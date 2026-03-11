from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from dude.audit import AuditStore
from dude.browser import BrowserController
from dude.config import DudeConfig
from dude.files import FileController
from dude.logging import log_event
from dude.persona import PersonaController
from dude.screen import ScreenCaptureController


class BackendKind(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    CODEX = "codex"
    GEMINI = "gemini"


class ApprovalClass(str, Enum):
    SAFE_LOCAL = "safe_local"
    USER_CONFIRM = "user_confirm"
    SUDO = "sudo"
    DESTRUCTIVE = "destructive"
    NETWORK = "network"


class TaskStatus(str, Enum):
    COMPLETED = "completed"
    APPROVAL_REQUIRED = "approval_required"
    FAILED = "failed"


@dataclass(slots=True)
class TaskRequest:
    text: str
    preferred_backend: BackendKind = BackendKind.AUTO
    auto_approve: bool = False
    working_dir: Path | None = None


@dataclass(slots=True)
class ActionResult:
    executor: str
    command: list[str]
    exit_code: int | None
    stdout_text: str
    stderr_text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "executor": self.executor,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout_text": self.stdout_text,
            "stderr_text": self.stderr_text,
        }


@dataclass(slots=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    backend: BackendKind
    approval_class: ApprovalClass
    route_reason: str
    request_text: str
    output_text: str = ""
    error_text: str = ""
    requires_approval: bool = False
    actions: list[ActionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "backend": self.backend.value,
            "approval_class": self.approval_class.value,
            "route_reason": self.route_reason,
            "request_text": self.request_text,
            "output_text": self.output_text,
            "error_text": self.error_text,
            "requires_approval": self.requires_approval,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(slots=True)
class RouteDecision:
    backend: BackendKind
    approval_class: ApprovalClass
    route_reason: str
    local_tool: str | None = None


class BackendRunner(Protocol):
    def run(
        self,
        prompt: str,
        *,
        working_dir: Path,
        timeout_seconds: int,
    ) -> ActionResult: ...


class CodexRunner:
    def __init__(self, config: DudeConfig) -> None:
        self.config = config

    def run(
        self,
        prompt: str,
        *,
        working_dir: Path,
        timeout_seconds: int,
    ) -> ActionResult:
        with tempfile.TemporaryDirectory(prefix="dude-codex-") as tmp_dir:
            last_message_path = Path(tmp_dir) / "last-message.txt"
            command = ["codex"]
            if self.config.orchestrator.codex_model:
                command.extend(["-m", self.config.orchestrator.codex_model])
            command.extend(
                [
                    "-a",
                    "never",
                    "-s",
                    self.config.orchestrator.codex_sandbox,
                    "exec",
                    "--skip-git-repo-check",
                    "--color",
                    "never",
                    "--output-last-message",
                    str(last_message_path),
                    prompt,
                ]
            )
            completed = subprocess.run(
                command,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            output_text = (
                last_message_path.read_text(encoding="utf-8").strip()
                if last_message_path.exists()
                else completed.stdout.strip()
            )
            return ActionResult(
                executor="codex",
                command=command,
                exit_code=completed.returncode,
                stdout_text=output_text,
                stderr_text=completed.stderr.strip(),
            )


class GeminiRunner:
    def __init__(self, config: DudeConfig) -> None:
        self.config = config

    def run(
        self,
        prompt: str,
        *,
        working_dir: Path,
        timeout_seconds: int,
    ) -> ActionResult:
        command = [
            "gemini",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            "default" if self.config.orchestrator.gemini_plan_only else "yolo",
        ]
        if self.config.orchestrator.gemini_model:
            command.extend(["-m", self.config.orchestrator.gemini_model])
        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output_text = completed.stdout.strip()
        try:
            parsed = json.loads(output_text) if output_text else {}
            response_text = str(parsed.get("response", "")).strip()
        except json.JSONDecodeError:
            response_text = output_text
        return ActionResult(
            executor="gemini",
            command=command,
            exit_code=completed.returncode,
            stdout_text=response_text or output_text,
            stderr_text=completed.stderr.strip(),
        )


class Orchestrator:
    def __init__(
        self,
        config: DudeConfig,
        logger: logging.Logger,
        *,
        audit_store: AuditStore | None = None,
        codex_runner: BackendRunner | None = None,
        gemini_runner: BackendRunner | None = None,
        browser_controller: BrowserController | None = None,
        screen_controller: ScreenCaptureController | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.audit = audit_store or AuditStore(config.runtime.audit_db_path)
        self.codex_runner = codex_runner or CodexRunner(config)
        self.gemini_runner = gemini_runner or GeminiRunner(config)
        self.browser = browser_controller or BrowserController(config, logger)
        self.screen = screen_controller or ScreenCaptureController(config, logger)
        self.files = FileController()
        self.persona = PersonaController(config.persona)

    def classify_request(self, text: str, preferred_backend: BackendKind) -> RouteDecision:
        lowered = text.lower()
        forced_backend = (
            preferred_backend
            if preferred_backend != BackendKind.AUTO
            else BackendKind(self.config.orchestrator.default_backend)
        )

        memory_list_tokens = (
            "show memory",
            "show memories",
            "memory list",
            "recent memory",
            "recent memories",
            "what did you do recently",
            "what have you done recently",
            "recent tasks",
        )
        if any(token in lowered for token in memory_list_tokens):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "memory_list",
                "memory_list",
            )
        if lowered.startswith("remember ") or lowered.startswith("remember that "):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "memory_note",
                "memory_note",
            )
        if any(token in lowered for token in ("pwd", "current directory", "where am i")):
            return RouteDecision(BackendKind.LOCAL, ApprovalClass.SAFE_LOCAL, "pwd_query", "pwd")
        if any(token in lowered for token in ("read file", "show file", "open file", "cat ")):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "file_read",
                "file_read",
            )
        if any(token in lowered for token in ("find file", "locate file", "search file named")):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "file_find",
                "file_find",
            )
        if any(token in lowered for token in ("search for", "find text", "grep ")) and any(
            token in lowered for token in ("in files", "in repo", "in project")
        ):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "file_search_text",
                "file_search_text",
            )
        if any(
            token in lowered
            for token in (
                "create directory",
                "make directory",
                "create folder",
                "make folder",
                "mkdir ",
            )
        ):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.USER_CONFIRM,
                "file_mkdir",
                "file_mkdir",
            )
        if any(token in lowered for token in ("create file", "make file", "touch ")):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.USER_CONFIRM,
                "file_touch",
                "file_touch",
            )
        if any(
            token in lowered
            for token in ("copy file", "copy folder", "copy directory", "copy ")
        ):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.USER_CONFIRM,
                "file_copy",
                "file_copy",
            )
        if any(
            token in lowered
            for token in ("move file", "move folder", "move directory", "move ")
        ):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.USER_CONFIRM,
                "file_move",
                "file_move",
            )
        if any(
            token in lowered
            for token in ("delete file", "remove file", "delete folder", "remove folder")
        ):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.DESTRUCTIVE,
                "file_delete",
                "file_delete",
            )
        if any(
            token in lowered
            for token in ("list files in", "show files in", "list directory", "show directory")
        ):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "file_list_dir",
                "file_list_dir",
            )
        launch_tokens = (
            "open terminal",
            "launch terminal",
            "open file manager",
            "open files",
            "open downloads",
            "launch firefox",
            "open firefox",
            "launch chrome",
            "open chrome",
            "launch discord",
            "open discord",
        )
        if any(token in lowered for token in launch_tokens):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "launch_app",
                "launch_app",
            )
        if any(token in lowered for token in ("list files", "show files", "ls")):
            return RouteDecision(BackendKind.LOCAL, ApprovalClass.SAFE_LOCAL, "list_files", "ls")
        if "git status" in lowered:
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "git_status",
                "git_status",
            )
        activity_tokens = (
            "show me what you're doing",
            "show me what you are doing",
            "show current activity",
            "what are you doing",
            "show current browser state",
        )
        if any(token in lowered for token in activity_tokens):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "activity_state",
                "activity_state",
            )
        screen_state_tokens = (
            "screen state",
            "desktop state",
            "last screen capture",
            "last screenshot",
        )
        if any(token in lowered for token in screen_state_tokens):
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "screen_state",
                "screen_state",
            )
        package_tokens = ("sudo", "apt ", "apt-get", "dnf ", "pacman ", "install ")
        if any(token in lowered for token in package_tokens):
            return RouteDecision(
                BackendKind.CODEX if forced_backend == BackendKind.AUTO else forced_backend,
                ApprovalClass.SUDO,
                "package_management",
            )
        if any(token in lowered for token in ("delete", "remove", "rm ", "purge", "wipe")):
            return RouteDecision(
                BackendKind.CODEX if forced_backend == BackendKind.AUTO else forced_backend,
                ApprovalClass.DESTRUCTIVE,
                "destructive_request",
            )
        if any(token in lowered for token in ("download", "wget", "curl", "fetch", "clone")):
            return RouteDecision(
                BackendKind.CODEX if forced_backend == BackendKind.AUTO else forced_backend,
                ApprovalClass.NETWORK,
                "network_request",
            )
        screen_tokens = (
            "take screenshot",
            "take a screenshot",
            "capture screenshot",
            "capture the screen",
            "capture the desktop",
            "show the desktop",
            "show my screen",
            "record screen",
            "record the screen",
            "record desktop",
            "record what you're doing",
            "record what you are doing",
        )
        if any(token in lowered for token in screen_tokens):
            tool_name = (
                "screen_record"
                if "record" in lowered
                else "screen_screenshot"
            )
            return RouteDecision(
                BackendKind.LOCAL,
                ApprovalClass.SAFE_LOCAL,
                "screen_capture",
                tool_name,
            )
        browser_tokens = (
            "open browser",
            "open the browser",
            "open chrome",
            "open firefox",
            "search for",
            "search web for",
            "look up",
            "google ",
            "click on the page",
            "click in the browser",
            "click the link",
            "click the button",
            "type \"",
            "enter \"",
            "fill \"",
            "show me the page",
            "screenshot the page",
            "capture the page",
            "summarize the page",
            "read the page",
            "what is on the page",
            "explain this page",
            "show links",
            "list links",
            "extract links",
            "deactivate headless",
            "disable headless",
            "visible browser",
            "headed browser",
        )
        has_url = re.search(r"https?://\S+", lowered) or re.search(
            r"\b(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?",
            lowered,
        )
        if any(token in lowered for token in browser_tokens) or has_url:
            approval_class = ApprovalClass.NETWORK if has_url else ApprovalClass.USER_CONFIRM
            return RouteDecision(
                BackendKind.LOCAL,
                approval_class,
                "browser_command",
                "browser_command",
            )

        backend = forced_backend if forced_backend != BackendKind.AUTO else BackendKind.CODEX
        return RouteDecision(backend, ApprovalClass.USER_CONFIRM, "general_agent_request")

    def run_task(self, request: TaskRequest) -> TaskResult:
        task_id = uuid.uuid4().hex
        return self._run_task_with_id(task_id, request, create_audit_row=True)

    def approve_task(
        self,
        task_id: str | None = None,
        *,
        latest: bool = False,
    ) -> TaskResult:
        stored = (
            self.audit.get_latest_pending_task()
            if latest or task_id is None
            else self.audit.get_task(task_id)
        )
        if stored is None:
            return TaskResult(
                task_id=task_id or "",
                status=TaskStatus.FAILED,
                backend=BackendKind.AUTO,
                approval_class=ApprovalClass.USER_CONFIRM,
                route_reason="approval_lookup_failed",
                request_text="",
                error_text="No pending task found to approve.",
                requires_approval=False,
            )
        if stored["status"] != TaskStatus.APPROVAL_REQUIRED.value:
            return TaskResult(
                task_id=str(stored["task_id"]),
                status=TaskStatus.FAILED,
                backend=BackendKind(str(stored["backend"])),
                approval_class=ApprovalClass(str(stored["approval_class"])),
                route_reason="approval_not_pending",
                request_text=str(stored["request_text"]),
                error_text="Task is not waiting for approval.",
                requires_approval=False,
            )

        request = TaskRequest(
            text=str(stored["request_text"]),
            preferred_backend=BackendKind(str(stored["preferred_backend"])),
            auto_approve=True,
            working_dir=Path(str(stored["working_dir"])),
        )
        self.audit.mark_task_approved(str(stored["task_id"]))
        return self._run_task_with_id(
            str(stored["task_id"]),
            request,
            create_audit_row=False,
        )

    def _run_task_with_id(
        self,
        task_id: str,
        request: TaskRequest,
        *,
        create_audit_row: bool,
    ) -> TaskResult:
        working_dir = (request.working_dir or Path.cwd()).resolve()
        decision = self.classify_request(request.text, request.preferred_backend)
        requires_approval = decision.approval_class != ApprovalClass.SAFE_LOCAL
        if create_audit_row:
            self.audit.create_task(
                task_id=task_id,
                request_text=request.text,
                backend=decision.backend.value,
                approval_class=decision.approval_class.value,
                status=(
                    TaskStatus.APPROVAL_REQUIRED.value
                    if requires_approval and not request.auto_approve
                    else "running"
                ),
                route_reason=decision.route_reason,
                preferred_backend=request.preferred_backend.value,
                working_dir=str(working_dir),
                auto_approve=request.auto_approve,
                requires_approval=requires_approval,
            )
        else:
            self.audit.update_task(
                task_id=task_id,
                status="running",
                output_text=None,
                error_text=None,
            )

        log_event(
            self.logger,
            "task_routed",
            task_id=task_id,
            backend=decision.backend.value,
            approval_class=decision.approval_class.value,
            route_reason=decision.route_reason,
            auto_approve=request.auto_approve,
        )

        if requires_approval and not request.auto_approve:
            output_text = (
                f"Approval required for '{decision.approval_class.value}' before executing: "
                f"{request.text}"
            )
            self.audit.update_task(
                task_id=task_id,
                status=TaskStatus.APPROVAL_REQUIRED.value,
                output_text=output_text,
            )
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.APPROVAL_REQUIRED,
                backend=decision.backend,
                approval_class=decision.approval_class,
                route_reason=decision.route_reason,
                request_text=request.text,
                output_text=output_text,
                requires_approval=True,
            )

        try:
            if decision.backend == BackendKind.LOCAL and decision.local_tool is not None:
                action = self._run_local_tool(decision.local_tool, request.text, working_dir)
            elif decision.backend == BackendKind.CODEX:
                prompt = self._build_backend_prompt(request.text, decision)
                action = self.codex_runner.run(
                    prompt,
                    working_dir=working_dir,
                    timeout_seconds=self.config.orchestrator.task_timeout_seconds,
                )
            elif decision.backend == BackendKind.GEMINI:
                prompt = self._build_backend_prompt(request.text, decision, plan_only=True)
                action = self.gemini_runner.run(
                    prompt,
                    working_dir=working_dir,
                    timeout_seconds=self.config.orchestrator.task_timeout_seconds,
                )
            else:
                raise RuntimeError(f"Unsupported backend: {decision.backend.value}")

            self.audit.record_action(
                task_id=task_id,
                executor=action.executor,
                command=action.command,
                exit_code=action.exit_code,
                stdout_text=action.stdout_text,
                stderr_text=action.stderr_text,
            )

            status = TaskStatus.COMPLETED if action.exit_code in (0, None) else TaskStatus.FAILED
            error_text = action.stderr_text if status == TaskStatus.FAILED else ""
            self.audit.update_task(
                task_id=task_id,
                status=status.value,
                output_text=action.stdout_text,
                error_text=error_text or None,
            )
            result = TaskResult(
                task_id=task_id,
                status=status,
                backend=decision.backend,
                approval_class=decision.approval_class,
                route_reason=decision.route_reason,
                request_text=request.text,
                output_text=action.stdout_text,
                error_text=error_text,
                requires_approval=False,
                actions=[action],
            )
            self._record_task_memory(result)
            return result
        except Exception as exc:
            error_text = str(exc)
            self.audit.update_task(
                task_id=task_id,
                status=TaskStatus.FAILED.value,
                error_text=error_text,
            )
            result = TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                backend=decision.backend,
                approval_class=decision.approval_class,
                route_reason=decision.route_reason,
                request_text=request.text,
                error_text=error_text,
                requires_approval=False,
            )
            self._record_task_memory(result)
            return result

    def list_recent_tasks(self, limit: int = 20) -> list[dict[str, object]]:
        return self.audit.list_tasks(limit)

    def list_memory(self, limit: int = 20) -> list[dict[str, object]]:
        return self.audit.list_memory(limit)

    def create_memory_note(self, text: str) -> dict[str, object]:
        note_text = text.strip()
        if not note_text:
            raise ValueError("Memory note text is required.")
        memory_id = self.audit.create_memory_entry(
            kind="user_note",
            summary_text=self._truncate_memory_text(note_text),
            detail={"text": note_text},
        )
        self.audit.trim_memory(self.config.memory.max_entries)
        entry = self.audit.list_memory(limit=1)[0]
        if str(entry["memory_id"]) != memory_id:
            entry = {
                "memory_id": memory_id,
                "kind": "user_note",
                "summary_text": self._truncate_memory_text(note_text),
                "detail": {"text": note_text},
                "pinned": False,
            }
        return entry

    def delete_memory(self, memory_id: str) -> bool:
        return self.audit.delete_memory(memory_id)

    def clear_memory(self) -> int:
        return self.audit.clear_memory()

    def voice_response_for(self, result: TaskResult) -> str:
        if result.status == TaskStatus.APPROVAL_REQUIRED:
            approval_phrase = result.approval_class.value.replace("_", " ")
            return self.persona.approval_required(approval_phrase)
        if result.status == TaskStatus.FAILED:
            if result.error_text.strip():
                detail = result.error_text.strip().splitlines()[0]
                return self.persona.failure(detail)
            return self.persona.failure()
        if result.output_text.strip():
            return result.output_text.strip()
        return "Task completed."

    def _run_local_tool(self, tool_name: str, request_text: str, working_dir: Path) -> ActionResult:
        if tool_name == "pwd":
            command = ["pwd"]
        elif tool_name == "ls":
            command = ["ls", "-la"]
        elif tool_name == "git_status":
            command = ["git", "status", "--short", "--branch"]
        elif tool_name == "browser_command":
            result = self.browser.execute_request(request_text, working_dir)
            return ActionResult(
                executor=result.executor,
                command=result.command,
                exit_code=result.exit_code,
                stdout_text=result.stdout_text,
                stderr_text=result.stderr_text,
            )
        elif tool_name == "browser_state":
            result = self.browser.show_state()
            return ActionResult(
                executor=result.executor,
                command=result.command,
                exit_code=result.exit_code,
                stdout_text=result.stdout_text,
                stderr_text=result.stderr_text,
            )
        elif tool_name == "activity_state":
            parts: list[str] = []
            browser_state = self.browser.get_state()
            screen_state = self.screen.get_state()
            if browser_state is not None:
                parts.append(self.browser.show_state().stdout_text)
            if screen_state is not None:
                parts.append(self.screen.show_state().stdout_text)
            stdout_text = (
                "\n".join(parts)
                if parts
                else "No browser or desktop activity has been recorded yet."
            )
            return ActionResult(
                executor="activity",
                command=[],
                exit_code=0,
                stdout_text=stdout_text,
                stderr_text="",
            )
        elif tool_name == "screen_screenshot":
            result = self.screen.capture_screenshot(working_dir)
            return ActionResult(
                executor=result.executor,
                command=result.command,
                exit_code=result.exit_code,
                stdout_text=result.stdout_text,
                stderr_text=result.stderr_text,
            )
        elif tool_name == "screen_record":
            result = self.screen.execute_request(request_text, working_dir)
            return ActionResult(
                executor=result.executor,
                command=result.command,
                exit_code=result.exit_code,
                stdout_text=result.stdout_text,
                stderr_text=result.stderr_text,
            )
        elif tool_name == "screen_state":
            result = self.screen.show_state()
            return ActionResult(
                executor=result.executor,
                command=result.command,
                exit_code=result.exit_code,
                stdout_text=result.stdout_text,
                stderr_text=result.stderr_text,
            )
        elif tool_name == "memory_list":
            memories = self.list_memory(limit=8)
            if not memories:
                stdout_text = "No memory entries have been stored yet."
            else:
                lines = [
                    f"{entry['memory_id']}: {entry['summary_text']}"
                    for entry in memories
                ]
                stdout_text = "\n".join(lines)
            return ActionResult(
                executor="memory",
                command=[],
                exit_code=0,
                stdout_text=stdout_text,
                stderr_text="",
            )
        elif tool_name == "memory_note":
            note_text = self._extract_memory_note(request_text)
            entry = self.create_memory_note(note_text)
            return ActionResult(
                executor="memory",
                command=[],
                exit_code=0,
                stdout_text=f"Saved memory note {entry['memory_id']}: {entry['summary_text']}",
                stderr_text="",
            )
        elif tool_name == "launch_app":
            command = self._resolve_launch_command(request_text)
            process = subprocess.Popen(  # noqa: S603
                command,
                cwd=working_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return ActionResult(
                executor="launch",
                command=command,
                exit_code=0,
                stdout_text=f"Launched {' '.join(command)} with pid {process.pid}.",
                stderr_text="",
            )
        elif tool_name in {
            "file_read",
            "file_mkdir",
            "file_touch",
            "file_list_dir",
            "file_copy",
            "file_move",
            "file_delete",
            "file_find",
            "file_search_text",
        }:
            result = self.files.execute_request(tool_name, request_text, working_dir)
            return ActionResult(
                executor=result.executor,
                command=result.command,
                exit_code=result.exit_code,
                stdout_text=result.stdout_text,
                stderr_text=result.stderr_text,
            )
        else:
            raise RuntimeError(f"Unsupported local tool: {tool_name}")

        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=self.config.orchestrator.task_timeout_seconds,
        )
        stdout_text = completed.stdout.strip() or completed.stderr.strip()
        return ActionResult(
            executor="local",
            command=command,
            exit_code=completed.returncode,
            stdout_text=stdout_text,
            stderr_text=completed.stderr.strip(),
        )

    def _build_backend_prompt(
        self,
        request_text: str,
        decision: RouteDecision,
        *,
        plan_only: bool = False,
    ) -> str:
        mode = "Plan only; do not execute tools." if plan_only else "Complete the task."
        memory_context = self._build_prompt_memory_context(limit=6)
        memory_block = (
            "Relevant local memory:\n"
            f"{memory_context}\n"
            if memory_context
            else ""
        )
        runtime_context = self._build_runtime_context()
        runtime_block = (
            "Current local context:\n"
            f"{runtime_context}\n"
            if runtime_context
            else ""
        )
        return (
            "You are Dude's execution backend.\n"
            f"Task: {request_text}\n"
            f"Approval class: {decision.approval_class.value}\n"
            f"Route reason: {decision.route_reason}\n"
            f"{memory_block}"
            f"{runtime_block}"
            f"{mode}\n"
            "Return a concise result summary."
        )

    def _record_task_memory(self, result: TaskResult) -> None:
        if not self.config.memory.enabled:
            return
        if result.route_reason in {"memory_list", "memory_note"}:
            return
        summary = self._build_memory_summary(result)
        if not summary:
            return
        detail = {
            "request_text": result.request_text,
            "route_reason": result.route_reason,
            "backend": result.backend.value,
            "approval_class": result.approval_class.value,
            "status": result.status.value,
            "output_text": result.output_text,
            "error_text": result.error_text,
        }
        self.audit.create_memory_entry(
            kind="task_summary",
            summary_text=summary,
            detail=detail,
            source_task_id=result.task_id,
        )
        self.audit.trim_memory(self.config.memory.max_entries)

    def _build_memory_summary(self, result: TaskResult) -> str:
        request_text = result.request_text.strip()
        output_text = result.output_text.strip()
        error_text = result.error_text.strip()
        if result.status == TaskStatus.COMPLETED and output_text:
            summary = f"{request_text} -> {output_text}"
        elif result.status == TaskStatus.FAILED and error_text:
            summary = f"{request_text} -> failed: {error_text}"
        else:
            summary = request_text
        return self._truncate_memory_text(summary)

    def _truncate_memory_text(self, text: str) -> str:
        max_chars = max(32, int(self.config.memory.summary_max_chars))
        compact = " ".join(text.split())
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "…"

    def _extract_memory_note(self, request_text: str) -> str:
        lowered = request_text.lower()
        if lowered.startswith("remember that "):
            return request_text[14:].strip()
        if lowered.startswith("remember "):
            return request_text[9:].strip()
        return request_text.strip()

    def _build_prompt_memory_context(self, limit: int) -> str:
        entries = self.audit.list_memory(limit=max(1, limit))
        if not entries:
            return ""
        lines: list[str] = []
        for entry in entries:
            kind = str(entry["kind"]).replace("_", " ")
            summary = str(entry["summary_text"]).strip()
            if not summary:
                continue
            lines.append(f"- {kind}: {summary}")
        return "\n".join(lines)

    def _build_runtime_context(self) -> str:
        lines: list[str] = []
        browser_state = self.browser.get_state()
        if isinstance(browser_state, dict):
            url = str(browser_state.get("url", "")).strip()
            title = str(browser_state.get("title", "")).strip()
            excerpt = str(browser_state.get("page_excerpt", "")).strip()
            mode = str(browser_state.get("mode", "")).strip()
            browser_line = "browser"
            if url:
                browser_line += f": {url}"
            if title:
                browser_line += f" | title={title}"
            if mode:
                browser_line += f" | mode={mode}"
            if excerpt:
                browser_line += f" | excerpt={self._truncate_memory_text(excerpt)}"
            lines.append(f"- {browser_line}")

        screen_state = self.screen.get_state()
        if isinstance(screen_state, dict):
            artifact = str(screen_state.get("artifact_path", "")).strip()
            resolution = str(screen_state.get("resolution", "")).strip()
            mode = str(screen_state.get("mode", "")).strip()
            screen_line = "screen"
            if mode:
                screen_line += f": mode={mode}"
            if resolution:
                screen_line += f" | resolution={resolution}"
            if artifact:
                screen_line += f" | artifact={artifact}"
            lines.append(f"- {screen_line}")

        return "\n".join(lines)

    def _resolve_launch_command(self, request_text: str) -> list[str]:
        lowered = request_text.lower()
        home = Path.home()
        candidates: list[list[str]]

        if "downloads" in lowered:
            candidates = [["xdg-open", str(home / "Downloads")]]
        elif "file manager" in lowered or "open files" in lowered:
            candidates = [
                ["nautilus"],
                ["thunar"],
                ["dolphin"],
                ["xdg-open", str(home)],
            ]
        elif "terminal" in lowered:
            candidates = [
                ["gnome-terminal"],
                ["kgx"],
                ["x-terminal-emulator"],
                ["konsole"],
                ["xfce4-terminal"],
            ]
        elif "firefox" in lowered:
            candidates = [["firefox"]]
        elif "chrome" in lowered:
            candidates = [
                ["google-chrome"],
                ["google-chrome-stable"],
                ["chromium"],
                ["chromium-browser"],
            ]
        elif "discord" in lowered:
            candidates = [["discord"], ["Discord"]]
        else:
            raise RuntimeError(f"Could not map an application launch request from: {request_text}")

        for command in candidates:
            if shutil.which(command[0]):
                return command
        raise RuntimeError(f"No installed application matched launch request: {request_text}")
