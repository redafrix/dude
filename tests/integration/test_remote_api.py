from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dude.audit import AuditStore
from dude.browser import BrowserToolResult
from dude.config import load_config
from dude.orchestrator import ActionResult, Orchestrator
from dude.remote_api import RemoteApiServer
from dude.screen import ScreenCaptureResult


class _FakeRunner:
    def __init__(self, executor: str, stdout_text: str) -> None:
        self.executor = executor
        self.stdout_text = stdout_text

    def run(self, prompt: str, *, working_dir: Path, timeout_seconds: int) -> ActionResult:
        del prompt, working_dir, timeout_seconds
        return ActionResult(
            executor=self.executor,
            command=[self.executor, "mock"],
            exit_code=0,
            stdout_text=self.stdout_text,
            stderr_text="",
        )


class _FakeBrowserController:
    def __init__(self, screenshot_path: Path) -> None:
        self.screenshot_path = screenshot_path

    def execute_request(self, request_text: str, working_dir: Path) -> BrowserToolResult:
        del request_text, working_dir
        return BrowserToolResult(
            executor="browser",
            command=["browser", "mock"],
            exit_code=0,
            stdout_text="Opened https://example.com in a headless browser and saved a screenshot.",
            stderr_text="",
        )

    def show_state(self) -> BrowserToolResult:
        return BrowserToolResult(
            executor="browser",
            command=[],
            exit_code=0,
            stdout_text="Last browser activity used headless mode at now for https://example.com.",
            stderr_text="",
        )

    def get_state(self) -> dict[str, object]:
        return {
            "updated_at": "now",
            "mode": "headless",
            "engine": "fake",
            "url": "https://example.com",
            "title": "Example",
            "screenshot_path": str(self.screenshot_path),
        }


class _FakeScreenController:
    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path

    def capture_screenshot(self, working_dir: Path) -> ScreenCaptureResult:
        del working_dir
        return ScreenCaptureResult(
            executor="screen",
            command=["screen", "screenshot"],
            exit_code=0,
            stdout_text="Captured a desktop screenshot to /tmp/desktop.png.",
            stderr_text="",
        )

    def execute_request(self, request_text: str, working_dir: Path) -> ScreenCaptureResult:
        del request_text, working_dir
        return ScreenCaptureResult(
            executor="screen",
            command=["screen", "record"],
            exit_code=0,
            stdout_text="Recorded a desktop clip to /tmp/desktop.mp4.",
            stderr_text="",
        )

    def show_state(self) -> ScreenCaptureResult:
        return ScreenCaptureResult(
            executor="screen",
            command=[],
            exit_code=0,
            stdout_text="Last desktop capture was a screenshot at now. Artifact: /tmp/desktop.png.",
            stderr_text="",
        )

    def get_state(self) -> dict[str, object]:
        return {
            "updated_at": "now",
            "mode": "screenshot",
            "resolution": "1920x1200",
            "artifact_path": str(self.artifact_path),
        }

    def capture_screenshot_bytes(
        self,
        working_dir: Path,
        *,
        image_format: str = "jpeg",
    ) -> tuple[bytes, str]:
        del working_dir
        if image_format == "png":
            return b"livepng", "image/png"
        return b"livejpeg", "image/jpeg"


class _FakeVoiceProcessor:
    def process_audio_task(
        self,
        audio_bytes: bytes,
        *,
        content_type: str,
        backend,
        auto_approve: bool,
    ):
        del content_type, backend, auto_approve
        if not audio_bytes:
            raise ValueError("Audio body is empty.")
        return {
            "raw_transcript": "take a screenshot",
            "transcript": "take a screenshot",
            "asr_device": "cpu",
            "task": {
                "task_id": "voice-task-1",
                "status": "completed",
                "backend": "local",
                "approval_class": "safe_local",
                "route_reason": "screen_capture",
                "request_text": "take a screenshot",
                "output_text": "Captured a desktop screenshot.",
                "error_text": "",
                "requires_approval": False,
                "actions": [],
            },
        }


class _FakeReplyAudioController:
    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path
        self._state: dict[str, object] | None = None

    def synthesize_reply(self, text: str) -> dict[str, object]:
        self._state = {
            "updated_at": "now",
            "text": text,
            "artifact_path": str(self.artifact_path),
            "sample_rate_hz": 24000,
            "backend": "kokoro",
        }
        return dict(self._state)

    def get_state(self) -> dict[str, object] | None:
        return None if self._state is None else dict(self._state)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    data = None
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _request_bytes(
    url: str,
    *,
    token: str | None = None,
) -> tuple[int, bytes, str]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get_content_type()


def test_remote_api_exposes_task_audit_and_browser_state(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    config.runtime.state_dir = tmp_path / "runtime"
    config.remote.bind_host = "127.0.0.1"
    config.remote.port = 0
    config.remote.auth_token_path = tmp_path / "remote.token"
    screenshot_path = tmp_path / "browser.png"
    screenshot_path.write_bytes(b"fakepng")
    desktop_path = tmp_path / "desktop.png"
    desktop_path.write_bytes(b"fakescreen")
    reply_audio_path = tmp_path / "reply.wav"
    reply_audio_path.write_bytes(b"fakewavreply")
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "done"),
        gemini_runner=_FakeRunner("gemini", "planned"),
        browser_controller=_FakeBrowserController(screenshot_path),
        screen_controller=_FakeScreenController(desktop_path),
    )
    server = RemoteApiServer(
        config,
        logging.getLogger("test"),
        orchestrator=orchestrator,
        voice_processor=_FakeVoiceProcessor(),
        reply_audio=_FakeReplyAudioController(reply_audio_path),
    )
    server.start_in_thread()
    try:
        host, port = server.server_address
        base_url = f"http://{host}:{port}"
        token = server.ensure_auth_token()

        status, health = _request_json(f"{base_url}/health")
        assert status == 200
        assert health["ok"] is True

        index_status, index_body, index_content_type = _request_bytes(f"{base_url}/")
        assert index_status == 200
        assert index_content_type == "text/html"
        assert b"Dude Remote" in index_body
        assert b"Memory" in index_body

        status, unauthorized = _request_json(f"{base_url}/audit?{urlencode({'limit': 1})}")
        assert status == 401
        assert unauthorized["ok"] is False

        status, memory_payload = _request_json(
            f"{base_url}/memory?{urlencode({'limit': 5})}",
            token=token,
        )
        assert status == 200
        assert memory_payload["memory"] == []

        status, task = _request_json(
            f"{base_url}/task",
            method="POST",
            token=token,
            payload={"text": "what is the current directory", "voice_reply": True},
        )
        assert status == 200
        assert task["task"]["status"] == "completed"
        assert task["task"]["backend"] == "local"
        assert task["reply"]["artifact_path"] == str(reply_audio_path)

        status, audit_payload = _request_json(
            f"{base_url}/audit?{urlencode({'limit': 1})}",
            token=token,
        )
        assert status == 200
        assert len(audit_payload["tasks"]) == 1

        status, memory_note = _request_json(
            f"{base_url}/memory/note",
            method="POST",
            token=token,
            payload={"text": "Prefer visible browser mode."},
        )
        assert status == 200
        assert memory_note["memory"]["kind"] == "user_note"
        memory_id = str(memory_note["memory"]["memory_id"])

        status, memory_list = _request_json(
            f"{base_url}/memory?{urlencode({'limit': 5})}",
            token=token,
        )
        assert status == 200
        assert len(memory_list["memory"]) >= 2

        status, delete_payload = _request_json(
            f"{base_url}/memory/delete",
            method="POST",
            token=token,
            payload={"memory_id": memory_id},
        )
        assert status == 200
        assert delete_payload["deleted"] is True

        status, browser_payload = _request_json(f"{base_url}/browser/state", token=token)
        assert status == 200
        assert "Last browser activity" in browser_payload["browser"]["stdout_text"]
        assert browser_payload["browser"]["state"]["url"] == "https://example.com"

        status, screen_payload = _request_json(f"{base_url}/screen/state", token=token)
        assert status == 200
        assert "Last desktop capture" in screen_payload["screen"]["stdout_text"]
        assert screen_payload["screen"]["state"]["artifact_path"] == str(desktop_path)

        shot_status, shot_body, shot_content_type = _request_bytes(
            f"{base_url}/browser/last-screenshot",
            token=token,
        )
        assert shot_status == 200
        assert shot_content_type == "image/png"
        assert shot_body == b"fakepng"

        screen_status, screen_body, screen_content_type = _request_bytes(
            f"{base_url}/screen/latest-artifact",
            token=token,
        )
        assert screen_status == 200
        assert screen_content_type == "image/png"
        assert screen_body == b"fakescreen"

        live_status, live_body, live_content_type = _request_bytes(
            f"{base_url}/screen/live.jpg",
            token=token,
        )
        assert live_status == 200
        assert live_content_type == "image/jpeg"
        assert live_body == b"livejpeg"

        voice_status, voice_payload = _request_json(
            f"{base_url}/voice/task?backend=auto&auto_approve=true",
            method="POST",
            token=token,
            payload=None,
        )
        assert voice_status == 400

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "audio/wav",
        }
        request = Request(
            f"{base_url}/voice/task?backend=auto&auto_approve=true",
            data=b"fakewav",
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            voice_ok = json.loads(response.read().decode("utf-8"))
        assert voice_ok["ok"] is True
        assert voice_ok["transcript"] == "take a screenshot"

        reply_status, reply_body, reply_content_type = _request_bytes(
            f"{base_url}/reply/latest-audio",
            token=token,
        )
        assert reply_status == 200
        assert reply_content_type == "audio/x-wav"
        assert reply_body == b"fakewavreply"
    finally:
        server.shutdown()
