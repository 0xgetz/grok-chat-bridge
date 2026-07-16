"""Discord bot via discord.py (optional extra)."""

from __future__ import annotations

import logging
import os

from .base import PlatformBot

logger = logging.getLogger(__name__)


class DiscordBot(PlatformBot):
    name = "discord"

    def __init__(self, sessions, token: str | None = None) -> None:
        super().__init__(sessions)
        self.token = token or os.environ["DISCORD_BOT_TOKEN"]

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
            text = message.content.replace(f"<@{client.user.id}>", "").strip()

            async with message.channel.typing():
                collected: list[str] = []

                async def reply(msg: str) -> None:
                    collected.append(msg)

                await self.handle_message(user_id, text, reply)

                for chunk in collected:
                    await message.reply(chunk[:2000])

        logger.info("Discord bot connecting…")
        await client.start(self.token)
