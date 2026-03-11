# Contributing

## Scope

`Dude` is being built as a local-first Linux assistant with measurable voice quality, explicit approvals, and public-repo-grade documentation. Contributions should preserve that direction.

## Development Setup

```bash
uv venv
uv sync --extra dev --extra tts
source .venv/bin/activate
```

Optional extras:

```bash
uv sync --extra dev --extra tts --extra wake --extra vad --extra browser --extra cuda_asr
```

## Before Sending Changes

Run the same local checks used in development:

```bash
uv run ruff check .
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q
```

If you change runtime behavior, also update the relevant docs under `docs/`, especially:

- `docs/architecture/`
- `docs/adrs/`
- `docs/roadmap/`
- `docs/benchmarks/`

## Change Expectations

- keep the runtime local-first and explicit about any remote reasoning backend
- route new system-affecting capabilities through the orchestrator
- keep the operator CLI stable where practical
- land tests with the feature, not later
- document stack changes with an ADR when they materially affect architecture

## Large Changes

For bigger features, preserve the working pattern already used in the repo:

1. research the subsystem
2. implement the smallest useful slice
3. benchmark or validate it
4. update docs and roadmap state

## Security

Do not commit secrets, tokens, or private runtime artifacts. Use the process in [`SECURITY.md`](/home/redafrix/tests/dude/SECURITY.md) for vulnerabilities.
