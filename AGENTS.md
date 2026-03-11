# AGENTS.md

This file is the operating map for the `Dude` repository. Durable decisions belong in `docs/`, not here.

## Repo Map

- `src/dude/`: runtime code and CLI
- `tests/`: unit and integration tests
- `configs/`: versioned runtime configuration
- `ops/systemd/`: user service units
- `docs/architecture/`: system and sequence notes
- `docs/adrs/`: architecture decision records
- `docs/research/`: source-backed subsystem comparisons
- `docs/benchmarks/`: measured machine-specific results
- `benchmarks/`: harness code and benchmark outputs
- `fixtures/`: audio fixtures and scenario manifests
- runtime audit data defaults to `runtime/dude.db`
- browser artifacts and last-browser state default to `runtime/browser/`
- remote API token defaults to `runtime/remote-api.token`

## Working Rules

- Keep the runtime local-first and explicit about any remote reasoning backend.
- Add or update ADRs when stack decisions materially change.
- Do not expand this file into a giant prompt dump; link deeper docs instead.
- Every feature should land with tests, measurements, and docs updates.
- Keep the public CLI stable while internal transport changes; `arm`, `disarm`, `status`, and `shutdown` should remain the operator surface.
- Route new capability surfaces through the orchestrator when they touch system state or approvals.

## Milestone 1 Focus

- GNOME/X11 activation
- armed listening
- wake phrase `Dude`
- local VAD/ASR/TTS loop
- Unix-socket control plane
- fixture recording and eval harness
- task routing, approvals, and audit logging
- browser screenshots and last-state visibility
- authenticated HTTP transport bootstrap
- logs, traces, and benchmark outputs
- runtime config lives in [`configs/default.yaml`](/home/redafrix/tests/dude/configs/default.yaml)
