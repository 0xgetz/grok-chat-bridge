"""Telegram bot via python-telegram-bot (optional extra)."""

from __future__ import annotations

import logging
import os

from .base import PlatformBot

logger = logging.getLogger(__name__)


class TelegramBot(PlatformBot):
    name = "telegram"

    def __init__(self, sessions, token: str | None = None) -> None:
        super().__init__(sessions)
        self.token = token or os.environ["TELEGRAM_BOT_TOKEN"]

    async def run(self) -> None:
        try:
            from telegram import Update
            from telegram.ext import Application, CommandHandler, MessageHandler, filters
        except ImportError as exc:
            raise RuntimeError(
                "Install telegram extra: pip install 'grok-chat-bridge[telegram]'"
            ) from exc

        app = Application.builder().token(self.token).build()

        async def start(update: Update, _) -> None:
            if update.effective_user and update.message:
                await update.message.reply_text(
                    "Connected to grok via ACP. Send any message and I'll forward it."
                )

        async def on_text(update: Update, _) -> None:
            if not update.effective_user or not update.message or not update.message.text:
                return
            user_id = update.effective_user.id
            text = update.message.text

            status = await update.message.reply_text("⏳ Thinking…")
            chunks: list[str] = []

            async def reply(msg: str) -> None:
                chunks.append(msg)

            await self.handle_message(user_id, text, reply)
            final = "\n\n".join(chunks) if chunks else "(empty response)"
            await status.edit_text(final[:4096])

        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

        logger.info("Telegram bot polling…")
        await app.run_polling(drop_pending_updates=True)
