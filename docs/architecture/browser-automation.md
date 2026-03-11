# Browser Automation

The browser subsystem is the first non-trivial local capability built on top of the orchestrator and approval model.

## Current Design

- Default path:
  - route text through the orchestrator
  - classify browser-related requests as local browser tasks
  - require approval for browser navigation that opens network URLs
  - execute the browser action locally
  - record the action in the SQLite audit log
- Headless mode:
  - preferred engine is Playwright when installed
  - current runtime falls back to Chrome headless CLI if Playwright is unavailable
  - a screenshot artifact is written under `runtime/browser/`
  - headless requests can now also summarize a page, extract top links, click a visible target, or type into a field
- Visible mode:
  - explicit phrases such as `show me the page` or `deactivate headless`
  - launches a visible browser window with the system browser
- State reporting:
  - the last browser action is persisted to `runtime/browser/last-browser-state.json`
  - `show me what you're doing` returns the last known URL, mode, screenshot path, and excerpt when available

## Why This Shape

- It adds real browser capability without blocking on Playwright installation.
- It keeps browser actions auditable under the same task/audit model as other tools.
- It creates the minimal persistence needed for later remote screenshot/session features.
- It now covers the first useful read-only automation layer: open, search, summarize, and link extraction.

## Known Limits

- Headless capture, read-only inspection, and basic click/type automation are functional now, but full scripted interaction is still limited.
- Visible-mode browser launch does not yet provide live remote streaming.
- The current state model tracks the last browser artifact, not a full session graph.
- Playwright is optional today; richer DOM automation should standardize on it later.
