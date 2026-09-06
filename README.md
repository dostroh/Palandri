# Palandri

Social media intelligence for X and Telegram. Palandri collects posts, normalizes them into one schema regardless of source, scores them with NLP and graph analysis, and serves the result as a live console.

```
X / Telegram  →  apitoprocessing.realdata1  →  NLP + graph scoring  →  processingtoanalytics.fakedata  →  web console
   connectors        raw normalized posts          sentiment, stance,        posts + ml_insights            KPIs, timeline,
                                                   topic, network                                          graph, radar
```

Everything is read and written through MongoDB Atlas, so each stage can run independently — you can ingest for hours and score later, or poll and score a handful of posts on demand from the console.

## Layout

| Path | Purpose |
| --- | --- |
| `dadri/schemas/events.py` | Pydantic v2 contracts (`Post`, `Author`, `InteractionEdge`) with timezone-aware UTC timestamps |
| `dadri/connectors/base.py` | Pluggable batch connector interface |
| `dadri/connectors/x_twitter.py` | Async twscrape search adapter and JSON serializer |
| `dadri/connectors/telegram.py` | Async Telethon channel history and polling adapter |
| `dadri/storage/` | Atlas client, indexes, and bulk upserts |
| `dadri/workers/` | Connector-to-storage runners (`run_x`, `run_telegram`, `run_all`, `verify_mongo`) |
| `processing/process_pipeline.py` | Scores the whole collection and replaces the analytics output |
| `processing/analyzer.py` | Scores an explicit list of posts, leaving existing analytics untouched |
| `web/app.py` | FastAPI backend: read endpoints, `/api/intel`, and `/api/poll` |
| `web/static/` | Console UI (vanilla JS, ECharts vendored locally) |
| `telegram_login.py` | One-time interactive Telethon login |

## Install

```bash
pip install -e ".[all]"
python -m spacy download en_core_web_sm
```

`[all]` covers ingestion, scoring, and the console. Narrower extras exist if you only need part of it: `[x]`, `[telegram]`, `[language]`, `[web]`, `[processing]`. Provider SDKs are lazy-imported, so the schemas and custom connectors work without installing either platform SDK.

`torch` and `scipy` are pulled in by `[processing]` even though nothing imports them directly — `transformers` needs a backend and `networkx.pagerank` needs `scipy`.

## Configure

Copy `.env.example` to `.env` and fill it in. Never commit `.env`, cookie files, or session files; `.gitignore` already excludes `.env*`, `.data/`, `.venv/`, and `__pycache__`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MONGODB_URI` | — | Atlas connection string (required) |
| `MONGODB_DATABASE` | `apitoprocessing` | Database holding raw posts |
| `MONGODB_POSTS_COLLECTION` | `realdata1` | Raw post collection |
| `MONGODB_ANALYTICS_DATABASE` | `processingtoanalytics` | Database holding scored posts |
| `MONGODB_ANALYTICS_COLLECTION` | `fakedata` | Scored post collection |
| `POLL_LANGUAGE` | `en` | Language console polls are restricted to |
| `X_USERNAME`, `X_COOKIES_FILE` | — | X auth; cookie file needs `auth_token` and `ct0` |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | — | From https://my.telegram.org |
| `TELEGRAM_SESSION` | `.data/telegram` | Telethon session path |

Nothing under `dadri/` calls `load_dotenv()`, so the workers read the real environment. Export the variables in your shell, or use the console, which loads `.env` through uvicorn.

## Run the console

```bash
python -m uvicorn web.app:app --port 8000 --env-file .env --reload
```

On Windows: `.venv\Scripts\python.exe -m uvicorn web.app:app --port 8000 --env-file .env --reload`

Open `http://127.0.0.1:8000`. The console gives you a live timeline, a searchable archive, a per-post detail view with the full NLP breakdown, threat KPIs, an interaction graph, and an emotion radar. MongoDB credentials stay on the server and never reach the browser.

The **Poll new posts** bar fetches fresh posts from X (keywords) or Telegram (a channel), stores them, and scores only those. The first poll of a session takes roughly 60–90 seconds while spaCy and the transformer models load; later polls are fast.

Polling is restricted to English, because the NLP stack is English-only. X is filtered with its native `lang:` operator. Telegram messages carry no language tag, so `langdetect` is used, which also drops captionless media posts — there is nothing in them to score.

Telegram needs one interactive login first, since Telethon asks for a phone number and code that a web request cannot supply:

```bash
python telegram_login.py
```

The session is saved to `.data/telegram` and reused afterwards. For a bot account, set `TELEGRAM_BOT_TOKEN` instead.

To deploy on Render, connect the repository, use the included `render.yaml`, and add `MONGODB_URI` as a secret environment variable.

## HTTP API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Atlas connectivity check |
| `GET /api/summary` | Totals, language mix, platform mix, newest timestamp |
| `GET /api/posts` | Paged posts with `ml_insights` joined in; supports `q`, `language`, `platform` |
| `GET /api/edges` | Most recent interaction edges |
| `GET /api/intel` | KPIs, interaction graph, and emotion radar; `?q=` scopes all three |
| `POST /api/poll` | Fetch, store, and score fresh posts. Body: `{source: "x" \| "telegram", query, limit}` |

Everything except `/api/poll` is read-only.

## Continuous ingestion

For long-running collection outside the console, use the workers. Both platforms together:

```fish
set -x MONGODB_URI 'your-atlas-uri'
set -x MONGODB_DATABASE apitoprocessing
set -x MONGODB_POSTS_COLLECTION realdata1

set -x X_USERNAME your_handle
set -x X_COOKIES_FILE .data/x_cookies.json
set -x X_TOPICS 'finance,elections,markets'
set -x X_LANGUAGE en
set -x X_RESULTS_PER_POLL 1
set -x X_POLL_INTERVAL 5
set -x X_MAX_POLLS 100

set -x TELEGRAM_API_ID 'your-api-id'
set -x TELEGRAM_API_HASH 'your-api-hash'
set -x TELEGRAM_ENTITIES '@channel_one,@channel_two'
set -x TELEGRAM_LANGUAGE en
set -x TELEGRAM_POLL_INTERVAL 5
set -x TELEGRAM_MAX_POLLS 100

python -m dadri.workers.run_all
```

`X_TOPICS` becomes a single search such as `("finance" OR "elections" OR "markets") -filter:retweets`. Each entry in `TELEGRAM_ENTITIES` gets its own concurrent polling task. `Ctrl+C` stops every poller.

Single-platform runners are `python -m dadri.workers.run_x` and `python -m dadri.workers.run_telegram` (the latter reads `TELEGRAM_ENTITY`, singular). Each performs `X_MAX_POLLS` / `TELEGRAM_MAX_POLLS` cycles and exits; set it to `0` to skip polling. twscrape keeps its account session in `.data/x_accounts.db`.

Check what actually landed in Atlas from another terminal:

```bash
python -m dadri.workers.verify_mongo
```

An empty result means the search matched nothing yet — try a broader query.

## Scoring

`processing/process_pipeline.py` rescores everything and replaces the analytics collection:

```bash
python processing/process_pipeline.py
```

`processing/analyzer.py` scores a specific list of posts and leaves the rest alone; this is what `/api/poll` calls. It imports its scoring functions from `process_pipeline`, so the batch and on-demand paths cannot drift apart.

Each post is scored for emotion (GoEmotions, mapped to a valence-weighted polarity), stance against an extracted target entity, inferred demographics, keywords and topic, network position (PageRank centrality, bot likelihood), topic burst z-score, and a combined risk score.

## Data contracts

Raw posts land in `apitoprocessing.realdata1`. X payloads can be serialized with `payload_json(tweet)` or `XConnector.to_payload(tweet).as_json()`:

```json
{
  "post_id": "TWT-1001",
  "platform": "Twitter",
  "timestamp": "2026-09-05T10:15:30Z",
  "text": "...",
  "language": "en",
  "author": {
    "user_id": "U-8821",
    "username": "hackathon_kid",
    "bio": "...",
    "location_raw": "Delhi, India",
    "follower_count": 342,
    "following_count": 210,
    "account_created_at": "2023-02-11T00:00:00Z",
    "verified": false
  },
  "interaction": {
    "is_reply": false,
    "is_retweet": false,
    "is_quote": false,
    "conversation_id": "TWT-1001",
    "reply_to_post_id": null,
    "reply_to_user_id": null,
    "mentions": ["CodeMaster"],
    "hashtags": ["Elections2026"],
    "urls": []
  },
  "engagement": { "like_count": 12, "retweet_count": 3, "reply_count": 5 }
}
```

Telegram posts carry a `channel` block instead of the X-specific author and interaction fields.

Scored documents in `processingtoanalytics.fakedata` keep the identifying fields, drop the raw engagement block, and add `ml_insights`:

```json
{
  "post_id": "TWT-1001",
  "platform": "Twitter",
  "timestamp": "2026-09-05T10:15:30Z",
  "text": "...",
  "author": { "user_id": "U-8821", "username": "hackathon_kid", "bio": "...", "follower_count": 342 },
  "interaction": { "is_reply": false, "reply_to_post_id": null, "reply_to_user_id": null, "mentions": ["CodeMaster"] },
  "ml_insights": {
    "sentiment": { "primary_emotion": "...", "emotion_distribution": {}, "polarity_score": 0.0, "sarcasm_flag": false, "confidence": 0.0 },
    "stance": { "target_entity": "...", "label": "...", "confidence": 0.0 },
    "demographics": { "inferred_age_bracket": "...", "inferred_location": "...", "inferred_profession": "...", "language": "en" },
    "trends": { "extracted_keywords": [], "topic_category": "...", "topic_id": "TOPIC-0091" },
    "network_signals": { "bot_likelihood_score": 0.0, "centrality_seed_weight": 0.0, "is_potential_kol": false },
    "burst_signal": { "topic_id": "TOPIC-0091", "z_score": 0.0, "is_burst": false },
    "risk_score": 0
  }
}
```

Telegram documents additionally carry `network_signals.forward_chain_depth`.

## Notes

Source timestamps must be timezone-aware; they are normalized to UTC at validation time and naive timestamps are rejected. `post_id`, `author_id`, and edge endpoints are platform-prefixed to prevent collisions across sources, so a document's `_id` (`x_2096…`) differs from the `post_id` inside its body (`TWT-2096…`).

Authors and interaction edges are stored alongside posts in `authors` and `interaction_edges`.
