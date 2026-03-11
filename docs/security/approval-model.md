# Approval Model

The current repo now implements the first real approval model for text-routed tasks.

Implemented approval classes:

- safe local actions
- user-confirm actions
- `sudo` actions
- destructive actions
- networked actions

Current behavior:

- `safe_local` executes immediately.
- `user_confirm`, `sudo`, `destructive`, and `network` return `approval_required` unless the caller explicitly opts into `--auto-approve`.
- Audit records are written to the SQLite database configured at `runtime.audit_db_path`.
- Codex is the execution backend for agentic tasks.
- Gemini is currently wired as a planning-oriented backend, not the primary mutation engine.
- Browser-state lookup is currently `safe_local`.
- Browser navigation to external URLs is currently treated as `network`.

Not solved yet:

- no voice-native approval UX exists yet
- no sudo prompt handoff exists yet
- no per-policy allowlist/denylist config exists yet
