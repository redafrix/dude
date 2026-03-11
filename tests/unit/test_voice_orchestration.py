from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import numpy as np

from dude.audio import CaptureAudioOutput, ReplayAudioInput
from dude.backends.tts import SpeechResult
from dude.config import load_config
from dude.events import AssistantState, AssistantStatus
from dude.pipeline import VoicePipeline


class _FakeAsr:
    def __init__(self, transcripts: list[str]) -> None:
        self._transcripts = iter(transcripts)
        self.device_in_use = "cpu"
        self.compute_type_in_use = "int8"

    def warmup(self) -> None:
        return None

    def transcribe(self, samples: np.ndarray, sample_rate_hz: int):
        del samples, sample_rate_hz
        return SimpleNamespace(text=next(self._transcripts), language="en")


class _FakeTts:
    def synthesize(self, text: str) -> SpeechResult:
        del text
        return SpeechResult(np.ones(8000, dtype=np.float32) * 0.1, 16000, "fake")


def test_voice_pipeline_uses_command_handler_for_non_builtin_command() -> None:
    config = load_config("configs/default.yaml")
    status = AssistantStatus(state=AssistantState.ARMED, armed=True)

    async def handler(command: str) -> str:
        return f"handled: {command}"

    pipeline = VoicePipeline(
        config,
        logging.getLogger("test"),
        status,
        audio_input=ReplayAudioInput(config.audio, np.zeros(0, dtype=np.float32)),
        audio_output=CaptureAudioOutput(config.audio),
        asr=_FakeAsr(["Dude, download discord for me"]),
        tts=_FakeTts(),
        command_handler=handler,
    )

    result = asyncio.run(
        pipeline._process_utterance(
            np.ones(config.audio.block_samples, dtype=np.float32) * 0.1,
            "transcript_gate",
            0.0,
            "transcript",
        )
    )

    assert result.command_text == "download discord for me"
    assert result.response_text == "handled: download discord for me"


def test_voice_pipeline_uses_persona_for_builtin_greeting() -> None:
    config = load_config("configs/default.yaml")
    config.persona.mode = "narcissistic"
    status = AssistantStatus(state=AssistantState.ARMED, armed=True)

    pipeline = VoicePipeline(
        config,
        logging.getLogger("test"),
        status,
        audio_input=ReplayAudioInput(config.audio, np.zeros(0, dtype=np.float32)),
        audio_output=CaptureAudioOutput(config.audio),
        asr=_FakeAsr(["Dude, hello"]),
        tts=_FakeTts(),
    )

    result = asyncio.run(
        pipeline._process_utterance(
            np.ones(config.audio.block_samples, dtype=np.float32) * 0.1,
            "transcript_gate",
            0.0,
            "transcript",
        )
    )

    assert result.response_text == "Dude is online. What masterpiece are we handling?"
