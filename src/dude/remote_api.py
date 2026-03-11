from __future__ import annotations

import json
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dude.config import DudeConfig
from dude.logging import log_event
from dude.orchestrator import BackendKind, Orchestrator, TaskRequest
from dude.remote_voice import RemoteVoiceProcessor
from dude.reply_audio import ReplyAudioController
from dude.webapp import (
    render_manifest,
    render_remote_app_html,
    render_service_worker,
)


class RemoteApiServer:
    def __init__(
        self,
        config: DudeConfig,
        logger,
        *,
        orchestrator: Orchestrator | None = None,
        voice_processor: RemoteVoiceProcessor | None = None,
        reply_audio: ReplyAudioController | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.orchestrator = orchestrator or Orchestrator(config, logger)
        self.voice_processor = voice_processor or RemoteVoiceProcessor(
            config,
            logger,
            self.orchestrator,
        )
        self.reply_audio = reply_audio or ReplyAudioController(config, logger)
        self._auth_token: str | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._ready_event = threading.Event()

    @property
    def token_path(self) -> Path:
        return self.config.remote.auth_token_path or (
            self.config.runtime.state_dir / "remote-api.token"
        )

    @property
    def server_address(self) -> tuple[str, int]:
        if self._httpd is None:
            return (self.config.remote.bind_host, self.config.remote.port)
        host, port = self._httpd.server_address
        return str(host), int(port)

    def ensure_auth_token(self) -> str:
        if self._auth_token is not None:
            return self._auth_token

        configured = self.config.remote.auth_token
        token_path = self.token_path
        token_path.parent.mkdir(parents=True, exist_ok=True)
        if configured:
            token = configured.strip()
        elif token_path.exists():
            token = token_path.read_text(encoding="utf-8").strip()
        else:
            token = secrets.token_urlsafe(32)
            token_path.write_text(token, encoding="utf-8")
            os.chmod(token_path, 0o600)

        self._auth_token = token
        return token

    def start_in_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self.serve_forever,
            name="dude-remote-api",
            daemon=True,
        )
        self._thread.start()
        self._ready_event.wait(timeout=5)

    def serve_forever(self) -> None:
        self.config.runtime.state_dir.mkdir(parents=True, exist_ok=True)
        token = self.ensure_auth_token()
        del token
        server = ThreadingHTTPServer(
            (self.config.remote.bind_host, self.config.remote.port),
            self._build_handler(),
        )
        server.daemon_threads = True
        self._httpd = server
        self._ready_event.set()
        bind_host, bind_port = self.server_address
        log_event(
            self.logger,
            "remote_api_started",
            bind_host=bind_host,
            port=bind_port,
            auth_token_path=str(self.token_path),
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
            self._httpd = None
            log_event(self.logger, "remote_api_stopped")

    def shutdown(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parent._handle(self, "GET")

            def do_POST(self) -> None:  # noqa: N802
                parent._handle(self, "POST")

            def log_message(self, format: str, *args: object) -> None:
                del format, args
                return None

        return Handler

    def _handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._write_json(handler, HTTPStatus.OK, {"ok": True, "service": "dude-remote-api"})
            return
        if parsed.path in {"/", "/index.html"}:
            self._write_text(handler, HTTPStatus.OK, render_remote_app_html(), "text/html")
            return
        if parsed.path == "/manifest.webmanifest":
            self._write_text(
                handler,
                HTTPStatus.OK,
                render_manifest(),
                "application/manifest+json",
            )
            return
        if parsed.path == "/service-worker.js":
            self._write_text(
                handler,
                HTTPStatus.OK,
                render_service_worker(),
                "application/javascript",
            )
            return

        if not self._is_authorized(handler.headers.get("Authorization")):
            self._write_json(
                handler,
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": "Unauthorized"},
            )
            return

        try:
            binary = self._dispatch_binary(parsed.path, method, query)
        except FileNotFoundError as exc:
            self._write_json(
                handler,
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": str(exc)},
            )
            return
        except RuntimeError as exc:
            self._write_json(
                handler,
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": str(exc)},
            )
            return
        if binary is not None:
            payload, content_type = binary
            self._write_bytes(handler, HTTPStatus.OK, payload, content_type)
            return

        try:
            if method == "POST" and parsed.path == "/voice/task":
                payload = self._dispatch_voice_task(handler, query)
                if self._voice_reply_requested(query):
                    payload["reply"] = self._synthesize_reply_from_payload(payload)
            else:
                body = self._read_json_body(handler) if method == "POST" else {}
                payload = self._dispatch(parsed.path, method, query, body)
                if method == "POST" and self._voice_reply_requested(query, body):
                    payload["reply"] = self._synthesize_reply_from_payload(payload)
        except ValueError as exc:
            self._write_json(
                handler,
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": str(exc)},
            )
            return
        except RuntimeError as exc:
            self._write_json(
                handler,
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": str(exc)},
            )
            return
        except Exception as exc:
            self._write_json(
                handler,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": str(exc)},
            )
            return

        self._write_json(handler, HTTPStatus.OK, {"ok": True, **payload})

    def _dispatch(
        self,
        path: str,
        method: str,
        query: dict[str, list[str]],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        if method == "GET" and path == "/audit":
            limit = int(query.get("limit", ["20"])[0])
            return {"tasks": self.orchestrator.list_recent_tasks(limit)}

        if method == "GET" and path == "/memory":
            limit = int(query.get("limit", ["20"])[0])
            return {"memory": self.orchestrator.list_memory(limit)}

        if method == "GET" and path == "/browser/state":
            result = self.orchestrator.browser.show_state()
            state = self.orchestrator.browser.get_state()
            return {
                "browser": {
                    "executor": result.executor,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout_text": result.stdout_text,
                    "stderr_text": result.stderr_text,
                    "state": state,
                }
            }

        if method == "GET" and path == "/screen/state":
            result = self.orchestrator.screen.show_state()
            state = self.orchestrator.screen.get_state()
            return {
                "screen": {
                    "executor": result.executor,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout_text": result.stdout_text,
                    "stderr_text": result.stderr_text,
                    "state": state,
                }
            }

        if method == "POST" and path == "/task":
            text = str(body.get("text", "")).strip()
            if not text:
                raise ValueError("Task text is required.")
            backend = BackendKind(str(body.get("backend", "auto")))
            auto_approve = bool(body.get("auto_approve", False))
            result = self.orchestrator.run_task(
                TaskRequest(
                    text=text,
                    preferred_backend=backend,
                    auto_approve=auto_approve,
                )
            )
            return {"task": result.to_dict()}

        if method == "POST" and path == "/approve":
            task_id = body.get("task_id")
            latest = bool(body.get("latest", False))
            result = self.orchestrator.approve_task(
                str(task_id) if task_id is not None else None,
                latest=latest,
            )
            return {"task": result.to_dict()}

        if method == "POST" and path == "/memory/note":
            text = str(body.get("text", "")).strip()
            if not text:
                raise ValueError("Memory note text is required.")
            entry = self.orchestrator.create_memory_note(text)
            return {"memory": entry}

        if method == "POST" and path == "/memory/delete":
            memory_id = str(body.get("memory_id", "")).strip()
            if not memory_id:
                raise ValueError("memory_id is required.")
            return {
                "deleted": self.orchestrator.delete_memory(memory_id),
                "memory_id": memory_id,
            }

        if method == "POST" and path == "/memory/clear":
            return {"deleted_count": self.orchestrator.clear_memory()}

        raise ValueError(f"Unsupported route: {method} {path}")

    def _dispatch_voice_task(
        self,
        handler: BaseHTTPRequestHandler,
        query: dict[str, list[str]],
    ) -> dict[str, Any]:
        audio_bytes = self._read_body_bytes(handler)
        backend_name = query.get("backend", ["auto"])[0]
        auto_approve_raw = query.get("auto_approve", ["false"])[0]
        auto_approve = auto_approve_raw.lower() in {"1", "true", "yes", "on"}
        content_type = handler.headers.get("Content-Type", "application/octet-stream")
        return self.voice_processor.process_audio_task(
            audio_bytes,
            content_type=content_type,
            backend=BackendKind(backend_name),
            auto_approve=auto_approve,
        )

    def _voice_reply_requested(
        self,
        query: dict[str, list[str]],
        body: dict[str, Any] | None = None,
    ) -> bool:
        query_value = query.get("voice_reply", ["false"])[0].lower()
        if query_value in {"1", "true", "yes", "on"}:
            return True
        if body is not None:
            return bool(body.get("voice_reply", False))
        return False

    def _synthesize_reply_from_payload(self, payload: dict[str, Any]) -> dict[str, object]:
        task_payload = payload.get("task")
        if not isinstance(task_payload, dict):
            raise ValueError("No task result is available for voice reply synthesis.")
        task_text = str(task_payload.get("output_text", "")).strip()
        if not task_text:
            task_text = str(task_payload.get("error_text", "")).strip()
        if not task_text:
            task_text = "Task completed."
        return self.reply_audio.synthesize_reply(task_text)

    def _dispatch_binary(
        self,
        path: str,
        method: str,
        query: dict[str, list[str]],
    ) -> tuple[bytes, str] | None:
        del query
        if method == "GET" and path == "/browser/last-screenshot":
            state = self.orchestrator.browser.get_state()
            if state is None or not state.get("screenshot_path"):
                raise FileNotFoundError("No browser screenshot is available yet.")
            screenshot_path = Path(str(state["screenshot_path"]))
            if not screenshot_path.exists():
                raise FileNotFoundError(f"Browser screenshot is missing: {screenshot_path}")
            content_type = guess_type(screenshot_path.name)[0] or "application/octet-stream"
            return screenshot_path.read_bytes(), content_type
        if method == "GET" and path == "/screen/latest-artifact":
            state = self.orchestrator.screen.get_state()
            if state is None or not state.get("artifact_path"):
                raise FileNotFoundError("No desktop capture artifact is available yet.")
            artifact_path = Path(str(state["artifact_path"]))
            if not artifact_path.exists():
                raise FileNotFoundError(f"Desktop capture artifact is missing: {artifact_path}")
            content_type = guess_type(artifact_path.name)[0] or "application/octet-stream"
            return artifact_path.read_bytes(), content_type
        if method == "GET" and path in {"/screen/live.jpg", "/screen/live.png"}:
            image_format = "png" if path.endswith(".png") else "jpeg"
            return self.orchestrator.screen.capture_screenshot_bytes(
                Path.cwd(),
                image_format=image_format,
            )
        if method == "GET" and path == "/reply/latest-audio":
            state = self.reply_audio.get_state()
            if state is None or not state.get("artifact_path"):
                raise FileNotFoundError("No reply audio is available yet.")
            artifact_path = Path(str(state["artifact_path"]))
            if not artifact_path.exists():
                raise FileNotFoundError(f"Reply audio artifact is missing: {artifact_path}")
            content_type = guess_type(artifact_path.name)[0] or "audio/wav"
            return artifact_path.read_bytes(), content_type
        return None

    def _is_authorized(self, header: str | None) -> bool:
        expected = self.ensure_auth_token()
        if not header or not header.startswith("Bearer "):
            return False
        token = header.removeprefix("Bearer ").strip()
        return secrets.compare_digest(token, expected)

    def _read_json_body(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = handler.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object.")
        return parsed

    def _read_body_bytes(self, handler: BaseHTTPRequestHandler) -> bytes:
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0:
            return b""
        return handler.rfile.read(length)

    def _write_json(
        self,
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        payload: dict[str, Any],
    ) -> None:
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        handler.send_response(int(status))
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(encoded)))
        handler.end_headers()
        handler.wfile.write(encoded)

    def _write_text(
        self,
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        payload: str,
        content_type: str,
    ) -> None:
        self._write_bytes(handler, status, payload.encode("utf-8"), content_type)

    def _write_bytes(
        self,
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        payload: bytes,
        content_type: str,
    ) -> None:
        handler.send_response(int(status))
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
