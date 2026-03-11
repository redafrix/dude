# Memory

`Dude` now keeps a lightweight local memory layer in the same SQLite store as the task audit log.

## Current Design

- Storage:
  - SQLite table: `memory_entries`
  - lives in the same database as `tasks` and `actions`
  - default path: `runtime/dude.db`
- Entry kinds:
  - `task_summary`
  - `user_note`
- Sources:
  - completed and failed orchestrator tasks create automatic summaries
  - explicit notes can be added from CLI, remote API, or remote web UI
- Management:
  - list recent memory
  - add note
  - delete single entry
  - clear non-pinned entries

## Why This Shape

- It reuses the existing durable local system of record instead of creating a second database.
- It keeps memory inspectable and erasable, which is required for this project.
- It allows later preference injection, summaries, and persona tuning without hiding state in prompts.

## Current Limits

- Memory is not yet injected back into Codex or Gemini prompts automatically.
- There is no semantic retrieval or embedding index yet.
- There is no per-user profile split yet.
- Pinned-memory policy exists at the schema level, but the current operator surface does not expose pinning yet.
