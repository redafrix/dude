# Speaker Verification

The voice stack now supports an optional local speaker-verification gate for a practical
"my voice only" mode.

## Current Design

- Enrollment capture:
  - `dude record-wake-enrollment --output-dir ...`
  - records repeated `Dude` takes and writes a manifest
- Profile build:
  - `dude build-speaker-profile --manifest ... --output ...`
  - converts enrollment takes into a reusable speaker profile
- Runtime enforcement:
  - enable `speaker.enabled: true`
  - point `speaker.profile_path` at the built profile
  - `speaker.mode: enforce` silently ignores non-matching voices after wake/transcript match
  - `speaker.mode: advisory` records the score but does not block the request
- Evaluation:
  - `dude eval-speaker --manifest ... --profile ...`
  - fixture manifests may include `expected_speaker_match`

## Implementation Notes

- Backend:
  - SpeechBrain ECAPA speaker embeddings via the optional `speaker` extra
- Profile format:
  - JSON profile with normalized exemplar embeddings and a centroid
- Decision rule:
  - cosine similarity against centroid and exemplar set
  - accept when the best score is at or above the configured threshold

## Why This Shape

- It keeps the default install light; speaker verification is opt-in.
- It reuses the existing local enrollment workflow instead of inventing a second capture path.
- It fits the current voice spine cleanly:
  - wake/transcript match
  - optional speaker check
  - response generation

## Current Limits

- This is speaker verification, not custom wake-word model training.
- Threshold tuning still needs real positive/negative recordings from the target user and at least one
  other speaker.
- The current backend runs on CPU and is optimized for correctness/integration first, not lowest
  possible latency.
