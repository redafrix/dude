from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import soundfile as sf

from dude.config import load_config
from dude.speaker import (
    SpeakerProfile,
    build_speaker_profile,
    verify_speaker_fixture,
)


def test_build_speaker_profile_from_enrollment_manifest(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")
    config.speaker.enabled = True
    config.speaker.min_duration_seconds = 0.0

    take1 = tmp_path / "wake-001.wav"
    take2 = tmp_path / "wake-002.wav"
    sf.write(take1, np.ones(8000, dtype=np.float32) * 0.1, 16000)
    sf.write(take2, np.ones(8000, dtype=np.float32) * 0.2, 16000)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        """
kind: wake_enrollment
phrase: dude
takes:
  - id: wake-001
    path: wake-001.wav
  - id: wake-002
    path: wake-002.wav
""".strip(),
        encoding="utf-8",
    )
    output = tmp_path / "speaker-profile.json"

    def _fake_embed(self, samples: np.ndarray, sample_rate_hz: int) -> np.ndarray:
        del self, sample_rate_hz
        mean = float(np.mean(samples))
        return np.array([mean, 1.0 - mean], dtype=np.float32)

    monkeypatch.setattr("dude.speaker.SpeechBrainSpeakerVerifier._embed_samples", _fake_embed)

    payload = build_speaker_profile(config, logging.getLogger("test"), manifest, output)

    assert output.exists()
    assert payload["take_count"] == 2
    assert payload["phrase"] == "dude"
    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["kind"] == "speaker_profile"
    assert len(profile["embeddings"]) == 2


def test_verify_speaker_fixture_uses_profile_threshold(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")
    config.speaker.enabled = True
    config.speaker.min_duration_seconds = 0.0

    fixture = tmp_path / "fixture.wav"
    sf.write(fixture, np.ones(8000, dtype=np.float32) * 0.1, 16000)
    profile_path = tmp_path / "profile.json"
    profile = SpeakerProfile(
        backend="speechbrain_ecapa",
        created_at="2026-03-11T00:00:00+00:00",
        threshold=0.25,
        sample_rate_hz=16000,
        source_manifest_path=None,
        phrase="dude",
        take_ids=["wake-001"],
        centroid=[1.0, 0.0],
        embeddings=[[1.0, 0.0]],
    )
    profile_path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")

    monkeypatch.setattr(
        "dude.speaker.SpeechBrainSpeakerVerifier._embed_samples",
        lambda self, samples, sample_rate_hz: np.array([1.0, 0.0], dtype=np.float32),
    )
    accepted = verify_speaker_fixture(config, logging.getLogger("test"), profile_path, fixture)
    assert accepted["accepted"] is True

    monkeypatch.setattr(
        "dude.speaker.SpeechBrainSpeakerVerifier._embed_samples",
        lambda self, samples, sample_rate_hz: np.array([-1.0, 0.0], dtype=np.float32),
    )
    rejected = verify_speaker_fixture(config, logging.getLogger("test"), profile_path, fixture)
    assert rejected["accepted"] is False
