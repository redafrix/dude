# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and uses calendar-driven project milestones rather than strict semver at this stage.

## Unreleased

### Added
- local-first voice runtime with Unix-socket control, ASR, TTS, VAD, and replayable evaluation
- deterministic transcript normalization for coding, math, and shell-style phrases
- orchestration layer with approvals, SQLite audit logging, Codex/Gemini bridges, and deterministic local tools
- browser automation bootstrap with headless screenshots, visible mode, search, summaries, and link extraction
- desktop screenshot and clip capture with remote artifact access and live snapshot refresh
- authenticated HTTP remote API, PWA-style web UI, Telegram transport, and reply-audio artifacts
- local memory summaries and user note storage

### Changed
- CUDA-backed `faster-whisper` support is now wired into the project environment when the CUDA runtime extra is installed

### Documentation
- architecture notes, ADRs, benchmark notes, roadmap tracking, contribution guidance, and security reporting
