"""
Seeds 50 fake posts (Twitter + Reddit) into apitoprocessing.fakedata.

Setup:
    1. Create a .env file next to this script with:
           MONGODB_URI=<your connection string>
       (or set the MONGODB_URI environment variable another way)
    2. Run with the project venv:
           .venv\\Scripts\\python.exe seed_fakedata.py
"""

import os
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

DB_NAME = "apitoprocessing"
COLLECTION_NAME = "fakedata"
NUM_DOCUMENTS = 50

TWITTER_USERNAMES = [
    "hackathon_kid", "code_ninja99", "delhi_dev", "ai_curious", "byte_wanderer",
    "snu_scholar", "quantum_leap", "debug_diva", "cloud_surfer", "night_owl_dev",
]

REDDIT_USERNAMES = [
    "throwaway_dev22", "quiet_lurker7", "sih_grinder", "null_pointer_x",
    "devs_of_india", "burnt_out_intern", "recursive_soul", "stackoverflow_ghost",
]

BIOS = [
    "CS Undergrad at SNU | Tech enthusiast from Delhi | Building AI bots",
    "Full-stack dev | Open source contributor | Coffee-powered",
    "ML enthusiast, forever debugging | IIT dropout turned founder",
    "Competitive programmer | Loves system design | Bangalore based",
    "Building things that break in production | SIH participant 2026",
    "Backend engineer | Distributed systems nerd | Cat person",
    None,
]

LOCATIONS = ["Delhi, India", "Bangalore, India", "Mumbai, India", "Hyderabad, India", "Pune, India", None]

TOPICS = [
    "Link Analysis", "Sentiment Detection", "Bot Classification", "Graph Clustering",
    "Real-time Ingestion", "Anomaly Detection", "Network Visualization", "NLP Pipeline",
    "PageRank", "Trend Scoring",
]

MENTIONS = ["CodeMaster", "DevGuru", "SIH_Mentor", "TeamLead_Riya", "backend_baba", "algo_queen"]

HASHTAGS = ["SIH2026", "Hackathon", "BuildInPublic", "AI", "DevLife"]

SUBREDDITS = ["r/developersIndia", "r/india", "r/learnprogramming", "r/MachineLearning", "r/webdev"]

FLAIRS = ["Discussion", "Help", "Rant", "Question", "Showcase"]

TWEET_TEMPLATES = [
    "The new SIH guidelines are completely stressing me out. Does anyone know how to handle the {topic} part? @{mention} help!",
    "Just pushed a fix for the {topic} module, finally works after 6 hours of debugging.",
    "Can someone explain how {topic} is supposed to scale? Docs are unclear @{mention}",
    "Hot take: {topic} is overrated and everyone's overengineering it for this hackathon.",
    "Shoutout to @{mention} for helping me untangle the {topic} pipeline last night.",
    "Anyone else's {topic} implementation randomly failing on edge cases? Losing my mind.",
]

REDDIT_TEMPLATES = [
    "Anyone else panicking about the {topic} phase for SIH? Feels impossible to finish in time.",
    "PSA: don't leave {topic} for the last day like I did. 10/10 do not recommend.",
    "Wrote up my approach to {topic} for our SIH submission, happy to share notes if anyone's stuck.",
    "Is it just me or is {topic} massively underdocumented for this problem statement?",
    "Our team finally cracked {topic} after two all-nighters. Worth it though.",
]


def random_timestamp():
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    offset = timedelta(
        days=random.randint(0, 4),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )
    return (base + offset).strftime("%Y-%m-%dT%H:%M:%SZ")


def random_account_created():
    start = datetime(2018, 1, 1, tzinfo=timezone.utc)
    days_range = (datetime(2025, 12, 31, tzinfo=timezone.utc) - start).days
    created = start + timedelta(days=random.randint(0, days_range))
    return created.strftime("%Y-%m-%dT00:00:00Z")


def make_twitter_document(index, post_id):
    username = random.choice(TWITTER_USERNAMES)
    mention = random.choice(MENTIONS)
    topic = random.choice(TOPICS)
    text = random.choice(TWEET_TEMPLATES).format(topic=topic, mention=mention)

    is_reply = random.random() < 0.3
    conversation_id = post_id
    reply_to_post_id = None
    reply_to_user_id = None
    if is_reply:
        reply_to_post_id = f"TWT-{random.randint(1000, 1000 + index)}"
        reply_to_user_id = f"U-{random.randint(8000, 8999)}"
        conversation_id = reply_to_post_id

    mentions = [mention] if f"@{mention}" in text else []
    hashtags = random.sample(HASHTAGS, k=random.randint(0, 2))

    return {
        "post_id": post_id,
        "platform": "Twitter",
        "timestamp": random_timestamp(),
        "text": text,
        "language": "en",
        "author": {
            "user_id": f"U-{random.randint(8000, 8999)}",
            "username": username,
            "bio": random.choice(BIOS),
            "location_raw": random.choice(LOCATIONS),
            "follower_count": random.randint(10, 5000),
            "following_count": random.randint(10, 2000),
            "account_created_at": random_account_created(),
            "verified": random.random() < 0.05,
        },
        "interaction": {
            "is_reply": is_reply,
            "is_retweet": random.random() < 0.1,
            "is_quote": random.random() < 0.05,
            "conversation_id": conversation_id,
            "reply_to_post_id": reply_to_post_id,
            "reply_to_user_id": reply_to_user_id,
            "mentions": mentions,
            "hashtags": hashtags,
            "urls": [],
        },
        "engagement": {
            "like_count": random.randint(0, 500),
            "retweet_count": random.randint(0, 100),
            "reply_count": random.randint(0, 50),
            "quote_count": random.randint(0, 20),
            "impression_count": random.randint(100, 20000),
        },
    }


def make_reddit_document(index, post_id):
    username = random.choice(REDDIT_USERNAMES)
    topic = random.choice(TOPICS)
    text = random.choice(REDDIT_TEMPLATES).format(topic=topic)

    is_reply = random.random() < 0.4
    parent_id = None
    link_id = post_id
    reply_to_user_id = None
    if is_reply:
        parent_id = f"RDT-{random.randint(2000, 2000 + index)}"
        link_id = parent_id
        reply_to_user_id = f"U-{random.randint(9000, 9999)}"

    return {
        "post_id": post_id,
        "platform": "Reddit",
        "timestamp": random_timestamp(),
        "text": text,
        "language": "en",
        "subreddit": random.choice(SUBREDDITS),
        "author": {
            "user_id": f"U-{random.randint(9000, 9999)}",
            "username": username,
            "account_created_at": random_account_created(),
            "comment_karma": random.randint(0, 20000),
            "link_karma": random.randint(0, 5000),
        },
        "interaction": {
            "is_reply": is_reply,
            "parent_id": parent_id,
            "link_id": link_id,
            "reply_to_user_id": reply_to_user_id,
            "flair_text": random.choice(FLAIRS),
        },
        "engagement": {
            "score": random.randint(-5, 500),
            "upvote_ratio": round(random.uniform(0.5, 1.0), 2),
            "num_comments": random.randint(0, 50),
        },
    }


def make_documents(count):
    documents = []
    for i in range(count):
        if i % 2 == 0:
            documents.append(make_twitter_document(i, f"TWT-{1001 + i}"))
        else:
            documents.append(make_reddit_document(i, f"RDT-{2001 + i}"))
    return documents


def main():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise SystemExit(
            "MONGODB_URI is not set. Put it in a .env file next to this script "
            "(MONGODB_URI=<your connection string>) or set it as an env var."
        )

    client = MongoClient(uri)
    collection = client[DB_NAME][COLLECTION_NAME]

    documents = make_documents(NUM_DOCUMENTS)
    result = collection.insert_many(documents)

    print(f"Inserted {len(result.inserted_ids)} documents into {DB_NAME}.{COLLECTION_NAME}")
    client.close()


if __name__ == "__main__":
    main()
