from __future__ import annotations

import ctypes
import importlib.util
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dude.config import AsrConfig


@dataclass(slots=True)
class TranscriptResult:
    text: str
    language: str | None
    backend: str


class FasterWhisperBackend:
    def __init__(self, config: AsrConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._model = None
        self._device_in_use: str | None = None
        self._compute_type_in_use: str | None = None

    def warmup(self) -> None:
        _ = self.model

    @property
    def device_in_use(self) -> str | None:
        return self._device_in_use

    @property
    def compute_type_in_use(self) -> str | None:
        return self._compute_type_in_use

    @property
    def model(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            device, compute_type = self._resolve_device()
            self._load_model(device, compute_type)
        return self._model

    def _resolve_device(self) -> tuple[str, str]:
        if self.config.device != "auto":
            return self.config.device, "float16" if self.config.device == "cuda" else "int8"
        if shutil.which("nvidia-smi"):
            return "cuda", "float16"
        return "cpu", "int8"

    def _create_model(self, device: str, compute_type: str) -> Any:
        if device == "cuda":
            self._ensure_cuda_runtime_loaded()
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.config.model_name,
            device=device,
            compute_type=compute_type,
        )

    def _ensure_cuda_runtime_loaded(self) -> None:
        lib_dirs = self._discover_cuda_runtime_dirs()
        if not lib_dirs:
            return
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        joined = ":".join(str(path) for path in lib_dirs)
        os.environ["LD_LIBRARY_PATH"] = (
            f"{joined}:{existing}" if existing else joined
        )
        for path in self._candidate_cuda_libraries(lib_dirs):
            try:
                ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                continue

    def _discover_cuda_runtime_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        spec = importlib.util.find_spec("nvidia")
        search_roots: list[Path] = []
        if spec and spec.submodule_search_locations:
            search_roots.extend(Path(entry) for entry in spec.submodule_search_locations)
        for root in search_roots:
            for suffix in ("cublas/lib", "cudnn/lib"):
                path = root / suffix
                if path.exists():
                    candidates.append(path)
        return candidates

    def _candidate_cuda_libraries(self, lib_dirs: list[Path]) -> list[Path]:
        patterns = (
            "libcublas.so*",
            "libcublasLt.so*",
            "libcudnn.so*",
            "libcudnn_ops*.so*",
            "libcudnn_cnn*.so*",
            "libcudnn_adv*.so*",
            "libcudnn_graph*.so*",
            "libcudnn_engines*.so*",
            "libnvrtc.so*",
        )
        libraries: list[Path] = []
        for lib_dir in lib_dirs:
            for pattern in patterns:
                libraries.extend(sorted(lib_dir.glob(pattern)))
        return libraries

    def _load_model(self, device: str, compute_type: str) -> None:
        try:
            self._model = self._create_model(device, compute_type)
        except Exception as exc:
            if not self._can_fallback_to_cpu(device):
                raise
            self._log_cpu_fallback(
                device=device,
                stage="model_init",
                error=str(exc),
            )
            self._model = self._create_model("cpu", "int8")
            self._device_in_use = "cpu"
            self._compute_type_in_use = "int8"
            return

        self._device_in_use = device
        self._compute_type_in_use = compute_type

    def _can_fallback_to_cpu(self, device: str | None) -> bool:
        return self.config.device == "auto" and device not in {None, "cpu"}

    def _log_cpu_fallback(self, *, device: str, stage: str, error: str) -> None:
        self.logger.warning(
            "asr_gpu_fallback",
            extra={
                "event_data": {
                    "backend": "faster_whisper",
                    "from_device": device,
                    "to_device": "cpu",
                    "stage": stage,
                    "error": error,
                }
            },
        )

    def transcribe(self, samples: np.ndarray, sample_rate_hz: int) -> TranscriptResult:
        del sample_rate_hz
        prepared = samples.astype(np.float32)
        try:
            text, info = self._transcribe_text(prepared)
        except Exception as exc:
            if not self._can_fallback_to_cpu(self._device_in_use):
                raise
            self._log_cpu_fallback(
                device=self._device_in_use or "unknown",
                stage="transcribe",
                error=str(exc),
            )
            self._model = self._create_model("cpu", "int8")
            self._device_in_use = "cpu"
            self._compute_type_in_use = "int8"
            text, info = self._transcribe_text(prepared)
        return TranscriptResult(
            text=text,
            language=getattr(info, "language", None),
            backend="faster_whisper",
        )

    def _transcribe_text(self, samples: np.ndarray) -> tuple[str, Any]:
        segments, info = self.model.transcribe(
            samples,
            beam_size=1,
            language=self.config.language,
            vad_filter=False,
            condition_on_previous_text=False,
            temperature=0.0,
            initial_prompt="coding, shell commands, filenames, math expressions",
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list).strip()
        return text, info
