# Processing (Phase 2)

NLP enrichment and network-analysis stage that runs after `dadri`'s ingestion phase. It reads raw posts from `apitoprocessing.realdata1` (the same Atlas cluster and collection `dadri` writes to), scores them, and writes enriched documents to `processingtoanalytics.fakedata`.

## Layout

- `process_pipeline.py`: loads posts, builds an interaction graph (NetworkX PageRank) to score KOL centrality, runs emotion/stance classification (Hugging Face `transformers`) and spaCy keyword extraction, then writes each post trimmed to the processing->analytics contract with an added `ml_insights` block.
- `seed_fakedata.py`: generates 50 sample Twitter + Reddit posts matching the ingestion schema and inserts them into `apitoprocessing.fakedata` for local testing.

## Output contract

Twitter and Telegram posts are trimmed to their own field sets before `ml_insights` is attached. Twitter keeps `author.{user_id,username,bio,follower_count}` and `interaction.{is_reply,reply_to_post_id,reply_to_user_id,mentions}`; Telegram keeps `channel.{channel_id,channel_name,channel_type,member_count}`, `author.{user_id,username,display_name,is_bot}`, and `interaction.{is_reply,reply_to_post_id,reply_to_user_id,is_forwarded,forwarded_from_channel}`. The raw `engagement` block is dropped for both, and Telegram additionally carries `ml_insights.network_signals.forward_chain_depth`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m spacy download en_core_web_sm
```

Copy `.env.example` to `.env` and fill in `MONGODB_URI`.

## Run

```bash
.venv\Scripts\python.exe seed_fakedata.py       # optional: seed sample data
.venv\Scripts\python.exe process_pipeline.py    # run enrichment
```
