"""One-off: generate a Telethon StringSession for use in Railway env var TG_SESSION.

Usage:
    python scripts/login.py

Prompts for API_ID/API_HASH (from https://my.telegram.org), phone number, SMS code,
and optional 2FA password. Prints the resulting StringSession. Paste it into your
.env as TG_SESSION, and into Railway env var of the same name.
"""
from __future__ import annotations

import getpass
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


def _prompt(name: str, *, secret: bool = False) -> str:
    env = os.environ.get(name)
    if env:
        return env
    if secret:
        return getpass.getpass(f"{name}: ")
    return input(f"{name}: ").strip()


def main() -> None:
    api_id = int(_prompt("TG_API_ID"))
    api_hash = _prompt("TG_API_HASH", secret=True)

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        client.start()
        session_str = client.session.save()
        print()
        print("=" * 72)
        print("Your TG_SESSION (paste into .env and Railway env vars):")
        print()
        print(session_str)
        print("=" * 72)


if __name__ == "__main__":
    main()
