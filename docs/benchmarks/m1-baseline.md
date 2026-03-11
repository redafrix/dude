# M1 Baseline

Original backend benchmark run on this machine from:

```bash
uv run dude --config configs/default.yaml benchmark --fixture fixtures/generated/silence-smoke.wav
```

Observed results:

- ASR warmup/load: `2617.12 ms`
- ASR fixture transcription: `1571.53 ms`
- ASR device in use: `cpu`
- ASR compute type in use: `int8`
- TTS backend: `kokoro`
- TTS cold synthesis: `1129.86 ms`
- TTS warm synthesis: `411.49 ms`
- TTS output sample rate: `24000 Hz`

Resource snapshot during the benchmark:

- CPU usage: `28.1%`
- RAM used: `8076.5 MB`
- RAM available: `23636.95 MB`
- GPU usage: `0.0%`
- VRAM used: `119.0 MB`
- VRAM total: `8188.0 MB`

Interpretation:

- Warm Kokoro synthesis is already within the project's first-audio target range for a short deterministic reply.
- ASR warmup cost is still noticeable and should be treated as a cold-start tax, not acceptable interactive latency.
- `faster-whisper` is not really using the RTX 4060 for transcription yet. The runtime now falls back cleanly to CPU instead of crashing, but CUDA-backed ASR is still an open environment task.
- The current benchmark is backend-only. It does not yet prove end-to-end live microphone latency, wake accuracy, or barge-in timing.

## Updated CUDA Benchmark

After installing the CUDA runtime wheels required by `faster-whisper`:

```bash
uv sync --extra dev --extra tts --extra cuda_asr
uv run dude --config configs/default.yaml benchmark --fixture runtime/voice-smoke.wav
```

Observed results:

- ASR warmup/load: `996.99 ms`
- ASR fixture transcription: `220.46 ms`
- ASR device in use: `cuda`
- ASR compute type in use: `float16`
- TTS backend: `kokoro`
- TTS cold synthesis: `1275.94 ms`
- TTS warm synthesis: `453.37 ms`

Resource snapshot during the benchmark:

- CPU usage: `43.1%`
- RAM used: `7911.98 MB`
- GPU usage: `0.0%`
- VRAM used: `583.0 MB`
- VRAM total: `8188.0 MB`

Interpretation:

- The main ASR blocker on this machine is now resolved for the current repo setup.
- CUDA-backed transcription is materially faster than the earlier CPU fallback.
- The remaining milestone-1 gap is no longer basic ASR device bring-up; it is real wake/transcript evaluation on user-recorded fixtures.

Next benchmark additions:

- fixture-driven wake false accept / false reject measurement
- transcript accuracy checks for `Dude, hello` and `Dude, stop`
- coding/math phrase evaluation
- live-path end-to-end first-audio timing
