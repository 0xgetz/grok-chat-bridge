"""Run one or more chat platform bots backed by grok ACP."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import GROK_VERSION_PIN, __version__
from .session_manager import SessionManager


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Chat bridge: Telegram / Discord / WhatsApp → grok (ACP stdio)"
    )
    parser.add_argument(
        "--platform",
        action="append",
        choices=["telegram", "discord", "whatsapp"],
        help="Enable platform (repeatable). Default: all with credentials set.",
    )
    parser.add_argument("--workdir", default=os.getcwd(), help="grok session cwd")
    parser.add_argument("--grok-bin", default=os.environ.get("GROK_BIN", "grok"))
    parser.add_argument("--model", default=os.environ.get("GROK_MODEL"))
    parser.add_argument("--smoke-test", action="store_true", help="ACP round-trip then exit")
    args = parser.parse_args()

    if args.smoke_test:
        asyncio.run(_smoke_test(args))
        return

    platforms = args.platform or _detect_platforms()
    if not platforms:
        parser.error(
            "No platforms enabled. Pass --platform or set bot tokens in .env"
        )

    asyncio.run(_run(platforms, args))


def _detect_platforms() -> list[str]:
    found: list[str] = []
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        found.append("telegram")
    if os.environ.get("DISCORD_BOT_TOKEN"):
        found.append("discord")
    if os.environ.get("WHATSAPP_ACCESS_TOKEN") and os.environ.get("WHATSAPP_PHONE_NUMBER_ID"):
        found.append("whatsapp")
    return found


async def _smoke_test(args: argparse.Namespace) -> None:
    from .acp.client import GrokAcpClient

    print(f"grok-chat-bridge {__version__} (pinned grok {GROK_VERSION_PIN})")
    client = GrokAcpClient(
        grok_bin=args.grok_bin,
        cwd=args.workdir,
        model=args.model,
    )
    try:
        init = await client.start()
        meta = init.get("_meta") or {}
        print(f"initialize ok — agentVersion={meta.get('agentVersion')}")
        sid = await client.new_session(args.workdir)
        print(f"session/new ok — sessionId={sid[:8]}…")
        prompt = os.environ.get("SMOKE_PROMPT", "Reply with exactly: pong")
        print(f"session/prompt: {prompt!r}")
        async for upd in client.prompt_stream(prompt):
            if upd.session_update == "agent_message_chunk" and upd.text:
                print(upd.text, end="", flush=True)
        print("\nsmoke test complete")
    finally:
        await client.close()


async def _run(platforms: list[str], args: argparse.Namespace) -> None:
    sessions = SessionManager(
        workdir=Path(args.workdir),
        grok_bin=args.grok_bin,
        model=args.model,
    )

    bots = []
    for name in platforms:
        if name == "telegram":
            from .platforms.telegram_bot import TelegramBot

            bots.append(TelegramBot(sessions))
        elif name == "discord":
            from .platforms.discord_bot import DiscordBot

            bots.append(DiscordBot(sessions))
        elif name == "whatsapp":
            from .platforms.whatsapp_bot import WhatsAppBot

            bots.append(WhatsAppBot(sessions))

    try:
        await asyncio.gather(*(b.run() for b in bots))
    finally:
        await sessions.close_all()


if __name__ == "__main__":
    main()
