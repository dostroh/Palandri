"""One-time interactive Telegram login.

Telethon needs a phone number and the code Telegram sends you, which can't happen
from a web request. Run this once in a terminal; it writes an authorized session to
TELEGRAM_SESSION (.data/telegram by default) that the web app's /api/poll reuses.

    .venv\\Scripts\\python.exe telegram_login.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()


async def main() -> None:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")

    session = os.getenv("TELEGRAM_SESSION", ".data/telegram")
    Path(session).parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(session, int(api_id), api_hash)
    print(f"Session file: {session}")
    print("Telegram will ask for your phone number (with country code, e.g. +91...),")
    print("then the login code it sends you, then your 2FA password if you have one.\n")

    # start() prompts on stdin for whatever it still needs, and no-ops if already authorized.
    await client.start()

    me = await client.get_me()
    handle = f"@{me.username}" if getattr(me, "username", None) else (me.first_name or "account")
    print(f"\nLogged in as {handle} (id {me.id}). Session saved.")
    print("The web app's Telegram polling will now work; you won't need to log in again.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
