from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic


class AssistantState(str, Enum):
    IDLE = "idle"
    ARMED = "armed"
    WAKE_DETECTED = "wake_detected"
    RECORDING_REQUEST = "recording_request"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass(slots=True)
class AssistantStatus:
    state: AssistantState = AssistantState.IDLE
    armed: bool = False
    speaking: bool = False
    last_transcript: str = ""
    last_response: str = ""
    updated_at: float = field(default_factory=monotonic)

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "armed": self.armed,
            "speaking": self.speaking,
            "last_transcript": self.last_transcript,
            "last_response": self.last_response,
            "updated_at_monotonic": round(self.updated_at, 6),
        }
