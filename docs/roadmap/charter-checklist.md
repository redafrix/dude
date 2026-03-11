# Charter Checklist

This file tracks the original project brief in [`prompt_what_i_want.md`](/home/redafrix/tests/dude/prompt_what_i_want.md) against the current repo state.

## Completed Or Strongly Implemented

- Desktop runtime bootstrap:
  - background service
  - Unix-socket control plane
  - GNOME hotkey installer
- Voice pipeline foundation:
  - local audio capture/playback
  - VAD
  - ASR
  - TTS
  - interruption/barge-in handling
  - CUDA-backed `faster-whisper` now works on this machine when the CUDA runtime extra is installed
- Voice evaluation foundation:
  - fixture recording
  - guided corpus recording workflow
  - component eval runner
  - end-to-end pipeline replay eval
  - speaker profile build and speaker-match eval flow
- Transcript intelligence foundation:
  - deterministic normalization for coding/math/shell-style phrases
- Orchestration foundation:
  - deterministic local tools first
  - Codex backend
  - Gemini backend
  - SQLite audit log
  - local memory summaries injected into backend prompts
  - current browser/screen context injected into backend prompts
  - approval classes
  - resumable approval flow
  - desktop approval prompt hook for voice-driven approval-required tasks
- Deterministic local desktop actions:
  - screenshot and clip capture
  - browser launch/state capture
  - app/file/download launch bootstrap
  - file read/list/create/mkdir/copy/move/delete/find/search routing
- Browser/bootstrap visibility:
  - headless browser capture
  - screenshot artifacts
  - last-browser-state reporting
  - visible-browser fallback
- Desktop visibility bootstrap:
  - X11 screenshot capture
  - short screen clip capture
  - remote screen artifact endpoint
  - live remote screenshot refresh endpoint
- Remote transport foundation:
  - authenticated local HTTP API
  - `/task`, `/approve`, `/audit`, `/browser/state`
  - phone-friendly web app/PWA bootstrap
  - remote voice-note task submission
  - synthesized remote voice replies
  - Tailscale Serve helper for private phone access
- Memory foundation:
  - SQLite-backed task summaries
  - user memory notes
  - CLI and HTTP memory list/create/delete/clear flows
- Persona foundation:
  - configurable neutral/witty/narcissistic modes
  - built-in spoken responses routed through a dedicated persona layer
- Telegram transport foundation:
  - text task handling
  - voice-note task handling
  - optional voice replies
  - screenshot/browser artifact replies
  - allowed-chat authorization
- Public repo foundation:
  - public GitHub repo created
  - root contribution, security, and changelog docs
  - CI workflow scaffold

## Partial

- Wake-word quality:
  - transcript-gated wake works
  - dedicated `openWakeWord` path exists in config/eval
  - enrollment recording workflow now exists
  - speaker profile building from enrollment now exists
  - real wake-word benchmarking corpus is still missing
- Speaker verification:
  - optional local speaker profile build now exists
  - optional runtime "my voice only" enforcement now exists
  - threshold tuning against real positive/negative recordings is still missing
- STT quality:
  - baseline works
  - deterministic normalization exists
  - context-aware correction and real coding/math fixture scoring are still incomplete
- TTS quality:
  - Kokoro path works
  - real comparative TTS quality/latency selection is not finished
- Browser automation:
  - bootstrap flows work
  - search, summarize, link extraction, and basic click/type actions now work
  - deeper scripted browsing and richer DOM/UI automation are still thin
- General capability surface:
  - shell-style safe queries work
  - browser and screen visibility bootstrap works
  - application and file-action coverage is still partial and curated, not broad
- Remote access:
  - text-first remote API and PWA exist
  - voice-note upload now exists
  - voice replies now exist
  - Telegram text/voice-note transport now exists
  - Tailscale private remote access helper now exists
  - real call mode is not implemented yet
- Personality and behavior:
  - configurable style layer now exists
  - richer long-form personality and adaptive humor are still not implemented
- Screen visibility:
  - screenshot and short clip artifacts exist
  - live snapshot refresh now exists
  - true low-latency continuous screen sharing is still not implemented
- Vision:
  - screenshot artifact flow exists
  - richer image reasoning attachment is not finished
- Approval UX:
  - CLI, voice resume, and desktop approval prompting exist
  - sudo handoff and richer approval policies are not finished

## Not Done Yet

- Personalized wake-word training from enrollment data
- Real recorded wake false-accept / false-reject benchmark corpus
- Android APK
- WebRTC live conversation / live screen share
- richer screen recording / clip delivery UX
- Full local multimodal reasoning path
- Sudo prompt handoff window flow

## Current Next Priorities

- real voice corpus collection and wake/STT benchmarking
- deeper remote web app refinement on top of the new HTTP task API
- deeper browser automation and screenshot-driven reasoning
- memory-aware summaries and preference use inside orchestration
