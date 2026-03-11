# Remote API

The remote API is the first reusable transport layer for non-desktop access to `Dude`.

## Current Design

- Transport:
  - authenticated local HTTP server
  - standard-library implementation, no extra web framework required
  - defaults to `127.0.0.1:8765`
  - optional `dude tailscale-serve` helper can publish it privately over the tailnet
- UI:
  - browser-served remote web app at `/`
  - installable manifest and service worker bootstrap for PWA-style mobile use
- Authentication:
  - bearer token
  - token can be configured directly or generated on first run
  - generated token is stored locally at `runtime/remote-api.token`
- Reused core:
  - `/task` routes through the same orchestrator as the CLI and voice path
  - `/voice/task` transcribes uploaded audio and routes it through the same orchestrator
  - `/approve` reuses the same resumable approval flow
  - `/audit` returns the same SQLite-backed task history
  - `/memory`, `/memory/note`, `/memory/delete`, and `/memory/clear` expose the same local memory store
  - `/browser/state` exposes the last saved browser state
  - `/screen/state` exposes the last saved desktop-capture state
  - `/browser/last-screenshot`, `/screen/latest-artifact`, and `/reply/latest-audio` expose binary artifacts
  - `/screen/live.jpg` captures a fresh live desktop frame for remote visibility

## Why This Shape

- It creates one stable task API that later Android, Telegram, Tailscale, or PWA clients can reuse.
- It keeps approvals and audit in one place instead of inventing a separate remote execution path.
- It keeps task history and lightweight operator memory in the same local SQLite system of record.
- It now supports a practical near-live visibility path without committing to a full WebRTC stack yet.
- It stays private-by-default because it binds to localhost unless explicitly reconfigured.

## Current Limits

- Telegram now exists as a sibling transport, but Android-native and WebRTC clients do not.
- The API is a bootstrap transport, not the final mobile UX.
- It is currently a separate process via `dude remote-serve`, not yet folded into the main service lifecycle.
