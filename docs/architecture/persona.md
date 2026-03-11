# Persona

The persona layer controls built-in spoken phrasing without mixing style logic into the core task and tool logic.

## Current Design

- Config section:
  - `persona.mode`
  - `persona.operator_name`
- Supported modes:
  - `neutral`
  - `witty`
  - `narcissistic`
- Current scope:
  - greeting replies
  - stop/status replies
  - approval-required phrasing
  - generic failure/fallback phrasing

## Why This Shape

- It keeps personality adjustable without corrupting deterministic tool output.
- It creates a stable layer where later prompt/persona work can plug in.
- It keeps style changes local to one subsystem instead of scattering strings through the runtime.

## Current Limits

- It does not yet rewrite Codex or Gemini free-form outputs.
- It does not yet model long-running conversational tone, memory-driven affect, or adaptive humor.
- Voice prosody and persona are still separate; the TTS layer does not yet vary delivery by persona mode.
