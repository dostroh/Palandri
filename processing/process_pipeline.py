import os

import spacy
import networkx as nx
import pymongo
from dotenv import load_dotenv
from transformers import pipeline

load_dotenv()

print("1. Initializing NLP Models & Graph Matrix...")
nlp = spacy.load("en_core_web_sm")

# Hugging Face models for emotion and zero-shot stance classification
emotion_model = pipeline("text-classification", model="SamLowe/roberta-base-go_emotions", top_k=3)
stance_model = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

STANCE_LABELS = ["against", "supportive", "neutral"]
TWITTER_PROFESSION_MARKERS = ("undergrad", "student")
TELEGRAM_STUDENT_MARKERS = ("sih", "hackathon", "student", "college", "aspirant")


def build_network_graph(posts):
    """Builds a NetworkX interaction graph to identify Key Opinion Leaders (KOLs)."""
    G = nx.DiGraph()

    # Add nodes and edges based on interactions
    for post in posts:
        author_id = post["author"]["user_id"]
        username = post["author"]["username"]
        G.add_node(author_id, username=username)

        interaction = post.get("interaction", {})
        if interaction.get("is_reply") and interaction.get("reply_to_user_id"):
            G.add_edge(author_id, interaction["reply_to_user_id"])

    # Calculate PageRank Centrality
    if len(G.nodes) > 0:
        pagerank = nx.pagerank(G, alpha=0.85)
    else:
        pagerank = {}

    return pagerank


def extract_keywords(doc):
    """spaCy noun-chunk keyword extraction, skipping stopword-rooted chunks and @mentions."""
    return [chunk.text for chunk in doc.noun_chunks if not chunk.root.is_stop and not chunk.text.startswith("@")]


def extract_sentiment(text):
    """Detects primary emotion, confidence, and distribution."""
    results = emotion_model(text, truncation=True)[0]
    primary_emotion = results[0]['label']
    confidence = round(results[0]['score'], 2)

    distribution = {res['label']: round(res['score'], 2) for res in results}

    negative_labels = {"anxiety", "fear", "anger", "frustration", "annoyance"}
    polarity = round(-0.5 - (confidence * 0.5), 2) if primary_emotion in negative_labels else round(0.5 + (confidence * 0.5), 2)

    return {
        "primary_emotion": primary_emotion,
        "emotion_distribution": distribution,
        "polarity_score": polarity,
        "sarcasm_flag": False,
        "confidence": confidence
    }


def extract_stance(text, target_entity):
    """Zero-shot stance classification against the extracted target entity."""
    stripped = text.strip()
    if not stripped:
        # Media-only posts (e.g. Telegram forwards with no caption) have nothing to classify.
        return {"target_entity": target_entity, "label": "neutral", "confidence": 0.0}

    # bart-large-mnli tops out at 1024 tokens; this pipeline has no truncation kwarg, so cap chars manually.
    result = stance_model(stripped[:2000], candidate_labels=STANCE_LABELS)
    return {
        "target_entity": target_entity,
        "label": result["labels"][0],
        "confidence": round(result["scores"][0], 2),
    }


def infer_location(location_raw):
    """Twitter's location_raw is free text like 'Delhi, India' -> keep just the city."""
    if not location_raw:
        return "Unknown"
    city = location_raw.split(",")[0].strip()
    return city or "Unknown"


def infer_twitter_profession(bio_text):
    if not bio_text:
        return "Unknown"
    bio_doc = nlp(bio_text)
    for chunk in bio_doc.noun_chunks:
        lowered = chunk.text.lower()
        if any(marker in lowered for marker in TWITTER_PROFESSION_MARKERS):
            return f"Student / {chunk.text}"
    return "Tech Professional"


def infer_telegram_profession(channel):
    channel_name = (channel.get("channel_name") or "").lower()
    return "Student" if any(marker in channel_name for marker in TELEGRAM_STUDENT_MARKERS) else "General User"


def extract_demographics(post):
    """Infers location, profession, and age bracket per-platform."""
    platform = post.get("platform", "Twitter")
    author = post.get("author") or {}

    if platform == "Twitter":
        location = infer_location(author.get("location_raw"))
        profession = infer_twitter_profession(author.get("bio"))
    elif platform == "Telegram":
        location = "Unknown"
        profession = infer_telegram_profession(post.get("channel") or {})
    else:
        location = "Unknown"
        subreddit = (post.get("subreddit") or "").lower()
        profession = "Developer" if "developers" in subreddit else "General User"

    return {
        "inferred_age_bracket": "18-24",
        "inferred_location": location,
        "inferred_profession": profession,
        "language": post.get("language") or "en"
    }


def extract_network_signals(post, user_id, centrality_scores):
    platform = post.get("platform", "Twitter")
    author = post.get("author") or {}
    interaction = post.get("interaction") or {}

    bot_likelihood_score = 0.95 if author.get("is_bot") else 0.05
    kol_weight = round(centrality_scores.get(user_id, 0.1), 3)

    signals = {
        "bot_likelihood_score": bot_likelihood_score,
        "centrality_seed_weight": kol_weight,
        "is_potential_kol": kol_weight > 0.25,
    }

    if platform == "Telegram":
        signals["forward_chain_depth"] = 1 if interaction.get("is_forwarded") else 0

    return signals


def compute_risk_score(polarity_score, stance_label, bot_likelihood_score):
    """Combines negative sentiment, an against-stance, and bot likelihood into one score."""
    score = (max(0.0, -polarity_score) * 10) + (5 if stance_label == "against" else 0) + (bot_likelihood_score * 10)
    return round(score)


def build_output_document(post, ml_insights):
    """Trims each platform's raw ingestion payload down to the processing->analytics contract."""
    platform = post.get("platform", "Twitter")
    author = post.get("author") or {}
    interaction = post.get("interaction") or {}

    output = {
        "post_id": post.get("post_id"),
        "platform": platform,
        "timestamp": post.get("timestamp"),
        "text": post.get("text"),
    }

    if platform == "Twitter":
        output["author"] = {
            "user_id": author.get("user_id"),
            "username": author.get("username"),
            "bio": author.get("bio"),
            "follower_count": author.get("follower_count"),
        }
        output["interaction"] = {
            "is_reply": interaction.get("is_reply", False),
            "reply_to_post_id": interaction.get("reply_to_post_id"),
            "reply_to_user_id": interaction.get("reply_to_user_id"),
            "mentions": interaction.get("mentions", []),
        }
    elif platform == "Telegram":
        channel = post.get("channel") or {}
        output["channel"] = {
            "channel_id": channel.get("channel_id"),
            "channel_name": channel.get("channel_name"),
            "channel_type": channel.get("channel_type"),
            "member_count": channel.get("member_count"),
        }
        output["author"] = {
            "user_id": author.get("user_id"),
            "username": author.get("username"),
            "display_name": author.get("display_name"),
            "is_bot": author.get("is_bot", False),
        }
        output["interaction"] = {
            "is_reply": interaction.get("is_reply", False),
            "reply_to_post_id": interaction.get("reply_to_post_id"),
            "reply_to_user_id": interaction.get("reply_to_user_id"),
            "is_forwarded": interaction.get("is_forwarded", False),
            "forwarded_from_channel": interaction.get("forwarded_from_channel"),
        }
    else:
        # Fallback for any other platform: pass author/interaction through as-is (minus engagement).
        if "channel" in post:
            output["channel"] = post["channel"]
        output["author"] = author
        output["interaction"] = interaction
        if "subreddit" in post:
            output["subreddit"] = post["subreddit"]

    output["ml_insights"] = ml_insights
    return output


def run_processing():
    MONGO_URI = os.environ.get("MONGODB_URI")
    if not MONGO_URI:
        print("MONGODB_URI is not set. Put it in a .env file (MONGODB_URI=<connection string>) or set it as an env var.")
        return
    try:
        client = pymongo.MongoClient(MONGO_URI)

        # 1. Load Raw Posts from apitoprocessing -> realdata1
        db_in = client["apitoprocessing"]
        col_in = db_in["realdata1"]
        posts = list(col_in.find({}))
        print(f"Loaded {len(posts)} posts from MongoDB (apitoprocessing.realdata1)")

        if not posts:
            print("No posts found in the source collection. Exiting.")
            return

    except Exception as e:
        print(f"MongoDB connection or read error: {e}")
        return

    # 2. Compute Graph Centrality across all posts
    centrality_scores = build_network_graph(posts)

    # 3. Process Each Post
    processed_posts = []
    print("Running NLP & Network analysis over posts...")

    for post in posts:
        text = post.get("text", "")
        user_id = post.get("author", {}).get("user_id", "Unknown")

        doc = nlp(text)
        keywords = extract_keywords(doc)
        target_entity = keywords[0] if keywords else "SIH Event"

        sentiment = extract_sentiment(text)
        stance = extract_stance(text, target_entity)
        network_signals = extract_network_signals(post, user_id, centrality_scores)
        risk_score = compute_risk_score(sentiment["polarity_score"], stance["label"], network_signals["bot_likelihood_score"])

        ml_insights = {
            "sentiment": sentiment,
            "stance": stance,
            "demographics": extract_demographics(post),
            "trends": {
                "extracted_keywords": keywords[:3],
                "topic_category": "Education / Hackathons",
                "topic_id": "TOPIC-0091"
            },
            "network_signals": network_signals,
            "burst_signal": {
                "topic_id": "TOPIC-0091",
                "z_score": 1.2,
                "is_burst": False
            },
            "risk_score": risk_score
        }
        processed_posts.append(build_output_document(post, ml_insights))

    # 4. Save Final Output to processingtoanalytics -> fakedata
    try:
        db_out = client["processingtoanalytics"]
        col_out = db_out["fakedata"]

        # Optional: Clear the destination collection before inserting new batch
        col_out.delete_many({})

        col_out.insert_many(processed_posts)
        print(f"Processing complete! Saved {len(processed_posts)} documents to MongoDB (processingtoanalytics.fakedata).")
    except Exception as e:
        print(f"MongoDB write error: {e}")

if __name__ == "__main__":
    run_processing()
