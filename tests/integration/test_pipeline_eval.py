from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from dude.backends.tts import SpeechResult
from dude.config import load_config
from dude.eval import evaluate_pipeline


class _FakeAsr:
    def __init__(self, transcripts: list[str]) -> None:
        self._transcripts = iter(transcripts)
        self.device_in_use = "cpu"
        self.compute_type_in_use = "int8"

    def warmup(self) -> None:
        return None

    def transcribe(self, samples: np.ndarray, sample_rate_hz: int):
        del samples, sample_rate_hz
        try:
            text = next(self._transcripts)
        except StopIteration:
            text = ""
        return SimpleNamespace(text=text, language="en")


class _FakeTts:
    def synthesize(self, text: str) -> SpeechResult:
        del text
        samples = np.ones(16000, dtype=np.float32) * 0.1
        return SpeechResult(samples=samples, sample_rate_hz=16000, backend="fake")


class _FakeSpeakerVerifier:
    def __init__(self, accepted: bool) -> None:
        self.accepted = accepted

    def verify(self, samples: np.ndarray, sample_rate_hz: int):
        del samples, sample_rate_hz
        return SimpleNamespace(
            accepted=self.accepted,
            score=0.91 if self.accepted else 0.04,
            threshold=0.25,
            backend="fake_speaker",
            reason="matched" if self.accepted else "below_threshold",
        )


def test_eval_pipeline_replays_fixture_through_pipeline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.vad.min_silence_ms = 120
    fixture = tmp_path / "hello.wav"
    samples = np.concatenate(
        [
            np.ones(int(config.audio.sample_rate_hz * 0.35), dtype=np.float32) * 0.2,
            np.zeros(int(config.audio.sample_rate_hz * 0.35), dtype=np.float32),
        ]
    )
    sf.write(fixture, samples, config.audio.sample_rate_hz)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""
cases:
  - id: hello
    scenario: greeting
    path: {fixture}
    expected_wake: true
    expected_transcript_contains:
      - dude
      - hello
    expected_response_contains:
      - hi
""".strip(),
        encoding="utf-8",
    )

    fake_asr = _FakeAsr(["Dude, hello"])
    monkeypatch.setattr("dude.eval.FasterWhisperBackend", lambda config, logger: fake_asr)
    monkeypatch.setattr("dude.eval.SpeechSynthesizer", lambda config, logger: _FakeTts())

    payload = asyncio.run(
        evaluate_pipeline(config, manifest, logging.getLogger("test"), realtime=False)
    )

    assert payload["case_count"] == 1
    assert payload["wake_pass_count"] == 1
    assert payload["transcript_pass_count"] == 1
    assert payload["response_pass_count"] == 1
    result = payload["results"][0]
    assert result["wake_triggered"] is True
    assert result["utterance_count"] == 1
    assert result["utterances"][0]["raw_transcript"] == "Dude, hello"
    assert result["utterances"][0]["transcript"] == "Dude, hello"
    assert result["utterances"][0]["response_text"] == "Hi, what can I help you with?"


def test_eval_pipeline_detects_barge_in_case(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.vad.min_silence_ms = 160
    config.audio.barge_in_grace_ms = 50
    fixture = tmp_path / "barge.wav"
    sr = config.audio.sample_rate_hz
    samples = np.concatenate(
        [
            np.ones(int(sr * 0.35), dtype=np.float32) * 0.2,
            np.zeros(int(sr * 0.25), dtype=np.float32),
            np.zeros(int(sr * 0.15), dtype=np.float32),
            np.ones(int(sr * 0.35), dtype=np.float32) * 0.2,
            np.zeros(int(sr * 0.35), dtype=np.float32),
        ]
    )
    sf.write(fixture, samples, sr)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""
cases:
  - id: barge
    scenario: barge_in
    path: {fixture}
    expected_wake: true
""".strip(),
        encoding="utf-8",
    )

    fake_asr = _FakeAsr(["Dude, hello", "status"])
    monkeypatch.setattr("dude.eval.FasterWhisperBackend", lambda config, logger: fake_asr)
    monkeypatch.setattr("dude.eval.SpeechSynthesizer", lambda config, logger: _FakeTts())

    payload = asyncio.run(
        evaluate_pipeline(config, manifest, logging.getLogger("test"), realtime=False)
    )

    assert payload["barge_in_case_count"] == 1
    assert payload["barge_in_detected_count"] == 1
    result = payload["results"][0]
    assert result["barge_in_detected"] is True
    assert result["utterance_count"] >= 2


def test_eval_pipeline_uses_normalized_transcript_expectations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.vad.min_silence_ms = 120
    fixture = tmp_path / "math.wav"
    samples = np.concatenate(
        [
            np.ones(int(config.audio.sample_rate_hz * 0.35), dtype=np.float32) * 0.2,
            np.zeros(int(config.audio.sample_rate_hz * 0.35), dtype=np.float32),
        ]
    )
    sf.write(fixture, samples, config.audio.sample_rate_hz)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""
cases:
  - id: math
    scenario: coding_math
    path: {fixture}
    expected_wake: true
    expected_transcript_contains:
      - alpha - 2 + 3
""".strip(),
        encoding="utf-8",
    )

    fake_asr = _FakeAsr(["Dude, alpha minus two plus three"])
    monkeypatch.setattr("dude.eval.FasterWhisperBackend", lambda config, logger: fake_asr)
    monkeypatch.setattr("dude.eval.SpeechSynthesizer", lambda config, logger: _FakeTts())

    payload = asyncio.run(
        evaluate_pipeline(config, manifest, logging.getLogger("test"), realtime=False)
    )

    assert payload["transcript_pass_count"] == 1
    result = payload["results"][0]
    assert result["utterances"][0]["transcript"].endswith("alpha - 2 + 3")


def test_eval_pipeline_tracks_speaker_expectations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.speaker.enabled = True
    config.speaker.mode = "enforce"
    config.vad.min_silence_ms = 120
    fixture = tmp_path / "hello.wav"
    samples = np.concatenate(
        [
            np.ones(int(config.audio.sample_rate_hz * 0.35), dtype=np.float32) * 0.2,
            np.zeros(int(config.audio.sample_rate_hz * 0.35), dtype=np.float32),
        ]
    )
    sf.write(fixture, samples, config.audio.sample_rate_hz)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""
cases:
  - id: hello
    scenario: greeting
    path: {fixture}
    expected_wake: true
    expected_speaker_match: false
""".strip(),
        encoding="utf-8",
    )

    fake_asr = _FakeAsr(["Dude, hello"])
    monkeypatch.setattr("dude.eval.FasterWhisperBackend", lambda config, logger: fake_asr)
    monkeypatch.setattr("dude.eval.SpeechSynthesizer", lambda config, logger: _FakeTts())
    monkeypatch.setattr(
        "dude.pipeline.build_speaker_verifier",
        lambda config, logger: _FakeSpeakerVerifier(False),
    )

    payload = asyncio.run(
        evaluate_pipeline(config, manifest, logging.getLogger("test"), realtime=False)
    )

    assert payload["speaker_expected_count"] == 1
    assert payload["speaker_pass_count"] == 1
    assert payload["results"][0]["utterances"][0]["speaker_verified"] is False
