from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
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
    """One grok ACP session per chat user (platform + user id).

    Uses LRU eviction (least-recently-used) when max_sessions exceeded.
    Shared session dict mutations are protected by an asyncio lock for safety
    under concurrent access from multiple platform bots.
    """

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
        self._sessions: OrderedDict[str, GrokAcpClient] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._manager_lock: asyncio.Lock = asyncio.Lock()

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
        async with self._manager_lock:
            if key in self._sessions:
                self._sessions.move_to_end(key)
                return self._sessions[key]

            if len(self._sessions) >= self.max_sessions:
                oldest = next(iter(self._sessions))
                client_to_close = self._sessions.pop(oldest)
            else:
                client_to_close = None

            client = GrokAcpClient(
                grok_bin=self.grok_bin,
                cwd=self.workdir,
                model=self.model,
            )
            self._sessions[key] = client
            self._sessions.move_to_end(key)

        if client_to_close:
            await client_to_close.close()

        await client.start()
        await client.new_session(self.workdir)
        logger.info("new ACP session %s -> %s", key, client.session_id)
        return client

    async def _evict(self, key: str) -> None:
        async with self._manager_lock:
            client = self._sessions.pop(key, None)
        if client:
            await client.close()

    async def close_all(self) -> None:
        async with self._manager_lock:
            to_close = list(self._sessions.values())
            self._sessions.clear()
        for client in to_close:
            await client.close()
