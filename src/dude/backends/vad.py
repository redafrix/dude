from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(slots=True)
class VadResult:
    is_speech: bool
    score: float
    backend: str


class VadBackend(Protocol):
    def detect(self, samples: np.ndarray) -> VadResult: ...


class EnergyVadBackend:
    def __init__(self, threshold: float = 0.015) -> None:
        self.threshold = threshold

    def detect(self, samples: np.ndarray) -> VadResult:
        if samples.size == 0:
            return VadResult(is_speech=False, score=0.0, backend="energy")
        rms = float(np.sqrt(np.mean(np.square(samples))))
        return VadResult(is_speech=rms >= self.threshold, score=rms, backend="energy")


class SileroVadBackend(EnergyVadBackend):
    def __init__(self, threshold: float) -> None:
        super().__init__(threshold=0.015)
        self.silero_threshold = threshold
        self._model = None
        self._torch = None
        try:
            import torch
            from silero_vad import load_silero_vad

            self._torch = torch
            self._model = load_silero_vad()
        except Exception:
            self._model = None

    def detect(self, samples: np.ndarray) -> VadResult:
        if self._model is None or self._torch is None:
            return super().detect(samples)
        tensor = self._torch.tensor(samples, dtype=self._torch.float32)
        try:
            score = float(self._model(tensor, 16000).item())
            return VadResult(score >= self.silero_threshold, score, "silero")
        except Exception:
            return super().detect(samples)

