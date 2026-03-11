from __future__ import annotations

import json
import mimetypes
import os
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dude.orchestrator import BackendKind, Orchestrator, TaskRequest
from dude.remote_voice import RemoteVoiceProcessor
from dude.reply_audio import ReplyAudioController


class TelegramApiClient(Protocol):
    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]: ...
    def send_message(self, chat_id: int, text: str) -> None: ...
    def send_audio(self, chat_id: int, audio_path: Path, caption: str | None = None) -> None: ...
    def send_document(
        self,
        chat_id: int,
        document_path: Path,
        caption: str | None = None,
    ) -> None: ...
    def get_file_bytes(self, file_id: str) -> tuple[bytes, str]: ...


class TelegramHttpClient:
    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{bot_token}"

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        query = {
            "timeout": timeout_seconds,
        }
        if offset is not None:
            query["offset"] = offset
        url = f"{self.base_url}/getUpdates?{urllib.parse.urlencode(query)}"
        payload = self._json_request(url)
        return list(payload.get("result", []))

    def send_message(self, chat_id: int, text: str) -> None:
        url = f"{self.base_url}/sendMessage"
        body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        self._json_request(url, body=body, headers={"Content-Type": "application/json"})

    def send_audio(self, chat_id: int, audio_path: Path, caption: str | None = None) -> None:
        self._send_multipart_file(
            f"{self.base_url}/sendAudio",
            chat_id=chat_id,
            field_name="audio",
            file_path=audio_path,
            caption=caption,
        )

    def send_document(self, chat_id: int, document_path: Path, caption: str | None = None) -> None:
        self._send_multipart_file(
            f"{self.base_url}/sendDocument",
            chat_id=chat_id,
            field_name="document",
            file_path=document_path,
            caption=caption,
        )

    def _send_multipart_file(
        self,
        url: str,
        *,
        chat_id: int,
        field_name: str,
        file_path: Path,
        caption: str | None,
    ) -> None:
        boundary = f"dude-{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        parts: list[bytes] = []
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="chat_id"\r\n\r\n',
                str(chat_id).encode(),
                b"\r\n",
            ]
        )
        if caption:
            parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    b'Content-Disposition: form-data; name="caption"\r\n\r\n',
                    caption.encode("utf-8"),
                    b"\r\n",
                ]
            )
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    "Content-Disposition: form-data; "
                    f'name="{field_name}"; filename="{file_path.name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                file_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        body = b"".join(parts)
        self._json_request(
            url,
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def get_file_bytes(self, file_id: str) -> tuple[bytes, str]:
        payload = self._json_request(
            f"{self.base_url}/getFile?file_id={urllib.parse.quote(file_id)}"
        )
        result = payload.get("result", {})
        file_path = str(result.get("file_path", ""))
        if not file_path:
            raise RuntimeError("Telegram getFile did not return a file path.")
        url = f"{self.file_base_url}/{file_path}"
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read(), response.headers.get_content_type()

    def _json_request(
        self,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers or {},
            method="POST" if body is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok", False):
            raise RuntimeError(payload.get("description", "Telegram API request failed."))
        return payload


@dataclass(slots=True)
class TelegramBotService:
    config: Any
    logger: Any
    orchestrator: Orchestrator
    voice_processor: RemoteVoiceProcessor
    reply_audio: ReplyAudioController
    client: TelegramApiClient
    next_update_offset: int | None = None

    def poll_once(self) -> int:
        updates = self.client.get_updates(
            offset=self.next_update_offset,
            timeout_seconds=self.config.telegram.poll_timeout_seconds,
        )
        handled = 0
        for update in updates:
            handled += 1
            self.next_update_offset = int(update["update_id"]) + 1
            self.handle_update(update)
        return handled

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat", {})
        chat_id = int(chat.get("id", 0))
        if (
            self.config.telegram.allowed_chat_ids
            and chat_id not in self.config.telegram.allowed_chat_ids
        ):
            self.client.send_message(chat_id, "This chat is not authorized for Dude.")
            return

        text = message.get("text")
        if isinstance(text, str) and text.strip():
            self._handle_text(chat_id, text.strip())
            return

        voice = message.get("voice")
        audio = message.get("audio")
        media = voice if isinstance(voice, dict) else audio if isinstance(audio, dict) else None
        if media is not None and media.get("file_id"):
            self._handle_voice(chat_id, str(media["file_id"]))

    def _handle_text(self, chat_id: int, text: str) -> None:
        if text in {"/start", "/help"}:
            self.client.send_message(
                chat_id,
                "Send a text command or a voice note. Example: take a screenshot",
            )
            return
        task = self.orchestrator.run_task(
            TaskRequest(
                text=text,
                preferred_backend=BackendKind.AUTO,
                auto_approve=False,
            )
        )
        reply_text = self.orchestrator.voice_response_for(task)
        self.client.send_message(chat_id, reply_text)
        self._send_visual_artifact(chat_id, getattr(task, "route_reason", ""))
        if self.config.telegram.voice_replies:
            self._send_reply_audio(chat_id, reply_text)

    def _handle_voice(self, chat_id: int, file_id: str) -> None:
        audio_bytes, content_type = self.client.get_file_bytes(file_id)
        payload = self.voice_processor.process_audio_task(
            audio_bytes,
            content_type=content_type,
            backend=BackendKind.AUTO,
            auto_approve=False,
        )
        transcript = str(payload.get("transcript", "")).strip()
        task_payload = payload.get("task", {})
        task_output = ""
        if isinstance(task_payload, dict):
            task_output = str(task_payload.get("output_text", "")).strip()
            if not task_output:
                task_output = str(task_payload.get("error_text", "")).strip()
        reply_text = f"{transcript}\n\n{task_output}".strip() if transcript else task_output
        if not reply_text:
            reply_text = "Voice note processed."
        self.client.send_message(chat_id, reply_text)
        route_reason = ""
        if isinstance(task_payload, dict):
            route_reason = str(task_payload.get("route_reason", "")).strip()
        self._send_visual_artifact(chat_id, route_reason)
        if self.config.telegram.voice_replies:
            self._send_reply_audio(chat_id, task_output or transcript or "Done.")

    def _send_reply_audio(self, chat_id: int, text: str) -> None:
        state = self.reply_audio.synthesize_reply(text)
        self.client.send_audio(chat_id, Path(str(state["artifact_path"])), caption="Dude reply")

    def _send_visual_artifact(self, chat_id: int, route_reason: str) -> None:
        if route_reason not in {
            "screen_capture",
            "screen_state",
            "activity_state",
            "browser_command",
        }:
            return
        candidates: list[tuple[Path | None, str]] = []
        if route_reason in {"screen_capture", "screen_state", "activity_state"}:
            screen_state = self.orchestrator.screen.get_state()
            candidates.append(
                (
                    Path(str(screen_state.get("artifact_path")))
                    if isinstance(screen_state, dict) and screen_state.get("artifact_path")
                    else None,
                    "Dude screen artifact",
                )
            )
        if route_reason in {"browser_command", "activity_state"}:
            browser_state = self.orchestrator.browser.get_state()
            candidates.append(
                (
                    Path(str(browser_state.get("screenshot_path")))
                    if isinstance(browser_state, dict) and browser_state.get("screenshot_path")
                    else None,
                    "Dude browser artifact",
                )
            )
        for artifact_path, caption in candidates:
            if artifact_path is None or not artifact_path.exists():
                continue
            self.client.send_document(chat_id, artifact_path, caption=caption)


def build_telegram_service(config, logger) -> TelegramBotService:
    bot_token = config.telegram.bot_token or os.environ.get("DUDE_TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("telegram.bot_token is required to start the Telegram bot.")
    orchestrator = Orchestrator(config, logger)
    voice_processor = RemoteVoiceProcessor(config, logger, orchestrator)
    reply_audio = ReplyAudioController(config, logger)
    client = TelegramHttpClient(bot_token)
    return TelegramBotService(
        config=config,
        logger=logger,
        orchestrator=orchestrator,
        voice_processor=voice_processor,
        reply_audio=reply_audio,
        client=client,
    )
