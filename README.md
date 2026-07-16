# grok-chat-bridge

Telegram, Discord, and WhatsApp bots that use **[grok](https://github.com/xai-org/grok-build)** as the AI backend via the **Agent Client Protocol (ACP)** — no Rust crates imported.

```
Chat user  →  Platform bot  →  grok-chat-bridge  →  grok agent stdio  →  xAI
                (Telegram/       (Python ACP          (JSON-RPC over
                 Discord/         client)              stdin/stdout)
                 WhatsApp)
```

## Requirements

| Item | Notes |
|------|-------|
| `grok` CLI | `grok --version` → **0.2.101** tested (pin this for production) |
| Auth | `grok login` or `~/.grok/auth.json` or `XAI_API_KEY` |
| Python | 3.10+ |
| Platform tokens | See `.env.example` |

ACP entry point (verified):

```bash
grok agent --no-leader --always-approve stdio
```

## Quick start

```bash
git clone https://github.com/0xgetz/grok-chat-bridge.git
cd grok-chat-bridge
cp .env.example .env
# edit .env with your bot tokens

pip install -e ".[all]"   # or per-platform extras below
pip install -e .          # core only (smoke test)

# Verify ACP round-trip
python -m grok_chat_bridge --smoke-test
```

## Run bots

```bash
# All platforms that have tokens in .env
python -m grok_chat_bridge

# Specific platforms
python -m grok_chat_bridge --platform telegram --platform discord
python -m grok_chat_bridge --platform whatsapp
```

### Optional extras

```bash
pip install -e ".[telegram]"   # python-telegram-bot
pip install -e ".[discord]"      # discord.py
pip install -e ".[whatsapp]"     # httpx (Cloud API)
pip install -e ".[all]"
```

## Platform setup

### Telegram

1. Create bot via [@BotFather](https://t.me/BotFather)
2. Set `TELEGRAM_BOT_TOKEN` in `.env`
3. Run: `python -m grok_chat_bridge --platform telegram`

### Discord

1. [Discord Developer Portal](https://discord.com/developers/applications) → Bot → Token
2. Enable **Message Content Intent**
3. Set `DISCORD_BOT_TOKEN`
4. Mention the bot or DM it

### WhatsApp (Cloud API)

1. [Meta for Developers](https://developers.facebook.com/) → WhatsApp Business
2. Set `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`
3. Configure webhook URL: `https://your-host/webhook`
4. Run bridge with a public tunnel (ngrok, cloudflare tunnel):

```bash
python -m grok_chat_bridge --platform whatsapp
```

## Architecture

### ACP flow (per user message)

1. `initialize` — negotiate capabilities
2. `session/new` — one session per `(platform, user_id)` (cached)
3. `session/prompt` — send user text
4. Stream `session/update` with `agent_message_chunk` until turn ends

### Why not `agent-client-protocol` PyPI?

The official SDK pulls `pydantic-core` (Rust). On Termux/Android it often fails to build. This project uses a **stdlib JSON-RPC client** (`grok_chat_bridge/acp/client.py`) tested against grok 0.2.101. You can swap in the official SDK on desktop Linux/macOS later.

### Session model

- One `grok agent stdio` subprocess per chat user
- LRU eviction when `max_sessions` (default 20) exceeded
- Working directory: `--workdir` (default cwd)

## Environment

| Variable | Description |
|----------|-------------|
| `GROK_BIN` | Path to grok (default: `grok`) |
| `GROK_MODEL` | e.g. `grok-composer-2.5-fast` |
| `TELEGRAM_BOT_TOKEN` | Telegram |
| `DISCORD_BOT_TOKEN` | Discord |
| `WHATSAPP_*` | Meta Cloud API |

## Hardening

- Subprocess crash → error reply to user, session evicted and recreated on retry
- Malformed JSON from grok → logged, skipped
- Permission requests from agent → auto-approved (grok also runs with `--always-approve`)
- **Pin** `grok 0.2.101` — beta behavior may change

## Development

```bash
python -m grok_chat_bridge --smoke-test
SMOKE_PROMPT="Say hello" python -m grok_chat_bridge --smoke-test
```

## References

- [grok agent mode docs](https://docs.x.ai/build/overview) / shipped `15-agent-mode.md`
- [ACP spec](https://agentclientprotocol.com)
- [grok-build](https://github.com/xai-org/grok-build)
- Tested grok: `0.2.101 (5bc4b5dfad)`

## License

Apache-2.0
