# Benchmarks

Milestone 1 writes runtime benchmark outputs to `benchmarks/results/`.

Current commands:

```bash
dude benchmark
dude eval-fixtures --manifest fixtures/manifests/m1-template.yaml
dude eval-pipeline --manifest fixtures/manifests/m1-template.yaml
```

What exists now:

- `benchmark`: ASR warmup/load timing, Kokoro cold/warm TTS timing, and a resource snapshot
- `eval-fixtures`: fixture-driven ASR transcript checks plus wake-result accounting
- `eval-pipeline`: replay a fixture manifest through the real wake/VAD/ASR/TTS pipeline and collect per-case runtime results
- service smoke benchmark: still available through the running service control path
- benchmark output now records the ASR device actually used, which matters on this machine because `auto` currently falls back from CUDA to CPU during transcription

Gaps still open:

- no committed real-user fixture corpus yet
- no measured live-mic end-to-end latency report yet
- no automated barge-in latency score yet
