# Telegram Transport

Telegram is now the first remote transport that leaves localhost while reusing the same local orchestration core.

## Current Design

- Process:
  - `dude telegram-serve`
  - long-polling transport over the Telegram Bot API
- Auth:
  - bot token from `telegram.bot_token` or `DUDE_TELEGRAM_BOT_TOKEN`
  - allowlist via `telegram.allowed_chat_ids`
- Message handling:
  - text messages route through the same orchestrator as CLI and HTTP
  - voice messages download the file bytes, transcribe locally, and route through the same orchestrator
  - replies can be text only or text plus synthesized local audio
  - screenshot and browser-capture tasks can also send back the latest local artifact
- Shared subsystems:
  - approvals
  - audit log
  - memory store
  - reply-audio generation

## Why This Shape

- It gives phone access quickly without forcing an Android APK first.
- It reuses the local task router instead of creating a second execution path.
- It keeps the Android-native path optional until Telegram is proven insufficient.

## Current Limits

- There is no live call mode.
- There is no live screen sharing over Telegram.
- Telegram is a transport layer, not the final rich mobile UX.
- Chat authorization is allowlist-based; there is no multi-user identity model yet.
