# Security Policy

## Supported Scope

This project is still in active development. Security fixes will focus first on the currently implemented surfaces:

- local runtime and control socket
- approval and audit model
- remote HTTP API
- Telegram transport
- browser and screen visibility flows

## Reporting a Vulnerability

Do not open a public issue for an exploitable bug that could expose:

- remote control access
- tokens or credentials
- screen or audio data
- unsafe command execution
- privilege escalation

Instead, report it privately through GitHub security advisories for the repository once enabled, or contact the maintainer directly if a private channel is listed on the repository profile.

## Current Security Posture

- remote HTTP access is bearer-token protected and localhost by default
- Telegram access is allowlist-based by chat id
- system-affecting actions route through explicit approval classes
- audit records are stored locally in SQLite
- runtime artifacts and tokens are ignored by git

## Hardening Still In Progress

The following areas are known to be incomplete and should be treated accordingly:

- richer multi-user authorization
- sudo handoff UX
- live screen sharing beyond snapshot refresh
- deeper sandboxing policies for agentic backends
- speaker verification and user-profile isolation
