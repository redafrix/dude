# Fixtures

This directory holds recorded audio for repeatable evaluation.

Milestone M1.1 fixture sets:

- `wake-hello/`: `Dude, hello`
- `wake-stop/`: `Dude, stop`
- `idle-noise/`: desk-noise false-accept checks
- `barge-in/`: user speech during playback

Tracked assets in this repo are only manifests and notes. Generated WAV files should be written under `fixtures/generated/`, which is gitignored.

Recommended workflow:

```bash
dude --config configs/default.yaml record-fixture --seconds 4 --output fixtures/generated/wake-hello-01.wav
dude --config configs/default.yaml record-corpus --output-dir fixtures/generated/m1-core --profile m1-core
dude --config configs/default.yaml eval-fixtures --manifest fixtures/manifests/m1-template.yaml
dude --config configs/default.yaml eval-pipeline --manifest fixtures/manifests/m1-template.yaml
```

`record-corpus` is the preferred way to build the first real evaluation set because it writes a manifest with the expected wake/transcript metadata for the recorded scenarios.

Fixture paths in the manifest are resolved relative to the manifest file location, not the current shell directory.

Recommended manifest fields:

- `id`
- `path`
- `scenario`
- `expected_wake`
- `expected_transcript_contains`
- `expected_response_contains`

`expected_transcript_contains` is matched against the normalized transcript output, not the raw ASR string.

Start with 10 to 20 recordings per scenario before drawing conclusions about wake false rejects or transcript quality.
