"""One grok ACP session per chat user (platform + user id)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from .acp.client import GrokAcpClient, GrokAcpError, PromptResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatKey:
    platform: str
    user_id: str

    def as_str(self) -> str:
        return f"{self.platform}:{self.user_id}"


class SessionManager:
    def __init__(
        self,
        *,
        workdir: str | Path,
        grok_bin: str | None = None,
        model: str | None = None,
        max_sessions: int = 20,
    ) -> None:
        self.workdir = Path(workdir).resolve()
        self.grok_bin = grok_bin
        self.model = model
        self.max_sessions = max_sessions
        self._sessions: dict[str, GrokAcpClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def ask(self, chat: ChatKey, prompt: str) -> PromptResult:
        key = chat.as_str()
        async with self._lock_for(key):
            client = await self._get_or_create(key)
            try:
                return await client.prompt(prompt)
            except GrokAcpError:
                await self._evict(key)
                client = await self._get_or_create(key)
                return await client.prompt(prompt)

    async def _get_or_create(self, key: str) -> GrokAcpClient:
        if key in self._sessions:
            return self._sessions[key]

        if len(self._sessions) >= self.max_sessions:
            oldest = next(iter(self._sessions))
            await self._evict(oldest)

        client = GrokAcpClient(
            grok_bin=self.grok_bin,
            cwd=self.workdir,
            model=self.model,
        )
        await client.start()
        await client.new_session(self.workdir)
        self._sessions[key] = client
        logger.info("new ACP session %s -> %s", key, client.session_id)
        return client

    async def _evict(self, key: str) -> None:
        client = self._sessions.pop(key, None)
        if client:
            await client.close()

    async def close_all(self) -> None:
        for key in list(self._sessions):
            await self._evict(key)
