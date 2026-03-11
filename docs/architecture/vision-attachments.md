# Vision Attachments

The Codex bridge can now attach current browser or desktop screenshots when the task is explicitly
about what is visible on screen.

## Current Design

- Vision-style prompts such as:
  - `what is on my screen`
  - `what is on the page`
  - `analyze the screenshot`
- Route to Codex with `route_reason: vision_request`.
- The orchestrator collects attachments from existing local state:
  - browser screenshot from the last browser action
  - desktop screenshot from the last screen capture
  - if needed, a fresh desktop screenshot can be captured locally before the backend call
- The Codex runner forwards those images with `codex exec -i ...`.

## Why This Exists

- The repo already had screenshot generation and remote visibility.
- The missing piece was letting the reasoning backend inspect those artifacts directly instead of
  only receiving text summaries.

## Current Limits

- This is currently implemented for the Codex backend path.
- It is screenshot-based, not a streaming multimodal runtime.
- It is not a full local multimodal model path.
