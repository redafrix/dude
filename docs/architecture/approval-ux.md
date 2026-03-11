# Approval UX

The approval system now has a user-facing layer on top of the underlying audit and policy engine.

## Current Design

- Core approval state:
  - approval classes are assigned in the orchestrator
  - pending tasks are stored in SQLite
  - tasks can still be resumed through CLI, HTTP, or Telegram flows
- Voice path:
  - if a voice-triggered task requires approval, the service can trigger a desktop prompt
  - `zenity` is preferred when available
  - `notify-send` is used as a fallback notification path
- Remote path:
  - HTTP and PWA clients still use explicit `/approve`
  - Telegram still uses explicit chat-driven approval flow

## Why This Shape

- It keeps approvals explicit and auditable.
- It improves voice-driven usability without bypassing the existing approval model.
- It avoids embedding UI code in the orchestrator itself.

## Current Limits

- This is not yet a sudo credential handoff.
- Prompting is desktop-environment dependent.
- There is no richer approval policy editor yet.
