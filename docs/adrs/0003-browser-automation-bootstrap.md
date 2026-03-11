# ADR 0003: Browser Automation Bootstrap

## Status

Accepted

## Decision

Add a local browser controller that:

- routes browser requests through the orchestrator
- defaults to headless capture with a saved screenshot artifact
- prefers Playwright when available
- falls back to Chrome headless CLI on this machine if Playwright is missing
- persists last-browser state so later `show me what you're doing` requests have a concrete answer

## Why

- Browser capability was the next major missing subsystem after orchestration.
- The repo already had approval and audit logging, so browser actions should reuse that path instead of bypassing it.
- This machine already has Google Chrome installed, so Chrome headless is a practical fallback that avoids blocking on package setup.

## Consequences

- The first browser milestone is pragmatic rather than fully featured.
- Playwright becomes the preferred long-term browser automation layer, but not a hard startup dependency.
- Remote visibility can later reuse the saved screenshot/state artifacts without rethinking the browser interface.
