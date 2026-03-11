import logging
from types import SimpleNamespace

import numpy as np
import pytest

from dude.backends.asr import FasterWhisperBackend
from dude.config import AsrConfig


class _FakeModel:
    def __init__(self, *, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error

    def transcribe(self, samples: np.ndarray, **_: object):
        if self._error is not None:
            raise self._error
        return [SimpleNamespace(text=self._text or "")], SimpleNamespace(language="en")


def test_faster_whisper_auto_falls_back_to_cpu_on_transcribe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FasterWhisperBackend(AsrConfig(device="auto"), logging.getLogger("test"))
    models = {
        "cuda": _FakeModel(error=RuntimeError("libcublas.so.12 is not found")),
        "cpu": _FakeModel(text="Dude hello"),
    }

    monkeypatch.setattr(
        backend,
        "_create_model",
        lambda device, compute_type: models[device],
    )
    monkeypatch.setattr(backend, "_resolve_device", lambda: ("cuda", "float16"))

    transcript = backend.transcribe(np.zeros(16000, dtype=np.float32), 16000)

    assert transcript.text == "Dude hello"
    assert backend._device_in_use == "cpu"


def test_faster_whisper_explicit_cuda_does_not_silently_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FasterWhisperBackend(AsrConfig(device="cuda"), logging.getLogger("test"))
    model = _FakeModel(error=RuntimeError("libcublas.so.12 is not found"))

    monkeypatch.setattr(backend, "_create_model", lambda device, compute_type: model)
    monkeypatch.setattr(backend, "_resolve_device", lambda: ("cuda", "float16"))

    with pytest.raises(RuntimeError, match="libcublas"):
        backend.transcribe(np.zeros(16000, dtype=np.float32), 16000)
