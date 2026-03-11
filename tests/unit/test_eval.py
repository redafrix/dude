import asyncio
from pathlib import Path

from dude.config import load_config
from dude.eval import load_fixture_manifest, record_wake_enrollment


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
