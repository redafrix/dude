# Voice Stack Research Notes

Current stack selected for implementation and benchmarking:

- VAD: `silero-vad` when installed, otherwise energy-VAD fallback
- Wake detection:
  - default: transcript-first gate for immediate practicality
  - optional: `openWakeWord` streaming backend
- ASR: `faster-whisper`
- TTS: `kokoro-onnx` first, deterministic tone fallback if unavailable

Why this stack shipped first:

- `faster-whisper` is the most practical path to working local ASR on this machine with a mature Python integration story.
- Kokoro gives a much better quality/latency baseline than a robotic placeholder TTS, while still running locally.
- Transcript-gated wake handling made it possible to ship the first usable loop without blocking on custom wake-model packaging.
- A deterministic post-ASR normalization layer is now the default first pass for coding/math/shell cleanup before any heavier correction strategy is considered.

Compared options under active evaluation:

- Wake:
  - `openWakeWord`: promising streaming interface and custom model path support
  - transcript gate: worse in principle for latency, but zero model packaging friction
  - `Precise`/OpenVoiceOS family: not yet integrated in this repo
- ASR:
  - `faster-whisper` is the current baseline
  - larger Whisper variants and NVIDIA Parakeet are still benchmark candidates
- TTS:
  - Kokoro is the current quality-first default
  - Piper-family remains the low-latency fallback candidate
  - XTTS-v2 is deferred because latency/footprint cost is higher

Observed implementation constraint:

- On this machine, the `openWakeWord` wheel did not expose a ready-to-use bundled default model file.
- The repo therefore treats `openWakeWord` as opt-in and requires `wake_word.model_path` to be set explicitly instead of pretending the backend is plug-and-play.
- On this machine, `faster-whisper` can initialize under `auto`, but actual transcription currently falls back to CPU because the required CUDA runtime library for CTranslate2 is not available at inference time.

Next research step:

- benchmark real wake models and fixture corpora on this laptop before replacing transcript-gated wake as the default.
