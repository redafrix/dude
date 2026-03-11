from __future__ import annotations

from types import SimpleNamespace

from dude.telegram_bot import TelegramBotService


class _FakeClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.audio: list[tuple[int, str, str | None]] = []
        self.documents: list[tuple[int, str, str | None]] = []
        self.file_bytes = (b"voice", "audio/wav")
        self.updates: list[dict] = []

    def get_updates(self, *, offset: int | None, timeout_seconds: int) -> list[dict]:
        del offset, timeout_seconds
        updates, self.updates = self.updates, []
        return updates

    def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    def send_audio(self, chat_id: int, audio_path, caption: str | None = None) -> None:
        self.audio.append((chat_id, str(audio_path), caption))

    def send_document(self, chat_id: int, document_path, caption: str | None = None) -> None:
        self.documents.append((chat_id, str(document_path), caption))

    def get_file_bytes(self, file_id: str) -> tuple[bytes, str]:
        assert file_id == "voice-file-1"
        return self.file_bytes


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.screen = SimpleNamespace(
            get_state=lambda: {"artifact_path": "/tmp/desktop.png"},
        )
        self.browser = SimpleNamespace(
            get_state=lambda: {"screenshot_path": "/tmp/browser.png"},
        )

    def run_task(self, request) -> SimpleNamespace:
        self.requests.append(request.text)
        return SimpleNamespace(
            output_text="Task completed from telegram.",
            error_text="",
            status="completed",
            route_reason="screen_capture",
        )

    def voice_response_for(self, task) -> str:
        return task.output_text


class _FakeVoiceProcessor:
    def process_audio_task(
        self,
        audio_bytes: bytes,
        *,
        content_type: str,
        backend,
        auto_approve: bool,
    ):
        del audio_bytes, content_type, backend, auto_approve
        return {
            "transcript": "take a screenshot",
            "task": {
                "output_text": "Captured a desktop screenshot.",
                "error_text": "",
            },
        }


class _FakeReplyAudio:
    def __init__(self, path: str = "/tmp/reply.wav") -> None:
        self.path = path
        self.texts: list[str] = []

    def synthesize_reply(self, text: str) -> dict[str, object]:
        self.texts.append(text)
        return {"artifact_path": self.path}


def _service() -> tuple[TelegramBotService, _FakeClient, _FakeReplyAudio, _FakeOrchestrator]:
    client = _FakeClient()
    reply_audio = _FakeReplyAudio()
    orchestrator = _FakeOrchestrator()
    telegram_cfg = SimpleNamespace(
        allowed_chat_ids=[42],
        poll_timeout_seconds=1,
        voice_replies=True,
    )
    service = TelegramBotService(
        config=SimpleNamespace(telegram=telegram_cfg),
        logger=SimpleNamespace(),
        orchestrator=orchestrator,
        voice_processor=_FakeVoiceProcessor(),
        reply_audio=reply_audio,
        client=client,
    )
    return service, client, reply_audio, orchestrator


def test_telegram_service_handles_text_message() -> None:
    service, client, reply_audio, orchestrator = _service()

    service.handle_update(
        {
            "update_id": 1,
            "message": {
                "chat": {"id": 42},
                "text": "take a screenshot",
            },
        }
    )

    assert orchestrator.requests == ["take a screenshot"]
    assert client.messages == [(42, "Task completed from telegram.")]
    assert reply_audio.texts == ["Task completed from telegram."]
    assert client.audio[0][0] == 42
    assert client.documents == []


def test_telegram_service_handles_voice_message() -> None:
    service, client, reply_audio, _ = _service()

    service.handle_update(
        {
            "update_id": 2,
            "message": {
                "chat": {"id": 42},
                "voice": {"file_id": "voice-file-1"},
            },
        }
    )

    assert "take a screenshot" in client.messages[0][1]
    assert "Captured a desktop screenshot." in client.messages[0][1]
    assert reply_audio.texts == ["Captured a desktop screenshot."]
    assert client.audio[0][0] == 42
    assert client.documents == []


def test_telegram_service_rejects_unauthorized_chat() -> None:
    service, client, _, orchestrator = _service()

    service.handle_update(
        {
            "update_id": 3,
            "message": {
                "chat": {"id": 999},
                "text": "pwd",
            },
        }
    )

    assert orchestrator.requests == []
    assert client.messages == [(999, "This chat is not authorized for Dude.")]


def test_telegram_service_sends_artifact_when_file_exists(tmp_path) -> None:
    service, client, _, orchestrator = _service()
    artifact = tmp_path / "desktop.png"
    artifact.write_bytes(b"png")
    orchestrator.screen = SimpleNamespace(get_state=lambda: {"artifact_path": str(artifact)})

    service.handle_update(
        {
            "update_id": 4,
            "message": {
                "chat": {"id": 42},
                "text": "take a screenshot",
            },
        }
    )

    assert client.documents == [(42, str(artifact), "Dude screen artifact")]
