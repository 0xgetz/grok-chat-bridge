from __future__ import annotations

import abc
import logging

from ..session_manager import ChatKey, SessionManager

logger = logging.getLogger(__name__)


class PlatformBot(abc.ABC):
    name: str

    def __init__(self, sessions: SessionManager) -> None:
        self.sessions = sessions

    @abc.abstractmethod
    async def run(self) -> None:
        """Block until the platform disconnects."""

    async def handle_message(self, user_id: str, text: str, reply) -> None:
        """Shared grok round-trip; `reply(text)` sends platform response."""
        text = text.strip()
        if not text:
            await reply("Send a non-empty message.")
            return

        chat = ChatKey(platform=self.name, user_id=str(user_id))
        try:
            result = await self.sessions.ask(chat, text)
            body = result.text.strip() or "(no text response — check tool output in logs)"
            # Platform message limits vary; chunk for Discord/Telegram
            for chunk in _chunk(body, 4000):
                await reply(chunk)
        except Exception as exc:
            logger.exception("grok error for %s", chat.as_str())
            await reply(f"Error talking to grok: {exc}")


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    while text:
        parts.append(text[:size])
        text = text[size:]
    return parts
