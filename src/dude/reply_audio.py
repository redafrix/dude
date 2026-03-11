from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import soundfile as sf

from dude.backends.tts import SpeechSynthesizer
from dude.config import DudeConfig


@dataclass(slots=True)
class ReplyAudioState:
    updated_at: str
    text: str
    artifact_path: str
    sample_rate_hz: int
    backend: str

    def to_dict(self) -> dict[str, object]:
        return {
            "updated_at": self.updated_at,
            "text": self.text,
            "artifact_path": self.artifact_path,
            "sample_rate_hz": self.sample_rate_hz,
            "backend": self.backend,
        }


class ReplyAudioController:
    def __init__(self, config: DudeConfig, logger) -> None:
        self.config = config
        self.logger = logger
        self.synthesizer = SpeechSynthesizer(config.tts, logger)
        self.artifact_dir = config.runtime.state_dir / "remote-replies"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.artifact_dir / "last-reply-state.json"

    def synthesize_reply(self, text: str) -> dict[str, object]:
        if not text.strip():
            raise ValueError("Reply text is empty.")
        speech = self.synthesizer.synthesize(text)
        output_path = self.artifact_dir / "last-reply.wav"
        sf.write(output_path, speech.samples, speech.sample_rate_hz)
        state = ReplyAudioState(
            updated_at=datetime.now(timezone.utc).isoformat(),
            text=text,
            artifact_path=str(output_path),
            sample_rate_hz=speech.sample_rate_hz,
            backend=speech.backend,
        )
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        return state.to_dict()

    def get_state(self) -> dict[str, object] | None:
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))
