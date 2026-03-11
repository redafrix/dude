from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dude.config import DudeConfig, ScreenConfig


@dataclass(slots=True)
class ScreenCaptureResult:
    executor: str
    command: list[str]
    exit_code: int | None
    stdout_text: str
    stderr_text: str


@dataclass(slots=True)
class ScreenRequest:
    action: str
    duration_seconds: float | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_screen_request(text: str, *, default_clip_seconds: float) -> ScreenRequest:
    lowered = text.strip().lower()
    if any(
        phrase in lowered
        for phrase in (
            "screen state",
            "desktop state",
            "last screen capture",
            "last screenshot",
        )
    ):
        return ScreenRequest(action="state")
    if any(
        phrase in lowered
        for phrase in (
            "record screen",
            "record the screen",
            "record desktop",
            "record what you're doing",
            "record what you are doing",
            "screen recording",
        )
    ):
        match = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b", lowered)
        duration = float(match.group(1)) if match else default_clip_seconds
        return ScreenRequest(action="record", duration_seconds=duration)
    return ScreenRequest(action="screenshot")


class ScreenCaptureController:
    def __init__(self, config: DudeConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.screen_config: ScreenConfig = config.screen
        self.artifact_dir = (
            self.screen_config.artifact_dir
            if self.screen_config.artifact_dir is not None
            else config.runtime.state_dir / "screen"
        )
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.artifact_dir / "last-screen-state.json"

    def execute_request(self, request_text: str, working_dir: Path) -> ScreenCaptureResult:
        request = parse_screen_request(
            request_text,
            default_clip_seconds=self.screen_config.default_clip_seconds,
        )
        if request.action == "state":
            return self.show_state()
        if request.action == "record":
            return self.record_clip(
                working_dir,
                request.duration_seconds or self.screen_config.default_clip_seconds,
            )
        return self.capture_screenshot(working_dir)

    def capture_screenshot(self, working_dir: Path) -> ScreenCaptureResult:
        display = self._resolve_display()
        resolution = self._detect_resolution()
        output_path = self._artifact_path("png")
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "x11grab",
            "-video_size",
            resolution,
            "-i",
            f"{display}+0,0",
            "-frames:v",
            "1",
            str(output_path),
        ]
        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=self.screen_config.screenshot_timeout_seconds,
            env=self._capture_env(),
        )
        if completed.returncode == 0:
            self._save_state(
                {
                    "updated_at": _utc_now(),
                    "mode": "screenshot",
                    "display": display,
                    "resolution": resolution,
                    "artifact_path": str(output_path),
                }
            )
        stdout_text = (
            f"Captured a desktop screenshot to {output_path}."
            if completed.returncode == 0
            else ""
        )
        return ScreenCaptureResult(
            executor="screen",
            command=command,
            exit_code=completed.returncode,
            stdout_text=stdout_text,
            stderr_text=completed.stderr.strip(),
        )

    def capture_screenshot_bytes(
        self,
        working_dir: Path,
        *,
        image_format: str = "jpeg",
    ) -> tuple[bytes, str]:
        display = self._resolve_display()
        resolution = self._detect_resolution()
        codec = "mjpeg" if image_format in {"jpg", "jpeg", "mjpeg"} else "png"
        content_type = "image/jpeg" if codec == "mjpeg" else "image/png"
        command = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "x11grab",
            "-video_size",
            resolution,
            "-i",
            f"{display}+0,0",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            codec,
            "pipe:1",
        ]
        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            timeout=self.screen_config.screenshot_timeout_seconds,
            env=self._capture_env(),
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Live screen capture failed: {stderr}")
        return completed.stdout, content_type

    def record_clip(self, working_dir: Path, duration_seconds: float) -> ScreenCaptureResult:
        display = self._resolve_display()
        resolution = self._detect_resolution()
        output_path = self._artifact_path("mp4")
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "x11grab",
            "-video_size",
            resolution,
            "-framerate",
            str(self.screen_config.framerate),
            "-i",
            f"{display}+0,0",
            "-t",
            str(duration_seconds),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(output_path),
        ]
        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=max(
                int(duration_seconds) + 5,
                self.screen_config.record_timeout_seconds,
            ),
            env=self._capture_env(),
        )
        if completed.returncode == 0:
            self._save_state(
                {
                    "updated_at": _utc_now(),
                    "mode": "clip",
                    "display": display,
                    "resolution": resolution,
                    "duration_seconds": duration_seconds,
                    "artifact_path": str(output_path),
                }
            )
        stdout_text = (
            f"Recorded a desktop clip to {output_path}."
            if completed.returncode == 0
            else ""
        )
        return ScreenCaptureResult(
            executor="screen",
            command=command,
            exit_code=completed.returncode,
            stdout_text=stdout_text,
            stderr_text=completed.stderr.strip(),
        )

    def show_state(self) -> ScreenCaptureResult:
        state = self.get_state()
        if state is None:
            return ScreenCaptureResult(
                executor="screen",
                command=[],
                exit_code=0,
                stdout_text="No desktop capture has been recorded yet.",
                stderr_text="",
            )
        detail = (
            f"Last desktop capture was a {state.get('mode', 'capture')} at "
            f"{state.get('updated_at', 'unknown')}."
        )
        if artifact_path := state.get("artifact_path"):
            detail += f" Artifact: {artifact_path}."
        if resolution := state.get("resolution"):
            detail += f" Resolution: {resolution}."
        return ScreenCaptureResult(
            executor="screen",
            command=[],
            exit_code=0,
            stdout_text=detail,
            stderr_text="",
        )

    def get_state(self) -> dict[str, object] | None:
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _resolve_display(self) -> str:
        display = self.screen_config.display or os.environ.get("DISPLAY")
        if not display:
            raise RuntimeError("DISPLAY is not set for desktop capture.")
        return display

    def _detect_resolution(self) -> str:
        env = self._capture_env()
        completed = subprocess.run(
            ["xdpyinfo"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"xdpyinfo failed: {completed.stderr.strip()}")
        match = re.search(r"dimensions:\s+(\d+x\d+)\s+pixels", completed.stdout)
        if not match:
            raise RuntimeError("Could not determine X11 display dimensions.")
        return match.group(1)

    def _artifact_path(self, extension: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.artifact_dir / f"{stamp}-desktop.{extension}"

    def _capture_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DISPLAY"] = self._resolve_display()
        return env

    def _save_state(self, payload: dict[str, object]) -> None:
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
