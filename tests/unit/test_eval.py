import asyncio
import logging
from pathlib import Path

from dude.config import load_config
from dude.eval import (
    benchmark_voice_corpus,
    load_fixture_manifest,
    record_scenario_corpus,
    record_wake_enrollment,
)


def test_load_fixture_manifest_supports_list_and_relative_paths(tmp_path: Path) -> None:
    fixture = tmp_path / "hello.wav"
    fixture.write_bytes(b"RIFF")
    manifest = tmp_path / "fixtures.yaml"
    manifest.write_text(
        """
- id: hello
  path: hello.wav
  scenario: greeting
  expected_wake: true
  expected_speaker_match: true
  expected_transcript_contains:
    - hello
  expected_response_contains: Hi
""".strip(),
        encoding="utf-8",
    )

    cases = load_fixture_manifest(manifest)
    assert len(cases) == 1
    assert cases[0].fixture_id == "hello"
    assert cases[0].path == fixture.resolve()
    assert cases[0].scenario == "greeting"
    assert cases[0].expected_wake is True
    assert cases[0].expected_speaker_match is True
    assert cases[0].expected_transcript_contains == ["hello"]
    assert cases[0].expected_response_contains == ["hi"]


def test_record_wake_enrollment_writes_manifest(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")

    async def _fake_record_fixture(config, output_path: Path, duration_seconds: float):
        del config, duration_seconds
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFF")
        return {
            "output_path": str(output_path),
            "duration_seconds": 1.8,
            "sample_rate_hz": 16000,
        }

    monkeypatch.setattr("dude.eval.record_fixture", _fake_record_fixture)

    payload = asyncio.run(
        record_wake_enrollment(
            config,
            tmp_path / "reda",
            phrase="dude",
            take_count=3,
            duration_seconds=1.8,
        )
    )

    manifest_path = Path(payload["manifest_path"])
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert payload["take_count"] == 3
    assert "wake_enrollment" in manifest_text
    assert "phrase: dude" in manifest_text
    assert "wake-001.wav" in manifest_text


def test_record_scenario_corpus_writes_manifest(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")

    async def _fake_record_fixture(config, output_path: Path, duration_seconds: float):
        del config, duration_seconds
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFF")
        return {
            "output_path": str(output_path),
            "duration_seconds": 1.0,
            "sample_rate_hz": 16000,
        }

    monkeypatch.setattr("dude.eval.record_fixture", _fake_record_fixture)

    payload = asyncio.run(
        record_scenario_corpus(
            config,
            tmp_path / "corpus",
            profile="m1-core",
            takes_per_prompt=1,
            announce=False,
        )
    )

    manifest_path = Path(payload["manifest_path"])
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert payload["case_count"] >= 5
    assert "voice_corpus" in manifest_text
    assert "wake-hello-01.wav" in manifest_text
    assert "spoken_prompt: Dude, hello" in manifest_text
    assert "expected_speaker_match: true" in manifest_text


def test_benchmark_voice_corpus_compares_backends(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("cases: []\n", encoding="utf-8")

    fixture_report = {"case_count": 0, "wake_pass_count": 0}
    pipeline_reports = {
        "transcript": {
            "wake_pass_count": 8,
            "wake_expected_count": 10,
            "transcript_pass_count": 6,
            "transcript_expected_count": 10,
            "response_pass_count": 5,
            "response_expected_count": 10,
            "speaker_pass_count": 0,
            "speaker_expected_count": 0,
        },
        "openwakeword": {
            "wake_pass_count": 9,
            "wake_expected_count": 10,
            "transcript_pass_count": 6,
            "transcript_expected_count": 10,
            "response_pass_count": 5,
            "response_expected_count": 10,
            "speaker_pass_count": 0,
            "speaker_expected_count": 0,
        },
    }

    monkeypatch.setattr(
        "dude.eval.evaluate_fixtures",
        lambda config, manifest, logger: fixture_report,
    )

    async def _fake_eval_pipeline(config, manifest, logger, *, wake_backend=None, realtime=False):
        del config, manifest, logger, realtime
        assert wake_backend is not None
        return dict(pipeline_reports[wake_backend])

    monkeypatch.setattr("dude.eval.evaluate_pipeline", _fake_eval_pipeline)

    payload = asyncio.run(
        benchmark_voice_corpus(
            config,
            manifest,
            logger=logging.getLogger("test"),
            wake_backends=["transcript", "openwakeword"],
        )
    )

    assert payload["recommended_wake_backend"]["backend"] == "openwakeword"
    assert payload["wake_backend_reports"]["transcript"]["wake_pass_rate"] == 0.8
    assert payload["wake_backend_reports"]["openwakeword"]["wake_pass_rate"] == 0.9
