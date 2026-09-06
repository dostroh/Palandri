# Processing

NLP and network scoring. Reads raw posts from `apitoprocessing.realdata1`, scores them, and writes enriched documents to `processingtoanalytics.fakedata`. See the [root README](../README.md) for the project as a whole.

## Layout

- `process_pipeline.py`: loads every post, builds an interaction graph (NetworkX PageRank) to score centrality, runs emotion/stance/topic classification (Hugging Face `transformers`) and spaCy keyword extraction, computes topic burst z-scores, then writes each post trimmed to the analytics contract with an added `ml_insights` block. Replaces the whole output collection.
- `analyzer.py`: scores an explicit list of posts and hands them back, leaving existing analytics untouched. This is what the console's `/api/poll` uses. It imports its scoring functions from `process_pipeline`, so the batch and on-demand paths cannot drift apart. Burst z-scores are measured against the whole corpus rather than the handful of posts in one poll, where they would be meaningless.
- `seed_fakedata.py`: generates 50 sample posts matching the ingestion schema for local testing.

## Output contract

Twitter and Telegram posts are trimmed to their own field sets before `ml_insights` is attached. Twitter keeps `author.{user_id,username,bio,follower_count}` and `interaction.{is_reply,reply_to_post_id,reply_to_user_id,mentions}`; Telegram keeps `channel.{channel_id,channel_name,channel_type,member_count}`, `author.{user_id,username,display_name,is_bot}`, and `interaction.{is_reply,reply_to_post_id,reply_to_user_id,is_forwarded,forwarded_from_channel}`. The raw `engagement` block is dropped for both, and Telegram additionally carries `ml_insights.network_signals.forward_chain_depth`.

`sentiment.polarity_score` is a confidence-weighted average over a valence lookup covering all 28 GoEmotions labels, rather than a positive/negative guess off the top label alone. `trends.topic_category` and `topic_id` come from zero-shot classification against the fixed list in `TOPIC_IDS`. `burst_signal` is a z-score of how over-represented a topic is across the scored set, with `is_burst` tripping past 1.5.

## Setup

From the repository root:

```bash
pip install -e ".[processing]"
python -m spacy download en_core_web_sm
```

Or standalone, with `pip install -r requirements.txt`. Either way, `MONGODB_URI` must be set — copy `.env.example` to `.env` and fill it in.

## Run

```bash
python processing/seed_fakedata.py       # optional: seed sample data
python processing/process_pipeline.py    # score everything
```

Scoring loads spaCy plus two transformer models (~2 GB), so the first run takes a while before any output appears.
