from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from dude.config import load_config
from dude.screen import ScreenCaptureController, parse_screen_request


def test_parse_screen_request_defaults_to_screenshot() -> None:
    request = parse_screen_request(
        "take a screenshot",
        default_clip_seconds=6.0,
    )

    assert request.action == "screenshot"
    assert request.duration_seconds is None


def test_parse_screen_request_detects_record_with_duration() -> None:
    request = parse_screen_request(
        "record screen for 9 seconds",
        default_clip_seconds=6.0,
    )

    assert request.action == "record"
    assert request.duration_seconds == 9.0


def test_parse_screen_request_detects_state_lookup() -> None:
    request = parse_screen_request(
        "show me the last screenshot",
        default_clip_seconds=6.0,
    )

    assert request.action == "state"


def test_screen_controller_can_capture_live_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.screen.artifact_dir = tmp_path / "screen"
    controller = ScreenCaptureController(config, logging.getLogger("test"))

    monkeypatch.setattr(controller, "_resolve_display", lambda: ":0")
    monkeypatch.setattr(controller, "_detect_resolution", lambda: "1920x1080")
    monkeypatch.setattr(controller, "_capture_env", lambda: {"DISPLAY": ":0"})

    def _run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=0,
            stdout=b"jpegbytes",
            stderr=b"",
        )

    monkeypatch.setattr("dude.screen.subprocess.run", _run)

    payload, content_type = controller.capture_screenshot_bytes(tmp_path)

    assert payload == b"jpegbytes"
    assert content_type == "image/jpeg"
