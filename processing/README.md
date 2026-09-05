# Processing (Phase 2)

NLP enrichment and network-analysis stage that runs after `dadri`'s ingestion phase. It reads raw posts from `apitoprocessing.realdata1` (the same Atlas cluster and collection `dadri` writes to), scores them, and writes enriched documents to `processingtoanalytics.fakedata`.

## Layout

- `process_pipeline.py`: loads posts, builds an interaction graph (NetworkX PageRank) to score KOL centrality, runs emotion/stance classification (Hugging Face `transformers`) and spaCy keyword extraction, then upserts the enriched `ml_insights` block per post.
- `seed_fakedata.py`: generates 50 sample Twitter + Reddit posts matching the ingestion schema and inserts them into `apitoprocessing.fakedata` for local testing.

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
