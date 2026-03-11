# Files

The file controller handles obvious local filesystem tasks deterministically instead of sending them straight to a general agent backend.

## Current Design

- Safe read-only actions:
  - read file
  - list directory
  - find file by name
  - search text in files
- Write actions behind approval:
  - create file
  - create directory
  - copy path
  - move path
  - delete path
- Path handling:
  - quoted paths are preferred
  - relative paths resolve from the active working directory
  - `~` expands to the user home directory

## Why This Shape

- It keeps common local file tasks fast and predictable.
- It avoids wasting Codex/Gemini cycles on trivial deterministic operations.
- It preserves explicit approval for state-changing filesystem actions.

## Current Limits

- There is no recursive search or globbing assistant syntax yet.
- There is no sandbox boundary beyond the explicit approval class and current working directory context.
