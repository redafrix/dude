# Voice Spine

Milestone 1 uses a single Python service with a local Unix control socket.

Core process:

1. `dude serve` starts `DudeService`
2. `DudeService` starts:
   - `VoicePipeline`
   - `ControlPlane` on a Unix socket
3. CLI commands such as `arm`, `status`, and `shutdown` send JSON requests over the local socket
4. When armed, the pipeline continuously reads mono 16 kHz audio blocks
5. VAD decides whether speech is present
6. Wake handling runs in one of two modes:
   - transcript gate: ASR the captured utterance, then look for `Dude`
   - streaming wake: `openWakeWord` scores each chunk and starts capture immediately on trigger
7. ASR turns the utterance into text
8. A deterministic normalization layer repairs coding/math/shell-style transcript spans before command handling and evaluation checks
9. Local deterministic response logic answers milestone-1 commands
10. TTS renders the reply and playback remains interruptible through barge-in detection
11. The same pipeline can now be fed by either live microphone input or replayed fixture audio for reproducible evaluation

State flow:

1. `idle`
2. `armed`
3. `wake_detected`
4. `listening`
5. `thinking`
6. `speaking`

Capture modes inside the pipeline:

- `idle`: assistant not currently collecting a request
- `transcript_gate`: speech is being captured for transcript-based wake detection
- `wake_stream`: a streaming wake backend already fired, so the utterance is captured immediately
- `follow_up`: assistant is inside the short follow-up window after a spoken response

Current implementation notes:

- The default config uses transcript-gated wake handling because it works without any dedicated keyword model assets.
- `openWakeWord` is already integrated behind a backend interface, but it currently requires an explicit model path in config.
- Transcript normalization is applied after ASR and before command handling; wake detection still uses the raw ASR text.
- Control transport is intentionally local-only and low-latency; the older file-mailbox bootstrap path has been retired.
- The audio layer now supports both live mic input and replayed fixture input, plus a capture-only audio sink for evaluation runs.
- Benchmark/eval tooling lives outside the service hot path in [`src/dude/eval.py`](/home/redafrix/tests/dude/src/dude/eval.py).
