# Screen Capture

The desktop capture subsystem provides the first real whole-screen visibility path for the local X11 session.

## Current Design

- Capture backend:
  - `ffmpeg` with `x11grab`
  - current machine assumptions: X11 session and a working `DISPLAY`
- Supported actions:
  - single screenshot capture
  - short clip recording
  - last-capture state reporting
- Artifact storage:
  - defaults to `runtime/screen/`
  - last state is stored in `runtime/screen/last-screen-state.json`
- API surface:
  - CLI `dude screen --screenshot`
  - CLI `dude screen --record --seconds 2`
  - CLI `dude screen --state`
  - orchestrator routes screen tasks as local tools
  - remote API exposes `/screen/state` and `/screen/latest-artifact`

## Why This Shape

- It directly addresses the charter requirement to inspect what is happening on the PC.
- It works on the current X11 desktop without adding a large new dependency tree.
- It gives the remote web app a real desktop artifact path, not only browser screenshots.

## Current Limits

- This is capture, not live screen streaming.
- It depends on X11; Wayland would need a different path.
- The current remote web app can fetch image artifacts directly and expose clip metadata, but live clip playback UX is still basic.
