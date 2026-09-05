import json
import os

import spacy
import networkx as nx
import pandas as pd
import pymongo
from dotenv import load_dotenv
from transformers import pipeline

load_dotenv()

print("1. Initializing NLP Models & Graph Matrix...")
nlp = spacy.load("en_core_web_sm")

# Hugging Face models for emotion and zero-shot stance classification
emotion_model = pipeline("text-classification", model="SamLowe/roberta-base-go_emotions", top_k=3)
stance_model = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")


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


def extract_demographics(post):
    """Infers location, profession, and age bracket."""
    author = post.get("author", {})
    platform = post.get("platform", "Twitter")

    if platform == "Twitter":
        location = author.get("location_raw") or author.get("bio", "Unknown")
        bio = (author.get("bio") or "").lower()
        profession = "Student / Undergrad" if "undergrad" in bio or "student" in bio else "Tech Professional"
    else:
        location = "Unknown"
        subreddit = post.get("subreddit", "")
        profession = "Developer" if "developers" in subreddit.lower() else "General User"

    return {
        "inferred_age_bracket": "18-24",
        "inferred_location": location if location != "" else "Unknown",
        "inferred_profession": profession,
        "language": post.get("language", "en")
    }


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
        # Remove MongoDB's internal _id to prevent insertion conflicts
        post.pop("_id", None)

        text = post.get("text", "")
        user_id = post.get("author", {}).get("user_id", "Unknown")

        # spaCy Keyword Extraction
        doc = nlp(text)
        keywords = [chunk.text for chunk in doc.noun_chunks if not chunk.root.is_stop and not chunk.text.startswith("@")]
        target = keywords[0] if keywords else "SIH Event"

        # Calculate PageRank Weight
        kol_weight = round(centrality_scores.get(user_id, 0.1), 3)

        # Assemble ML Insights block
        post["ml_insights"] = {
            "sentiment": extract_sentiment(text),
            "stance": {
                "target_entity": target,
                "label": "against" if "stress" in text.lower() or "panic" in text.lower() else "supportive",
                "confidence": 0.85
            },
            "demographics": extract_demographics(post),
            "trends": {
                "extracted_keywords": keywords[:3],
                "topic_category": "Education / Hackathons",
                "topic_id": "TOPIC-0091"
            },
            "network_signals": {
                "bot_likelihood_score": 0.04,
                "centrality_seed_weight": kol_weight,
                "is_potential_kol": kol_weight > 0.25
            },
            "burst_signal": {
                "topic_id": "TOPIC-0091",
                "z_score": 1.2,
                "is_burst": False
            },
            "risk_score": 14
        }
        processed_posts.append(post)

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
