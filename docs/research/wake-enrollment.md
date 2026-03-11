# Wake Enrollment Workflow

The repo now includes a first-pass wake enrollment recorder for collecting repeated user utterances of the wake phrase.

## Command

```bash
dude --config configs/default.yaml record-wake-enrollment \
  --output-dir fixtures/enrollment/reda \
  --phrase dude \
  --count 12 \
  --seconds 1.8
```

## Output

- one WAV file per take:
  - `wake-001.wav`
  - `wake-002.wav`
  - ...
- a manifest at `manifest.yaml` containing:
  - phrase
  - creation time
  - sample rate
  - take list

## Why This Exists

- It creates a repeatable path for personalized wake-word collection.
- It gives future `openWakeWord` or speaker-verification work a clean input set.
- It makes wake benchmarking less ad hoc once real user data is available.

## Current Limit

- This is a data-collection workflow, not wake-model training yet.
- The repo still needs real recordings from the target user and a measured personalization loop.
