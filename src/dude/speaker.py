from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import numpy as np
import soundfile as sf
import yaml

from dude.config import DudeConfig, SpeakerConfig


@dataclass(slots=True)
class SpeakerVerificationResult:
    accepted: bool
    score: float | None
    threshold: float
    backend: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "score": None if self.score is None else round(self.score, 4),
            "threshold": round(self.threshold, 4),
            "backend": self.backend,
            "reason": self.reason,
        }


@dataclass(slots=True)
class SpeakerProfile:
    backend: str
    created_at: str
    threshold: float
    sample_rate_hz: int
    source_manifest_path: str | None
    phrase: str | None
    take_ids: list[str]
    centroid: list[float]
    embeddings: list[list[float]]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "speaker_profile",
            "version": 1,
            "backend": self.backend,
            "created_at": self.created_at,
            "threshold": self.threshold,
            "sample_rate_hz": self.sample_rate_hz,
            "source_manifest_path": self.source_manifest_path,
            "phrase": self.phrase,
            "take_ids": self.take_ids,
            "centroid": self.centroid,
            "embeddings": self.embeddings,
        }

    @classmethod
    def from_path(cls, path: Path) -> SpeakerProfile:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            backend=str(raw.get("backend", "speechbrain_ecapa")),
            created_at=str(raw.get("created_at", "")),
            threshold=float(raw.get("threshold", 0.25)),
            sample_rate_hz=int(raw.get("sample_rate_hz", 16000)),
            source_manifest_path=raw.get("source_manifest_path"),
            phrase=raw.get("phrase"),
            take_ids=[str(item) for item in raw.get("take_ids", [])],
            centroid=[float(value) for value in raw.get("centroid", [])],
            embeddings=[
                [float(value) for value in embedding]
                for embedding in raw.get("embeddings", [])
            ],
        )


class SpeakerVerifier(Protocol):
    def verify(self, samples: np.ndarray, sample_rate_hz: int) -> SpeakerVerificationResult:
        ...


def _load_audio(path: Path, target_rate_hz: int) -> np.ndarray:
    samples, sample_rate_hz = sf.read(path, always_2d=False)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if sample_rate_hz == target_rate_hz:
        return samples.astype(np.float32)
    new_length = int(round(len(samples) * target_rate_hz / sample_rate_hz))
    if new_length <= 0 or len(samples) == 0:
        return np.zeros(0, dtype=np.float32)
    source_idx = np.arange(len(samples), dtype=np.float32)
    target_idx = np.linspace(0, len(samples) - 1, num=new_length, dtype=np.float32)
    return np.interp(target_idx, source_idx, samples).astype(np.float32)


def _normalize_embedding(values: np.ndarray) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vector)
    if norm <= 1e-12:
        return vector
    return vector / norm


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    left = _normalize_embedding(a)
    right = _normalize_embedding(b)
    if left.size == 0 or right.size == 0:
        return 0.0
    return float(np.dot(left, right))


def _load_enrollment_manifest(path: Path) -> tuple[str | None, list[tuple[str, Path]]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Enrollment manifest must be a mapping.")
    takes_raw = raw.get("takes", [])
    if not isinstance(takes_raw, list) or not takes_raw:
        raise ValueError("Enrollment manifest does not contain any takes.")
    base_dir = path.parent
    phrase = raw.get("phrase")
    takes: list[tuple[str, Path]] = []
    for item in takes_raw:
        if not isinstance(item, dict):
            raise ValueError("Enrollment manifest contains an invalid take entry.")
        take_id = str(item.get("id", "")).strip()
        take_path = item.get("path")
        if not take_id or not take_path:
            raise ValueError("Enrollment take entries must define `id` and `path`.")
        resolved = (base_dir / str(take_path)).resolve()
        takes.append((take_id, resolved))
    return (str(phrase) if phrase is not None else None, takes)


class SpeechBrainSpeakerVerifier:
    def __init__(
        self,
        config: SpeakerConfig,
        logger: logging.Logger,
        *,
        profile: SpeakerProfile | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        if profile is None:
            if config.profile_path is None:
                raise ValueError("Speaker verification requires `speaker.profile_path`.")
            profile = SpeakerProfile.from_path(Path(config.profile_path))
        self.profile = profile
        self._classifier = None

    def _load_encoder(self):
        if self._classifier is not None:
            return self._classifier

        try:
            from speechbrain.inference.classifiers import EncoderClassifier
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Speaker verification requires the optional speaker extra. "
                "Install it with `uv sync --extra speaker`."
            ) from exc

        cache_root = self.config.cache_dir
        savedir = None
        if cache_root is not None:
            cache_root.mkdir(parents=True, exist_ok=True)
            savedir = str((cache_root / "speechbrain-ecapa").resolve())

        self._classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=savedir,
            run_opts={"device": "cpu"},
        )
        return self._classifier

    def _embed_samples(self, samples: np.ndarray, sample_rate_hz: int) -> np.ndarray:
        waveform = _load_audio_from_array(samples, sample_rate_hz, self.profile.sample_rate_hz)
        if waveform.size == 0:
            return waveform
        classifier = self._load_encoder()
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Speaker verification requires torch through the optional speaker extra."
            ) from exc
        batch = torch.tensor(waveform, dtype=torch.float32).unsqueeze(0)
        embedding = classifier.encode_batch(batch)
        return np.asarray(embedding.squeeze().detach().cpu().numpy(), dtype=np.float32)

    def verify(self, samples: np.ndarray, sample_rate_hz: int) -> SpeakerVerificationResult:
        duration_seconds = 0.0
        if sample_rate_hz > 0:
            duration_seconds = float(len(samples) / sample_rate_hz)
        if duration_seconds < self.config.min_duration_seconds:
            return SpeakerVerificationResult(
                accepted=False,
                score=None,
                threshold=self.profile.threshold,
                backend=self.profile.backend,
                reason="too_short",
            )

        embedding = self._embed_samples(samples, sample_rate_hz)
        if embedding.size == 0:
            return SpeakerVerificationResult(
                accepted=False,
                score=None,
                threshold=self.profile.threshold,
                backend=self.profile.backend,
                reason="empty_audio",
            )

        exemplar_scores = [
            _cosine_similarity(embedding, np.asarray(reference, dtype=np.float32))
            for reference in self.profile.embeddings
        ]
        centroid_score = _cosine_similarity(
            embedding,
            np.asarray(self.profile.centroid, dtype=np.float32),
        )
        score = max([centroid_score, *exemplar_scores], default=centroid_score)
        return SpeakerVerificationResult(
            accepted=score >= self.profile.threshold,
            score=score,
            threshold=self.profile.threshold,
            backend=self.profile.backend,
            reason="matched" if score >= self.profile.threshold else "below_threshold",
        )

    @classmethod
    def build_profile(
        cls,
        config: SpeakerConfig,
        logger: logging.Logger,
        *,
        manifest_path: Path,
        output_path: Path,
        threshold: float | None = None,
    ) -> SpeakerProfile:
        phrase, takes = _load_enrollment_manifest(manifest_path)
        verifier = cls(
            config,
            logger,
            profile=SpeakerProfile(
                backend=config.provider,
                created_at="",
                threshold=threshold if threshold is not None else config.threshold,
                sample_rate_hz=config.sample_rate_hz,
                source_manifest_path=str(manifest_path),
                phrase=phrase,
                take_ids=[],
                centroid=[],
                embeddings=[],
            ),
        )

        take_ids: list[str] = []
        embeddings: list[np.ndarray] = []
        for take_id, take_path in takes:
            samples = _load_audio(take_path, config.sample_rate_hz)
            if len(samples) / config.sample_rate_hz < config.min_duration_seconds:
                continue
            embedding = _normalize_embedding(
                verifier._embed_samples(samples, config.sample_rate_hz)
            )
            if embedding.size == 0:
                continue
            take_ids.append(take_id)
            embeddings.append(embedding)

        if not embeddings:
            raise ValueError("No valid enrollment takes could be embedded.")

        centroid = _normalize_embedding(np.mean(np.stack(embeddings, axis=0), axis=0))
        profile = SpeakerProfile(
            backend=config.provider,
            created_at=datetime.now(timezone.utc).isoformat(),
            threshold=threshold if threshold is not None else config.threshold,
            sample_rate_hz=config.sample_rate_hz,
            source_manifest_path=str(manifest_path),
            phrase=phrase,
            take_ids=take_ids,
            centroid=centroid.tolist(),
            embeddings=[embedding.tolist() for embedding in embeddings],
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        return profile


def _load_audio_from_array(
    samples: np.ndarray,
    sample_rate_hz: int,
    target_rate_hz: int,
) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate_hz == target_rate_hz:
        return audio.astype(np.float32)
    new_length = int(round(len(audio) * target_rate_hz / sample_rate_hz))
    if new_length <= 0 or len(audio) == 0:
        return np.zeros(0, dtype=np.float32)
    source_idx = np.arange(len(audio), dtype=np.float32)
    target_idx = np.linspace(0, len(audio) - 1, num=new_length, dtype=np.float32)
    return np.interp(target_idx, source_idx, audio).astype(np.float32)


def build_speaker_verifier(
    config: DudeConfig,
    logger: logging.Logger,
) -> SpeakerVerifier | None:
    if not config.speaker.enabled:
        return None
    return SpeechBrainSpeakerVerifier(config.speaker, logger)


def build_speaker_profile(
    config: DudeConfig,
    logger: logging.Logger,
    manifest_path: Path,
    output_path: Path,
    *,
    threshold: float | None = None,
) -> dict[str, object]:
    profile = SpeechBrainSpeakerVerifier.build_profile(
        config.speaker,
        logger,
        manifest_path=manifest_path,
        output_path=output_path,
        threshold=threshold,
    )
    return {
        "output_path": str(output_path),
        "source_manifest_path": str(manifest_path),
        "backend": profile.backend,
        "phrase": profile.phrase,
        "take_count": len(profile.take_ids),
        "threshold": profile.threshold,
    }


def verify_speaker_fixture(
    config: DudeConfig,
    logger: logging.Logger,
    profile_path: Path,
    fixture_path: Path,
) -> dict[str, object]:
    speaker_config = SpeakerConfig(
        enabled=True,
        mode=config.speaker.mode,
        provider=config.speaker.provider,
        profile_path=profile_path,
        enrollment_manifest_path=config.speaker.enrollment_manifest_path,
        threshold=config.speaker.threshold,
        sample_rate_hz=config.speaker.sample_rate_hz,
        min_duration_seconds=config.speaker.min_duration_seconds,
        cache_dir=config.speaker.cache_dir,
    )
    verifier = SpeechBrainSpeakerVerifier(speaker_config, logger)
    samples, sample_rate_hz = sf.read(fixture_path, always_2d=False)
    result = verifier.verify(np.asarray(samples, dtype=np.float32), int(sample_rate_hz))
    payload = result.to_dict()
    payload.update(
        {
            "fixture_path": str(fixture_path),
            "profile_path": str(profile_path),
        }
    )
    return payload
