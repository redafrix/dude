from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

from dude.audit import AuditStore
from dude.browser import BrowserToolResult
from dude.config import load_config
from dude.orchestrator import (
    ActionResult,
    ApprovalClass,
    BackendKind,
    Orchestrator,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from dude.screen import ScreenCaptureResult


class _FakeRunner:
    def __init__(self, executor: str, stdout_text: str) -> None:
        self.executor = executor
        self.stdout_text = stdout_text
        self.prompts: list[str] = []
        self.image_paths: list[list[Path]] = []

    def run(
        self,
        prompt: str,
        *,
        working_dir: Path,
        timeout_seconds: int,
        approval_class: ApprovalClass = ApprovalClass.USER_CONFIRM,
        request_text: str = "",
        image_paths: list[Path] | None = None,
    ) -> ActionResult:
        self.prompts.append(prompt)
        self.image_paths.append(list(image_paths or []))
        del working_dir, timeout_seconds, approval_class, request_text
        return ActionResult(
            executor=self.executor,
            command=[self.executor, "mock"],
            exit_code=0,
            stdout_text=self.stdout_text,
            stderr_text="",
        )


class _FakeBrowserController:
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
            "url": "https://example.com",
            "screenshot_path": "/tmp/browser.png",
        }


class _FakeScreenController:
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
            "artifact_path": "/tmp/desktop.png",
            "resolution": "1920x1200",
        }


def test_orchestrator_runs_safe_local_pwd(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    orchestrator = Orchestrator(config, logging.getLogger("test"))

    result = orchestrator.run_task(
        TaskRequest(
            text="what is the current directory",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.SAFE_LOCAL
    assert str(tmp_path) in result.output_text


def test_orchestrator_requires_approval_for_network_request(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    orchestrator = Orchestrator(config, logging.getLogger("test"))

    result = orchestrator.run_task(
        TaskRequest(
            text="download discord for me",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
        )
    )

    assert result.status == TaskStatus.APPROVAL_REQUIRED
    assert result.backend == BackendKind.CODEX
    assert result.approval_class == ApprovalClass.NETWORK
    assert result.requires_approval is True


def test_orchestrator_records_backend_run_in_audit_store(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "done"),
        gemini_runner=_FakeRunner("gemini", "planned"),
    )

    result = orchestrator.run_task(
        TaskRequest(
            text="refactor this module",
            preferred_backend=BackendKind.CODEX,
            auto_approve=True,
            working_dir=tmp_path,
        )
    )
    tasks = orchestrator.list_recent_tasks(limit=5)

    assert result.status == TaskStatus.COMPLETED
    assert result.backend == BackendKind.CODEX
    assert tasks[0]["task_id"] == result.task_id
    assert tasks[0]["actions"][0]["executor"] == "codex"


def test_orchestrator_can_approve_latest_pending_task(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "download complete"),
        gemini_runner=_FakeRunner("gemini", "planned"),
    )

    pending = orchestrator.run_task(
        TaskRequest(
            text="download discord for me",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )
    approved = orchestrator.approve_task(latest=True)
    tasks = orchestrator.list_recent_tasks(limit=5)

    assert pending.status == TaskStatus.APPROVAL_REQUIRED
    assert approved.status == TaskStatus.COMPLETED
    assert approved.task_id == pending.task_id
    assert tasks[0]["task_id"] == pending.task_id
    assert tasks[0]["status"] == TaskStatus.COMPLETED.value


def test_orchestrator_routes_browser_requests_to_local_browser_controller(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "done"),
        gemini_runner=_FakeRunner("gemini", "planned"),
        browser_controller=_FakeBrowserController(),
        screen_controller=_FakeScreenController(),
    )

    result = orchestrator.run_task(
        TaskRequest(
            text="open browser https://example.com",
            preferred_backend=BackendKind.AUTO,
            auto_approve=True,
            working_dir=tmp_path,
        )
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.NETWORK
    assert "saved a screenshot" in result.output_text


def test_orchestrator_can_report_browser_state_without_approval(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "done"),
        gemini_runner=_FakeRunner("gemini", "planned"),
        browser_controller=_FakeBrowserController(),
        screen_controller=_FakeScreenController(),
    )

    result = orchestrator.run_task(
        TaskRequest(
            text="show me what you're doing",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.SAFE_LOCAL
    assert "Last browser activity" in result.output_text
    assert "Last desktop capture" in result.output_text


def test_orchestrator_routes_screen_capture_requests(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "done"),
        gemini_runner=_FakeRunner("gemini", "planned"),
        browser_controller=_FakeBrowserController(),
        screen_controller=_FakeScreenController(),
    )

    result = orchestrator.run_task(
        TaskRequest(
            text="take a screenshot",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.SAFE_LOCAL
    assert "desktop screenshot" in result.output_text


def test_orchestrator_records_task_memory_entries(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "done"),
        gemini_runner=_FakeRunner("gemini", "planned"),
    )

    result = orchestrator.run_task(
        TaskRequest(
            text="what is the current directory",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )
    memories = orchestrator.list_memory(limit=5)

    assert result.status == TaskStatus.COMPLETED
    assert memories
    assert memories[0]["kind"] == "task_summary"
    assert "what is the current directory" in str(memories[0]["summary_text"])


def test_orchestrator_can_store_and_list_memory_note(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=_FakeRunner("codex", "done"),
        gemini_runner=_FakeRunner("gemini", "planned"),
        browser_controller=_FakeBrowserController(),
        screen_controller=_FakeScreenController(),
    )

    note_result = orchestrator.run_task(
        TaskRequest(
            text="remember that I prefer visible browser mode",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )
    list_result = orchestrator.run_task(
        TaskRequest(
            text="show memory",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert note_result.status == TaskStatus.COMPLETED
    assert "Saved memory note" in note_result.output_text
    assert list_result.status == TaskStatus.COMPLETED
    assert "visible browser mode" in list_result.output_text


def test_orchestrator_includes_memory_context_in_backend_prompt(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    audit = AuditStore(config.runtime.audit_db_path)
    codex_runner = _FakeRunner("codex", "done")
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        audit_store=audit,
        codex_runner=codex_runner,
        gemini_runner=_FakeRunner("gemini", "planned"),
        browser_controller=_FakeBrowserController(),
        screen_controller=_FakeScreenController(),
    )

    orchestrator.create_memory_note("Prefer visible browser mode.")
    orchestrator.run_task(
        TaskRequest(
            text="plan the next browser step",
            preferred_backend=BackendKind.CODEX,
            auto_approve=True,
            working_dir=tmp_path,
        )
    )

    assert codex_runner.prompts
    assert "Relevant local memory:" in codex_runner.prompts[0]
    assert "Prefer visible browser mode." in codex_runner.prompts[0]
    assert "Current local context:" in codex_runner.prompts[0]
    assert "https://example.com" in codex_runner.prompts[0]
    assert "/tmp/desktop.png" in codex_runner.prompts[0]


def test_orchestrator_voice_response_uses_persona_for_approval(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    config.persona.mode = "narcissistic"
    orchestrator = Orchestrator(config, logging.getLogger("test"))

    result = TaskResult(
        task_id="task-1",
        status=TaskStatus.APPROVAL_REQUIRED,
        backend=BackendKind.CODEX,
        approval_class=ApprovalClass.NETWORK,
        route_reason="network_request",
        request_text="download discord",
        requires_approval=True,
    )

    response = orchestrator.voice_response_for(result)

    assert "Reda" in response
    assert "network" in response


def test_orchestrator_routes_screen_vision_request_to_codex(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    screenshot_path = tmp_path / "desktop.png"
    screenshot_path.write_bytes(b"png")

    class _VisionScreenController(_FakeScreenController):
        def get_state(self) -> dict[str, object]:
            return {
                "updated_at": "now",
                "mode": "screenshot",
                "artifact_path": str(screenshot_path),
                "resolution": "1920x1200",
            }

    codex_runner = _FakeRunner("codex", "I can see the desktop.")
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        codex_runner=codex_runner,
        screen_controller=_VisionScreenController(),
    )

    pending = orchestrator.run_task(
        TaskRequest(
            text="what is on my screen right now",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert pending.status == TaskStatus.APPROVAL_REQUIRED
    result = orchestrator.approve_task(latest=True)
    assert result.status == TaskStatus.COMPLETED
    assert codex_runner.image_paths[-1] == [screenshot_path.resolve()]


def test_orchestrator_routes_page_vision_request_to_codex_with_browser_screenshot(
    tmp_path: Path,
) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    browser_path = tmp_path / "browser.png"
    browser_path.write_bytes(b"png")

    class _VisionBrowserController(_FakeBrowserController):
        def get_state(self) -> dict[str, object]:
            return {
                "updated_at": "now",
                "mode": "headless",
                "url": "https://example.com",
                "screenshot_path": str(browser_path),
            }

    codex_runner = _FakeRunner("codex", "The page is example domain.")
    orchestrator = Orchestrator(
        config,
        logging.getLogger("test"),
        codex_runner=codex_runner,
        browser_controller=_VisionBrowserController(),
    )

    pending = orchestrator.run_task(
        TaskRequest(
            text="what is on the page in the browser",
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert pending.status == TaskStatus.APPROVAL_REQUIRED
    result = orchestrator.approve_task(latest=True)
    assert result.status == TaskStatus.COMPLETED
    assert codex_runner.image_paths[-1] == [browser_path.resolve()]


def test_orchestrator_can_launch_downloads_folder(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    orchestrator = Orchestrator(config, logging.getLogger("test"))

    class _FakeProcess:
        pid = 4242

    def _which(exe: str) -> str | None:
        return "/usr/bin/xdg-open" if exe == "xdg-open" else None

    with (
        patch("dude.orchestrator.shutil.which", side_effect=_which),
        patch("dude.orchestrator.subprocess.Popen", return_value=_FakeProcess()),
    ):
        result = orchestrator.run_task(
            TaskRequest(
                text="open downloads",
                preferred_backend=BackendKind.AUTO,
                auto_approve=False,
                working_dir=tmp_path,
            )
        )

    assert result.status == TaskStatus.COMPLETED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.SAFE_LOCAL
    assert "pid 4242" in result.output_text


def test_orchestrator_routes_file_creation_to_approval(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    orchestrator = Orchestrator(config, logging.getLogger("test"))

    result = orchestrator.run_task(
        TaskRequest(
            text='create file "notes.txt"',
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert result.status == TaskStatus.APPROVAL_REQUIRED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.USER_CONFIRM


def test_orchestrator_routes_file_delete_to_destructive_approval(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    orchestrator = Orchestrator(config, logging.getLogger("test"))

    result = orchestrator.run_task(
        TaskRequest(
            text='delete file "notes.txt"',
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert result.status == TaskStatus.APPROVAL_REQUIRED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.DESTRUCTIVE


def test_orchestrator_routes_repo_text_search_to_safe_local(tmp_path: Path) -> None:
    config = load_config(Path("configs/default.yaml"))
    config.runtime.audit_db_path = tmp_path / "dude.db"
    (tmp_path / "notes.txt").write_text("todo: ship dude\n", encoding="utf-8")
    orchestrator = Orchestrator(config, logging.getLogger("test"))

    result = orchestrator.run_task(
        TaskRequest(
            text='search for "ship dude" in files',
            preferred_backend=BackendKind.AUTO,
            auto_approve=False,
            working_dir=tmp_path,
        )
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.backend == BackendKind.LOCAL
    assert result.approval_class == ApprovalClass.SAFE_LOCAL
    assert "notes.txt" in result.output_text
