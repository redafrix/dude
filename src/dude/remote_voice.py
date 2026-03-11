from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import soundfile as sf

from dude.backends.asr import FasterWhisperBackend
from dude.config import DudeConfig
from dude.normalize import TranscriptNormalizer
from dude.orchestrator import BackendKind, Orchestrator, TaskRequest


class RemoteVoiceProcessor:
    def __init__(self, config: DudeConfig, logger, orchestrator: Orchestrator) -> None:
        self.config = config
        self.logger = logger
        self.orchestrator = orchestrator
        self.asr = FasterWhisperBackend(config.asr, logger)
        self.normalizer = TranscriptNormalizer(config.normalization)
        self._warmed = False

    def process_audio_task(
        self,
        audio_bytes: bytes,
        *,
        content_type: str,
        backend: BackendKind,
        auto_approve: bool,
    ) -> dict[str, Any]:
        if not audio_bytes:
            raise ValueError("Audio body is empty.")
        suffix = self._suffix_for_content_type(content_type)
        with tempfile.TemporaryDirectory(prefix="dude-voice-task-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / f"input{suffix}"
            wav_path = tmp_path / "normalized.wav"
            input_path.write_bytes(audio_bytes)
            self._convert_to_wav(input_path, wav_path)
            samples, sample_rate_hz = sf.read(wav_path, always_2d=False)
            if not self._warmed:
                self.asr.warmup()
                self._warmed = True
            transcript = self.asr.transcribe(samples, sample_rate_hz)
            raw_transcript = transcript.text.strip()
            normalized = self.normalizer.normalize(raw_transcript).text
            task = self.orchestrator.run_task(
                TaskRequest(
                    text=normalized,
                    preferred_backend=backend,
                    auto_approve=auto_approve,
                )
            )
        return {
            "raw_transcript": raw_transcript,
            "transcript": normalized,
            "asr_device": self.asr.device_in_use,
            "task": task.to_dict(),
        }

    def _convert_to_wav(self, input_path: Path, wav_path: Path) -> None:
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            str(self.config.audio.sample_rate_hz),
            str(wav_path),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg audio conversion failed: {completed.stderr.strip()}")

    def _suffix_for_content_type(self, content_type: str) -> str:
        lowered = content_type.lower()
        if "wav" in lowered:
            return ".wav"
        if "webm" in lowered:
            return ".webm"
        if "ogg" in lowered:
            return ".ogg"
        if "mpeg" in lowered or "mp3" in lowered:
            return ".mp3"
        return ".bin"
