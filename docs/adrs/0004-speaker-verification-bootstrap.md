# ADR 0004: Speaker Verification Bootstrap

## Status

Accepted

## Context

The charter requires a future "my voice only" mode and a path from repeated wake-word enrollment to
voice-specific acceptance.

The repo already had:

- wake enrollment recording
- live voice pipeline replay/eval
- optional local wake-word backend

What was missing was the bridge from enrollment data to an actual runtime speaker gate.

## Decision

Add an optional speaker-verification subsystem using SpeechBrain ECAPA embeddings.

- Capture enrollment with the existing wake enrollment workflow.
- Build a reusable JSON speaker profile from enrollment takes.
- Verify runtime utterances against the stored profile.
- Support two modes:
  - `advisory`
  - `enforce`

## Consequences

Positive:

- Adds a practical local-first "my voice only" path without depending on remote APIs.
- Reuses the current repo structure, config model, CLI, and eval harness patterns.
- Makes future threshold tuning and false-accept/false-reject measurement possible.

Tradeoffs:

- Adds another optional heavy dependency.
- Quality depends on real positive/negative recordings and threshold tuning.
- This does not replace personalized wake-word model training.
