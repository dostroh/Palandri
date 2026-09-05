# Dadri Phase 1

Dadri is a normalized, chronological ingestion pipeline for social media intelligence. Phase 1 emits `Post`, `Author`, and `InteractionEdge` events from X and Telegram so later NLP, profiling, trend, and graph phases can consume the same contract.

## Layout

- `dadri/schemas/events.py`: Pydantic v2 contracts with timezone-aware UTC timestamps.
- `dadri/connectors/base.py`: pluggable batch connector interface.
- `dadri/connectors/x_twitter.py`: async twscrape search adapter and requested JSON serializer.
- `dadri/connectors/telegram.py`: async Telethon channel history/polling adapter.
- `dadri/storage/database.py`: MongoDB Atlas client and indexes.
- `dadri/storage/repository.py`: MongoDB bulk upserts.
- `dadri/workers/ingestion.py`: connector-to-storage workers.

## Install

```bash
pip install -e ".[x,telegram]"
```

The provider SDKs are lazy-imported, so schemas and custom connectors can be used without installing either platform SDK. `XConnector` uses twscrape's authenticated account pool and `TelegramConnector` uses Telethon.

## Start Telegram polling

Set your Telegram API credentials from `https://my.telegram.org` and the channel username or ID:

```fish
set -x TELEGRAM_API_ID '12345678'
set -x TELEGRAM_API_HASH 'your-api-hash'
set -x TELEGRAM_ENTITY '@your_channel'
set -x TELEGRAM_SESSION '.data/telegram'
set -x TELEGRAM_POLL_INTERVAL 5
set -x TELEGRAM_MAX_POLLS 100

python -m dadri.workers.run_telegram
```

The first run may ask for your Telegram phone number, login code, and 2FA password. The session is saved under `.data/telegram` and reused on later runs. For a bot, set `TELEGRAM_BOT_TOKEN` instead.

## Run X and Telegram together

Use the combined worker for multiple topics and channels:

```fish
set -x MONGODB_URI 'your-atlas-uri'
set -x MONGODB_DATABASE apitoprocessing
set -x MONGODB_POSTS_COLLECTION realdata1

set -x X_USERNAME sihwinner
set -x X_COOKIES_FILE .data/x_cookies.json
set -x X_TOPICS 'finance,SIH,Link Analysis'
set -x X_LANGUAGE en
set -x X_RESULTS_PER_POLL 1
set -x X_POLL_INTERVAL 5
set -x X_MAX_POLLS 100

set -x TELEGRAM_API_ID 'your-api-id'
set -x TELEGRAM_API_HASH 'your-api-hash'
set -x TELEGRAM_ENTITIES '@channel_one,@channel_two,@group_three'
set -x TELEGRAM_LANGUAGE en
set -x TELEGRAM_POLL_INTERVAL 5
set -x TELEGRAM_MAX_POLLS 100

python -m dadri.workers.run_all
```

`X_TOPICS` becomes one X search such as `("finance" OR "SIH" OR "Link Analysis") -filter:retweets`. Each value in `TELEGRAM_ENTITIES` gets its own concurrent polling task. Press `Ctrl+C` to stop all pollers.

`X_LANGUAGE=en` uses X's native `lang:en` search operator. `TELEGRAM_LANGUAGE=en` uses local language detection, so install it with `pip install -e ".[language]"`; Telegram does not provide a reliable language filter in Telethon itself.

## Start X polling

Initialize the database once, then start the five-second poller:

```bash
export X_USERNAME="your_x_username"
export X_EMAIL="your_x_email"        # optional for some Twikit accounts
export X_PASSWORD="your_x_password"
export DADRI_DATABASE_URL="postgresql+asyncpg://localhost/dadri"
export X_QUERY='"SIH" OR "Link Analysis"'

python -m dadri.workers.run_x
```

Set `X_POLL_INTERVAL=3` for three-second polling. Press `Ctrl+C` to stop it. The poller only persists newly seen post IDs during its process lifetime.

The runner performs 100 polls by default and then exits. Each poll requests one latest post and waits `X_POLL_INTERVAL` seconds before the next request. Set `X_MAX_POLLS=10` to run ten search cycles, or set `X_MAX_POLLS=0` for no polls. Use `X_RESULTS_PER_POLL` to request more than one result per cycle.

twscrape stores its account session in `.data/x_accounts.db`. A valid cookie file containing `auth_token` and `ct0` can be loaded through `X_COOKIES_FILE`; otherwise twscrape login requires `X_USERNAME`, `X_EMAIL`, `X_PASSWORD`, and `X_EMAIL_PASSWORD`.

Verify that real results reached Atlas from a second terminal:

```bash
python -m dadri.workers.verify_mongo
```

This prints collection counts and the newest stored post. An empty result means the X search returned no matching posts yet; try a broader `X_QUERY`, such as `SIH`.

The public X payload can be serialized with `payload_json(tweet)` or `XConnector.to_payload(tweet).as_json()` and has this shape:

```json
{
	"post_id": "TWT-1001",
	"timestamp": "2026-09-05T10:15:30Z",
	"text": "...",
	"author": {
		"user_id": "8821",
		"username": "hackathon_kid",
		"bio": "...",
		"follower_count": 342
	},
	"interaction": {
		"is_reply": false,
		"reply_to_post_id": null,
		"reply_to_user_id": null,
		"mentions": ["CodeMaster"]
	}
}
```

## MongoDB Atlas

```python
from dadri.storage.database import create_mongo_client, ensure_indexes, get_database
from dadri.workers.ingestion import run_backfill

client = create_mongo_client("mongodb+srv://USER:PASSWORD@cluster.mongodb.net/?retryWrites=true&w=majority")
database = get_database(client, "dadri")
await ensure_indexes(database)
await run_backfill(connector, database, start=start_utc, end=end_utc)
```

For the continuous X poller, set `MONGODB_URI` to the Atlas connection string. It writes posts to `apiprocessing.realdata1` by default. Authors and interaction edges are stored in `apiprocessing.authors` and `apiprocessing.interaction_edges`. Override the database or post collection with `MONGODB_DATABASE` or `MONGODB_POSTS_COLLECTION`.

All source timestamps must be timezone-aware. They are normalized to UTC at model validation time; naive timestamps are rejected. `post_id`, `author_id`, and edge endpoints are platform-prefixed to prevent cross-platform collisions.

## External web console

The read-only dashboard is served by FastAPI and reads `apitoprocessing.realdata1` through the backend; MongoDB credentials never reach the browser.

Run locally:

```fish
.venv/bin/python -m pip install -e ".[web]"
set -x MONGODB_URI 'mongodb+srv://USER:PASSWORD@cluster.mongodb.net/'
set -x MONGODB_DATABASE apitoprocessing
set -x MONGODB_POSTS_COLLECTION realdata1
.venv/bin/uvicorn web.app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. To host it on Render, connect this repository, use the included `render.yaml`, and add `MONGODB_URI` as a secret environment variable. The dashboard exposes only read endpoints: `/api/health`, `/api/summary`, `/api/posts`, and `/api/edges`.
