"""WhatsApp Cloud API webhook server (Meta Business Platform).

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN
Optional:
  WHATSAPP_APP_SECRET (for X-Hub-Signature-256 validation - recommended for production)
  WHATSAPP_WEBHOOK_HOST (default 0.0.0.0), WHATSAPP_WEBHOOK_PORT (default 8080)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

from .base import PlatformBot

logger = logging.getLogger(__name__)

# Hard cap on inbound webhook body to avoid unbounded memory allocation.
_MAX_WEBHOOK_BODY_BYTES = 1_048_576  # 1 MiB


class WhatsAppBot(PlatformBot):
    name = "whatsapp"

    def __init__(self, sessions) -> None:
        super().__init__(sessions)
        token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
        if not token:
            raise RuntimeError(
                "WHATSAPP_ACCESS_TOKEN is required (set in .env)"
            )
        self.token = token
        phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        if not phone_id:
            raise RuntimeError(
                "WHATSAPP_PHONE_NUMBER_ID is required (set in .env)"
            )
        self.phone_id = phone_id
        verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN")
        if not verify_token:
            raise RuntimeError(
                "WHATSAPP_VERIFY_TOKEN is required (set in .env)"
            )
        self.verify_token = verify_token
        self.app_secret = os.environ.get("WHATSAPP_APP_SECRET")
        self.host = os.environ.get("WHATSAPP_WEBHOOK_HOST", "0.0.0.0")
        self.port = int(os.environ.get("WHATSAPP_WEBHOOK_PORT", "8080"))

    async def run(self) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "Install whatsapp extra: pip install 'grok-chat-bridge[whatsapp]'"
            ) from exc

        bot = self
        loop = asyncio.get_running_loop()

        if not self.app_secret:
            logger.warning(
                "WHATSAPP_APP_SECRET is not set — webhook POSTs are not "
                "signature-verified. Set it in production to enable "
                "X-Hub-Signature-256 validation and reject spoofed traffic."
            )

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args) -> None:
                logger.debug(fmt, *args)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/webhook":
                    self.send_error(404)
                    return
                qs = parse_qs(parsed.query)
                mode = qs.get("hub.mode", [""])[0]
                token = qs.get("hub.verify_token", [""])[0]
                challenge = qs.get("hub.challenge", [""])[0]
                # Constant-time compare to reduce timing side-channels.
                token_ok = hmac.compare_digest(token, bot.verify_token)
                if mode == "subscribe" and token_ok:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(challenge.encode())
                else:
                    self.send_error(403)

            def do_POST(self) -> None:
                if self.path != "/webhook":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    self.send_error(400)
                    return
                if length < 0 or length > _MAX_WEBHOOK_BODY_BYTES:
                    logger.warning(
                        "rejecting webhook body: Content-Length=%s (max %s)",
                        length,
                        _MAX_WEBHOOK_BODY_BYTES,
                    )
                    self.send_error(413)
                    return
                body = self.rfile.read(length)

                # Security: optional signature verification (Meta best practice)
                if bot.app_secret:
                    sig_header = self.headers.get("X-Hub-Signature-256", "")
                    if not sig_header.startswith("sha256="):
                        logger.warning("missing/invalid X-Hub-Signature-256 header")
                        self.send_error(403)
                        return
                    expected_sig = "sha256=" + hmac.new(
                        bot.app_secret.encode("utf-8"), body, hashlib.sha256
                    ).hexdigest()
                    if not hmac.compare_digest(expected_sig, sig_header):
                        logger.warning("webhook signature mismatch - possible spoofing attempt")
                        self.send_error(403)
                        return

                self.send_response(200)
                self.end_headers()
                asyncio.run_coroutine_threadsafe(
                    bot._on_webhook(body, httpx), loop
                )

        server = HTTPServer((self.host, self.port), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(
            "WhatsApp webhook listening on http://%s:%s/webhook", self.host, self.port
        )

        # Keep asyncio task alive
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            server.shutdown()

    async def _on_webhook(self, body: bytes, httpx_module) -> None:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("invalid whatsapp webhook json")
            return

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    user_id = msg.get("from", "")
                    text = msg.get("text", {}).get("body", "")
                    await self._handle_whatsapp(user_id, text, httpx_module)

    async def _handle_whatsapp(self, user_id: str, text: str, httpx_module) -> None:
        async def reply(msg: str) -> None:
            url = f"https://graph.facebook.com/v21.0/{self.phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
            for chunk in [msg[i : i + 4096] for i in range(0, len(msg), 4096)]:
                body = {
                    "messaging_product": "whatsapp",
                    "to": user_id,
                    "type": "text",
                    "text": {"body": chunk},
                }
                async with httpx_module.AsyncClient(timeout=30) as client:
                    resp = await client.post(url, headers=headers, json=body)
                    if resp.status_code >= 400:
                        logger.error("whatsapp send failed: %s %s", resp.status_code, resp.text)

        await self.handle_message(user_id, text, reply)
