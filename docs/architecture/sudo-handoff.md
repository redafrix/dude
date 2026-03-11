# Sudo Handoff

The orchestration bridge now has a real local sudo handoff path for approved Codex tasks.

## Current Design

- Tasks classified as `sudo` still require explicit approval first.
- After approval, Codex runs with:
  - `-a never`
  - `-s danger-full-access`
- The local runtime injects:
  - an askpass helper script
  - a `sudo` wrapper that forces `sudo -A`
  - request context for the desktop password prompt

## Prompt Backends

- `zenity`
- `systemd-ask-password`
- `auto`
- `none`

When `auto` is selected, Dude prefers `zenity` and falls back to `systemd-ask-password`.

## Why This Exists

- The earlier bridge approved tasks at the orchestrator level but still launched Codex with a
  non-interactive sudo-dead path.
- This keeps approval explicit while allowing the backend to continue after the desktop password
  prompt is satisfied.

## Current Limits

- This is aimed at Codex-driven sudo flows, not a full privilege broker for every subsystem.
- If no desktop askpass backend is available, sudo-class tasks fail with an explicit error instead
  of silently hanging.
