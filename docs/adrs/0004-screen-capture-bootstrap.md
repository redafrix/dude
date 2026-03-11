# ADR 0004: Screen Capture Bootstrap

## Status

Accepted

## Decision

Add a local screen capture controller based on `ffmpeg` + `x11grab` that can:

- capture a screenshot of the current X11 desktop
- record a short desktop clip
- persist last-capture state
- expose artifacts through the orchestrator and remote API

## Why

- The original charter explicitly asked for a way to see what the PC is doing.
- The current machine is on X11 and already has `ffmpeg`, `xdpyinfo`, and a working `DISPLAY`, so this path is practical now.
- It provides immediate value before attempting live screen share or an Android-native client.

## Consequences

- Desktop visibility is now stronger than browser-only state reporting.
- The current implementation is specific to X11 and should be isolated behind the screen controller boundary.
- Live streaming remains future work.
