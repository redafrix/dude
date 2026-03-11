# ADR 0001: Milestone 1 Runtime

## Status

Accepted

## Decision

Milestone 1 uses a Python `asyncio` service with a local Unix control socket and a single-process voice pipeline.

## Why

- Fastest path to an integrated local voice loop on this machine
- Good Python ecosystem coverage for ASR, VAD, audio capture, and TTS
- Easy to benchmark and refactor later

## Consequences

- Hot-path latency may require later optimization or process splits
- GPU enablement depends on Python environment packaging
