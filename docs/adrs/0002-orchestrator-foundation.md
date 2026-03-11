# ADR 0002: Orchestrator Foundation

## Status

Accepted

## Decision

The next subsystem after the voice foundation is a local orchestration layer with:

- deterministic local-tool routing first
- explicit approval classes
- Codex as the execution backend
- Gemini as a planning-oriented secondary backend
- SQLite audit logging for tasks and actions

## Why

- The project needed a real action core before browser automation, remote access, or richer autonomy.
- Approval and audit had to exist before allowing agentic execution.
- SQLite is sufficient for local durability, simple inspection, and future memory/history reuse.

## Consequences

- Voice requests still do not have a native approval UX yet.
- Gemini is integrated, but currently more useful as a reasoning path than as the mutation engine.
- Browser automation and remote access should build on this audit/approval layer instead of bypassing it.
