"""Minimal ACP client for `grok agent stdio` (JSON-RPC 2.0, newline-delimited).

Uses only the Python standard library so it runs on Termux/Android without
the `agent-client-protocol` PyPI package (which pulls pydantic-core/Rust).

Tested against: grok 0.2.101 (5bc4b5dfad)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1


class GrokAcpError(Exception):
    """ACP or subprocess failure."""


@dataclass
class PromptUpdate:
    """One streamed session/update notification."""

    session_update: str
    raw: dict[str, Any]

    @property
    def text(self) -> str:
        content = self.raw.get("content") or {}
        if isinstance(content, dict):
            return str(content.get("text") or "")
        return ""


@dataclass
class PromptResult:
    """Aggregated result of a prompt turn."""

    text: str
    updates: list[PromptUpdate] = field(default_factory=list)


class GrokAcpClient:
    """Talk to a single `grok agent stdio` subprocess."""

    def __init__(
        self,
        *,
        grok_bin: str | None = None,
        cwd: str | Path | None = None,
        model: str | None = None,
        always_approve: bool = True,
        no_leader: bool = True,
    ) -> None:
        self.grok_bin = grok_bin or os.environ.get("GROK_BIN", "grok")
        self.cwd = Path(cwd or os.getcwd()).resolve()
        self.model = model or os.environ.get("GROK_MODEL")
        self.always_approve = always_approve
        self.no_leader = no_leader

        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._update_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._next_id = 1
        self._session_id: str | None = None
        self._closed = False

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def start(self) -> dict[str, Any]:
        if not shutil.which(self.grok_bin):
            raise GrokAcpError(
                f"grok binary not found: {self.grok_bin!r}. "
                "Install via https://x.ai/cli or set GROK_BIN."
            )

        cmd = [self.grok_bin, "agent"]
        if self.no_leader:
            cmd.append("--no-leader")
        if self.always_approve:
            cmd.append("--always-approve")
        if self.model:
            cmd.extend(["-m", self.model])
        cmd.append("stdio")

        logger.info("spawning %s", " ".join(cmd))
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.cwd),
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        return await self.initialize()

    async def initialize(self) -> dict[str, Any]:
        return await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
            },
        )

    async def new_session(self, cwd: str | Path | None = None) -> str:
        workdir = Path(cwd or self.cwd).resolve()
        result = await self._request(
            "session/new",
            {"cwd": str(workdir), "mcpServers": []},
        )
        session_id = result.get("sessionId")
        if not session_id:
            raise GrokAcpError(f"session/new missing sessionId: {result!r}")
        self._session_id = session_id
        return session_id

    async def prompt_stream(self, text: str) -> AsyncIterator[PromptUpdate]:
        if not self._session_id:
            raise GrokAcpError("no session — call new_session() first")

        req_id = self._alloc_id()
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": text}],
            },
        }
        await self._send(message)
        response_future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = response_future

        try:
            while True:
                if response_future.done():
                    result = response_future.result()
                    if result.get("error"):
                        raise GrokAcpError(f"session/prompt error: {result['error']}")
                    return

                try:
                    update_msg = await asyncio.wait_for(
                        self._update_queue.get(), timeout=0.2
                    )
                except asyncio.TimeoutError:
                    continue

                update = update_msg.get("params", {}).get("update", {})
                if not update:
                    continue
                yield PromptUpdate(
                    session_update=str(update.get("sessionUpdate", "")),
                    raw=update,
                )
        finally:
            self._pending.pop(req_id, None)

    async def prompt(self, text: str) -> PromptResult:
        chunks: list[str] = []
        updates: list[PromptUpdate] = []
        async for upd in self.prompt_stream(text):
            updates.append(upd)
            if upd.session_update == "agent_message_chunk" and upd.text:
                chunks.append(upd.text)
        return PromptResult(text="".join(chunks), updates=updates)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        self._proc = None

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = self._alloc_id()
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        try:
            msg = await asyncio.wait_for(future, timeout=120)
        except asyncio.TimeoutError as exc:
            raise GrokAcpError(f"timeout waiting for {method}") from exc
        finally:
            self._pending.pop(req_id, None)

        if "error" in msg:
            raise GrokAcpError(f"{method} failed: {msg['error']}")
        return msg.get("result") or {}

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise GrokAcpError("subprocess not running")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    def _alloc_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            line = line.decode(errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("non-json from grok: %s", line[:200])
                continue
            await self._dispatch(msg)

        rc = await self._proc.wait() if self._proc else -1
        if not self._closed:
            logger.error("grok exited with code %s", rc)
            err = await self._drain_stderr()
            if err:
                logger.error("grok stderr: %s", err[-2000:])
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(GrokAcpError(f"grok exited ({rc})"))
            raise GrokAcpError(f"grok subprocess exited with code {rc}")

    async def _drain_stderr(self) -> str:
        if not self._proc or not self._proc.stderr:
            return ""
        try:
            data = await asyncio.wait_for(self._proc.stderr.read(), timeout=1)
            return data.decode(errors="replace")
        except asyncio.TimeoutError:
            return ""

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        # Agent → client request (needs response)
        if "id" in msg and "method" in msg and "result" not in msg and "error" not in msg:
            await self._reply_agent_request(msg)
            return

        method = msg.get("method")
        if method in ("session/update", "x.ai/session/update"):
            await self._update_queue.put(msg)
            return

        msg_id = msg.get("id")
        if msg_id is not None and msg_id in self._pending:
            fut = self._pending[msg_id]
            if not fut.done():
                fut.set_result(msg)
            return

        if method:
            logger.debug("ignored notification: %s", method)

    async def _reply_agent_request(self, msg: dict[str, Any]) -> None:
        """Best-effort auto-approve for headless bot operation."""
        method = msg.get("method", "")
        req_id = msg["id"]
        logger.debug("agent request: %s", method)

        if "permission" in method.lower():
            result = {"outcome": {"outcome": "approved"}}
        elif method == "authenticate":
            result = {"authenticated": True}
        else:
            result = {}

        await self._send({"jsonrpc": "2.0", "id": req_id, "result": result})
