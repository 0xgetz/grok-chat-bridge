"""Telegram bot via python-telegram-bot (optional extra)."""

from __future__ import annotations

import asyncio
import logging
import os

from .base import PlatformBot

logger = logging.getLogger(__name__)

# Telegram Bot API hard limit for message text.
_TELEGRAM_MAX_MESSAGE = 4096


class TelegramBot(PlatformBot):
    name = "telegram"

    def __init__(self, sessions, token: str | None = None) -> None:
        super().__init__(sessions)
        token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is required (set in .env or pass token=)"
            )
        self.token = token

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

            if not chunks:
                await status.edit_text("(empty response)")
                return

            # First chunk replaces the status bubble; further chunks are
            # new messages so long replies are not silently truncated.
            await status.edit_text(chunks[0][:_TELEGRAM_MAX_MESSAGE])
            for extra in chunks[1:]:
                await update.message.reply_text(extra[:_TELEGRAM_MAX_MESSAGE])

        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

        # run_polling() owns the event loop and breaks asyncio.gather with
        # other platforms. Use the granular async API on the shared loop.
        logger.info("Telegram bot polling…")
        await app.initialize()
        await app.start()
        assert app.updater is not None
        await app.updater.start_polling(drop_pending_updates=True)
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
