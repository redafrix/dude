# Dude

`Dude` is a local-first Linux personal assistant project focused on fast voice interaction, explicit permissions, and measurable quality.

This repository currently implements the voice foundation plus the first orchestration foundation: GNOME/X11 activation, a background voice runtime, Unix-socket control, local ASR/TTS, replayable eval tooling, and a task router with backend bridges and SQLite audit logging.

## Status

- Milestones in repo: `M1.1 Voice Quality Gate` + `M2 Orchestration Foundation`
- Runtime model: Python `asyncio` service managed by `systemd --user`
- Control plane: local Unix domain socket and CLI
- Voice stack:
  - VAD: Silero when installed, energy fallback otherwise
  - Wake: transcript-gated by default, `openWakeWord` optional
  - ASR: `faster-whisper`
  - Transcript repair: deterministic normalization for coding/math/shell-style phrases
  - TTS: `kokoro-onnx`, with tone fallback
- Tooling:
  - structured JSON logs
  - backend benchmark command
  - fixture recording command
  - component fixture evaluation command
  - end-to-end pipeline replay evaluation command
- task routing command
- audit log query command
- memory note/list/delete command
- authenticated local HTTP API for remote transport bootstrap
- remote voice-note task submission through the local HTTP API
- synthesized remote voice replies through the same local TTS stack
- Telegram text and voice-note transport on top of the same orchestration core
- Telegram artifact replies for screenshots and browser captures

## Quick Start

```bash
uv venv
uv sync --extra dev --extra tts
source .venv/bin/activate
dude --config configs/default.yaml serve --warmup
```

In another terminal:

```bash
dude --config configs/default.yaml arm
dude --config configs/default.yaml status
```

The default runtime config is [`configs/default.yaml`](/home/redafrix/tests/dude/configs/default.yaml). GNOME hotkey installation is automated by [`tools/install_gnome_hotkey.sh`](/home/redafrix/tests/dude/tools/install_gnome_hotkey.sh).

Optional speech extras:

```bash
uv sync --extra dev --extra tts --extra wake --extra vad
```

Optional browser automation extra:

```bash
uv sync --extra dev --extra tts --extra wake --extra vad --extra browser
```

Optional CUDA ASR runtime extra:

```bash
uv sync --extra dev --extra tts --extra cuda_asr
```

Notes:

- The default config uses transcript wake handling: `wake_word.backend: transcript`.
- Transcript normalization is enabled by default and is applied after ASR in the live runtime and eval paths.
- Task routing uses deterministic local tools first, Codex as the execution backend, and Gemini as a planning-oriented secondary backend.
- Browser automation prefers Playwright when installed, and falls back to Chrome headless CLI when it is not.
- Non-safe requests return `approval_required` unless explicitly auto-approved.
- `--extra wake` installs `openWakeWord`.
- `--extra vad` installs `silero-vad`.
- `--extra browser` installs Playwright for richer browser control.
- `--extra cuda_asr` installs the CUDA 12 runtime wheels needed by `faster-whisper` on this machine.
- The runtime still works without either extra by falling back to energy VAD and transcript-gated wake handling.
- `openWakeWord` currently requires an explicit `wake_word.model_path`; the package wheel on this machine did not ship a ready-to-use default keyword model.

## Local Control And Evaluation

Service control:

```bash
dude --config configs/default.yaml serve --warmup
dude --config configs/default.yaml arm
dude --config configs/default.yaml disarm
dude --config configs/default.yaml status
dude --config configs/default.yaml shutdown
```

Backend benchmark:

```bash
dude --config configs/default.yaml benchmark
```

Fixture workflow:

```bash
dude --config configs/default.yaml record-fixture --seconds 4 --output fixtures/generated/wake-hello.wav
dude --config configs/default.yaml record-wake-enrollment --output-dir fixtures/enrollment/reda
dude --config configs/default.yaml record-corpus --output-dir fixtures/generated/m1-core --profile m1-core
dude --config configs/default.yaml eval-fixtures --manifest fixtures/manifests/m1-template.yaml
dude --config configs/default.yaml eval-pipeline --manifest fixtures/manifests/m1-template.yaml
```

The manifest template lives at [`fixtures/manifests/m1-template.yaml`](/home/redafrix/tests/dude/fixtures/manifests/m1-template.yaml).

Task workflow:

```bash
dude --config configs/default.yaml task --text "what is the current directory"
dude --config configs/default.yaml task --text "download discord for me"
dude --config configs/default.yaml task --text "say hello" --backend codex --auto-approve
dude --config configs/default.yaml task --text "open browser https://example.com" --auto-approve
dude --config configs/default.yaml task --text "show me what you're doing"
dude --config configs/default.yaml task --text "open downloads"
dude --config configs/default.yaml audit --limit 10
dude --config configs/default.yaml memory --list --limit 10
dude --config configs/default.yaml memory --note "Prefer visible browser mode."
```

Direct browser workflow:

```bash
dude --config configs/default.yaml browser --url https://example.com
dude --config configs/default.yaml browser --state
```

Desktop capture workflow:

```bash
dude --config configs/default.yaml screen --screenshot
dude --config configs/default.yaml screen --record --seconds 2
dude --config configs/default.yaml screen --state
```

Remote API workflow:

```bash
dude --config configs/default.yaml remote-token
dude --config configs/default.yaml remote-serve
dude --config configs/default.yaml tailscale-serve
```

Then open `http://127.0.0.1:8765/` on the local machine or through a private tunnel such as Tailscale, paste the bearer token once, and use the remote web app.

If Tailscale is installed and logged in, `dude tailscale-serve` configures a tailnet HTTPS entrypoint to the same remote API so the PWA can be opened from your phone without exposing the service publicly.

Remote voice-note task flow is also available through the web app and the `POST /voice/task` endpoint.

Telegram workflow:

```bash
export DUDE_TELEGRAM_BOT_TOKEN=...
dude --config configs/default.yaml telegram-serve
```

Telegram uses the same task router, approvals, memory store, and reply-audio path as the CLI and HTTP API. Restrict allowed chat ids in [`configs/default.yaml`](/home/redafrix/tests/dude/configs/default.yaml) before exposing it.

## Current Scope

- `Alt+A` activation via GNOME custom shortcut
- Armed listening and wake handling for `Dude`
- Deterministic response flow for `Dude, hello`
- Structured benchmark and event logging
- Offline fixture evaluation for wake/transcript checks
- Replayable end-to-end pipeline evaluation through the real runtime path
- wake enrollment recording workflow for personalized wake-word datasets
- SQLite-backed task audit log
- Approval-classified task routing for text requests
- deterministic local launch bootstrap for terminal, files, downloads, browser, and Discord
- deterministic local file read/list/create/mkdir/copy/move/delete/find/search routing with explicit approvals
- Codex execution bridge and Gemini planning bridge
- backend prompts enriched with local memory plus current browser/screen context
- headless browser capture with screenshot artifacts
- browser search, page summaries, link extraction, and basic click/type automation
- persisted browser state for later visibility flows
- authenticated localhost HTTP gateway for future remote clients
- X11 desktop screenshot and clip capture with remote artifact access
- live remote desktop snapshots over the authenticated HTTP transport
- remote voice-note upload and local ASR task routing
- remote reply-audio generation and playback artifacts
- local memory summaries plus operator notes in the SQLite store
- Telegram text and voice-note transport with optional voice replies
- Tailscale Serve helper for tailnet-only remote access
- configurable persona layer for built-in spoken/system phrasing
- desktop approval prompt hook for approval-required voice tasks

## Current Measured Baseline

Latest backend benchmark on this machine:

- ASR model warmup/load: about `2617 ms`
- ASR fixture transcription: about `1572 ms`
- ASR active device during actual transcription: `cpu` (`int8` fallback)
- Latest CUDA-backed ASR verification after installing runtime wheels:
  - ASR model warmup/load: about `997 ms`
  - ASR fixture transcription: about `220 ms`
  - ASR active device: `cuda` (`float16`)
- Kokoro TTS cold synthesis: about `1130 ms`
- Kokoro TTS warm synthesis: about `411 ms`
- Observed snapshot during backend benchmark:
  - RAM used: about `8077 MB`
  - VRAM used: about `119 MB`

These numbers are from [`docs/benchmarks/m1-baseline.md`](/home/redafrix/tests/dude/docs/benchmarks/m1-baseline.md). The current repo can now run `faster-whisper` on CUDA on this machine when the `cuda_asr` extra is installed.

Project-wide status against the original charter is tracked in [`docs/roadmap/charter-checklist.md`](/home/redafrix/tests/dude/docs/roadmap/charter-checklist.md).

## Next Milestone Work

- fixture corpus collection
- dedicated wake-word model validation
- real user enrollment recordings through the new wake-enrollment workflow
- live and replayed wake-to-first-audio timing comparison
- real recorded coding/math/command transcript benchmarks
- deeper browser and desktop automation
- richer deterministic local tool routing and launch coverage
- Android / Tailscale-facing remote clients on top of the HTTP task API
- voice-side approval UX over the orchestration core
- richer mobile UX, voice notes, and live screen/call mode
