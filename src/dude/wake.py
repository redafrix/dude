from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from dude.config import WakeWordConfig


@dataclass(slots=True)
class WakeDecision:
    triggered: bool
    remainder: str
    backend: str


@dataclass(slots=True)
class StreamingWakeEvent:
    triggered: bool
    score: float
    backend: str
    label: str


class StreamingWakeDetector(Protocol):
    def process_chunk(self, samples: np.ndarray) -> StreamingWakeEvent:
        ...

    def reset(self) -> None:
        ...


class PhraseWakeDetector:
    def __init__(self, phrase: str):
        self.phrase = phrase.lower().strip()

    def detect(self, transcript: str) -> WakeDecision:
        normalized = transcript.strip().lower()
        if not normalized:
            return WakeDecision(triggered=False, remainder="", backend="transcript")
        if normalized == self.phrase:
            return WakeDecision(triggered=True, remainder="", backend="transcript")
        prefix = f"{self.phrase} "
        alt_prefix = f"{self.phrase}, "
        if normalized.startswith(prefix):
            return WakeDecision(
                triggered=True,
                remainder=normalized[len(prefix):].strip(),
                backend="transcript",
            )
        if normalized.startswith(alt_prefix):
            return WakeDecision(
                triggered=True,
                remainder=normalized[len(alt_prefix):].strip(),
                backend="transcript",
            )
        return WakeDecision(triggered=False, remainder="", backend="transcript")


class OpenWakeWordDetector:
    def __init__(self, config: WakeWordConfig):
        if config.model_path is None:
            raise ValueError("openWakeWord backend requires `wake_word.model_path`.")

        from openwakeword.model import Model

        self.model_path = Path(config.model_path)
        self.threshold = config.threshold
        self.label = self.model_path.stem
        inference_framework = "onnx" if self.model_path.suffix == ".onnx" else "tflite"
        self.model = Model(
            wakeword_models=[str(self.model_path)],
            inference_framework=inference_framework,
        )

    def process_chunk(self, samples: np.ndarray) -> StreamingWakeEvent:
        pcm16 = np.clip(samples, -1.0, 1.0)
        pcm16 = (pcm16 * 32767).astype(np.int16)
        scores = self.model.predict(pcm16)
        score = float(scores.get(self.label, 0.0))
        return StreamingWakeEvent(
            triggered=score >= self.threshold,
            score=score,
            backend="openwakeword",
            label=self.label,
        )

    def reset(self) -> None:
        self.model.reset()


def build_stream_wake_detector(
    config: WakeWordConfig,
    logger: logging.Logger,
) -> StreamingWakeDetector | None:
    if config.backend == "transcript":
        return None
    if config.backend == "openwakeword":
        detector = OpenWakeWordDetector(config)
        logger.info(
            "wake_backend_ready",
            extra={
                "event_data": {
                    "backend": "openwakeword",
                    "model_path": str(config.model_path),
                    "threshold": config.threshold,
                }
            },
        )
        return detector
    raise ValueError(f"Unsupported wake backend: {config.backend}")
