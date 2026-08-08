"""Discord bot via discord.py (optional extra)."""

from __future__ import annotations

import logging
import os
import re

from .base import PlatformBot

logger = logging.getLogger(__name__)


class DiscordBot(PlatformBot):
    name = "discord"

    def __init__(self, sessions, token: str | None = None) -> None:
        super().__init__(sessions)
        token = token or os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            raise RuntimeError(
                "DISCORD_BOT_TOKEN is required (set in .env or pass token=)"
            )
        self.token = token

    async def run(self) -> None:
        try:
            import discord
        except ImportError as exc:
            raise RuntimeError(
                "Install discord extra: pip install 'grok-chat-bridge[discord]'"
            ) from exc

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:
            logger.info("Discord logged in as %s", client.user)

        @client.event
        async def on_message(message: discord.Message) -> None:
            if message.author.bot:
                return
            if client.user not in message.mentions and not isinstance(
                message.channel, discord.DMChannel
            ):
                return

            user_id = message.author.id
            # Strip both mention forms (<@id> and nickname <@!id>).
            text = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()

            async with message.channel.typing():
                collected: list[str] = []

                async def reply(msg: str) -> None:
                    collected.append(msg)

                # Discord's message limit is 2000 chars; handle_message chunks
                # to fit so long grok replies are never silently truncated.
                await self.handle_message(user_id, text, reply, max_chunk=2000)

                for chunk in collected:
                    await message.reply(chunk)

        logger.info("Discord bot connecting\u2026")
        await client.start(self.token)
