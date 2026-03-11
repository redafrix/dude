# Remote Voice Notes

The remote API now supports voice-note task submission.

## Current Design

- Endpoint:
  - `POST /voice/task?backend=auto&auto_approve=true`
- Reply audio:
  - task responses can optionally request synthesized audio reply
  - latest reply audio is exposed at `GET /reply/latest-audio`
- Input:
  - raw uploaded audio bytes
  - currently accepts content types that `ffmpeg` can convert, including `audio/wav` and `audio/webm`
- Processing:
  - upload is normalized to mono WAV with `ffmpeg`
  - local ASR transcribes the audio
  - transcript normalization is applied
  - the normalized text is routed through the same orchestrator as text requests
- Client:
  - the remote web app can record a voice note with `MediaRecorder`
  - the response is returned as JSON with transcript, ASR device, task result, and optional reply-audio metadata

## Why This Shape

- It directly advances the charter requirement for remote voice messages from Android.
- It reuses the same local ASR and task router rather than inventing a second reasoning path.
- It stays compatible with the existing approval/audit model.

## Current Limits

- This is asynchronous voice-note submission, not real-time call mode.
- Returned output can now include a synthesized voice reply, but not a live duplex conversation.
- ASR still falls back to CPU on this machine until the CUDA runtime issue is fixed.
