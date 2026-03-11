from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np

from dude.config import TtsConfig

KOKORO_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
KOKORO_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)


@dataclass(slots=True)
class SpeechResult:
    samples: np.ndarray
    sample_rate_hz: int
    backend: str


class ToneSynthesizer:
    def __init__(self, sample_rate_hz: int) -> None:
        self.sample_rate_hz = sample_rate_hz

    def synthesize(self, text: str) -> SpeechResult:
        duration = max(0.45, min(1.1, len(text) / 28))
        t = np.linspace(0, duration, int(self.sample_rate_hz * duration), endpoint=False)
        carrier = np.sin(2 * np.pi * 220 * t)
        envelope = np.minimum(1.0, np.linspace(0, 2.0, len(t))) * np.linspace(1.0, 0.0, len(t))
        samples = 0.15 * carrier * envelope
        return SpeechResult(
            samples=samples.astype(np.float32),
            sample_rate_hz=self.sample_rate_hz,
            backend="tone",
        )


class KokoroSynthesizer:
    def __init__(self, config: TtsConfig) -> None:
        self.config = config
        self._pipeline = None

    def _resolve_asset_path(self, explicit: Path | None, filename: str) -> Path:
        if explicit is not None:
            return explicit
        return Path.home() / ".cache" / "dude" / "models" / "kokoro" / filename

    def _ensure_asset(self, path: Path, url: str) -> Path:
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(url, path)
        return path

    def _load_pipeline(self):  # type: ignore[no-untyped-def]
        if self._pipeline is not None:
            return self._pipeline
        import kokoro_onnx

        model_path = self._ensure_asset(
            self._resolve_asset_path(self.config.kokoro_model_path, "kokoro-v1.0.onnx"),
            KOKORO_MODEL_URL,
        )
        voices_path = self._ensure_asset(
            self._resolve_asset_path(self.config.kokoro_voice_path, "voices-v1.0.bin"),
            KOKORO_VOICES_URL,
        )

        if hasattr(kokoro_onnx, "Kokoro"):
            self._pipeline = kokoro_onnx.Kokoro(
                model_path=str(model_path),
                voices_path=str(voices_path),
            )
        elif hasattr(kokoro_onnx, "TTS"):
            self._pipeline = kokoro_onnx.TTS(
                model_path=str(model_path),
                voices_path=str(voices_path),
            )
        else:
            raise RuntimeError("Unsupported kokoro_onnx API shape.")
        return self._pipeline

    def synthesize(self, text: str) -> SpeechResult:
        pipeline = self._load_pipeline()
        if hasattr(pipeline, "create"):
            audio, sample_rate = pipeline.create(
                text,
                voice=self.config.voice,
                speed=self.config.speed,
            )
        elif hasattr(pipeline, "generate"):
            audio, sample_rate = pipeline.generate(
                text,
                voice=self.config.voice,
                speed=self.config.speed,
            )
        else:
            raise RuntimeError("Unsupported Kokoro generation API.")
        return SpeechResult(np.asarray(audio, dtype=np.float32), int(sample_rate), "kokoro")


class SpeechSynthesizer:
    def __init__(self, config: TtsConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._tone = ToneSynthesizer(sample_rate_hz=config.sample_rate_hz)
        self._kokoro = KokoroSynthesizer(config)

    def synthesize(self, text: str) -> SpeechResult:
        if self.config.provider == "tone":
            return self._tone.synthesize(text)
        try:
            return self._kokoro.synthesize(text)
        except Exception as exc:
            if not self.config.fallback_to_tone:
                raise
            self.logger.warning(
                "tts_fallback",
                extra={"event_data": {"error": str(exc), "fallback": "tone"}},
            )
            return self._tone.synthesize(text)
