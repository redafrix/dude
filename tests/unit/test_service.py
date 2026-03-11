from __future__ import annotations

import asyncio
import logging

from dude.config import load_config
from dude.orchestrator import (
    ApprovalClass,
    BackendKind,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from dude.service import DudeService


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.approved_task_ids: list[str] = []

    def run_task(self, request: TaskRequest) -> TaskResult:
        self.requests.append(request.text)
        return TaskResult(
            task_id="task-approval-1",
            status=TaskStatus.APPROVAL_REQUIRED,
            backend=BackendKind.CODEX,
            approval_class=ApprovalClass.NETWORK,
            route_reason="network_request",
            request_text=request.text,
            output_text="Approval required.",
            requires_approval=True,
        )

    def approve_task(self, task_id: str | None = None, *, latest: bool = False) -> TaskResult:
        del latest
        if task_id is not None:
            self.approved_task_ids.append(task_id)
        return TaskResult(
            task_id=task_id or "task-approval-1",
            status=TaskStatus.COMPLETED,
            backend=BackendKind.CODEX,
            approval_class=ApprovalClass.NETWORK,
            route_reason="network_request",
            request_text="download discord for me",
            output_text="Download staged.",
            requires_approval=False,
        )

    def voice_response_for(self, result: TaskResult) -> str:
        return result.output_text or result.error_text


class _FakePrompter:
    def __init__(self, approved: bool) -> None:
        self.approved = approved
        self.prompted_task_ids: list[str] = []

    def prompt_task(self, result: TaskResult) -> bool:
        self.prompted_task_ids.append(result.task_id)
        return self.approved


def test_service_voice_command_can_auto_approve_with_desktop_prompt() -> None:
    config = load_config("configs/default.yaml")
    service = DudeService(config, logging.getLogger("test"))
    fake_orchestrator = _FakeOrchestrator()
    fake_prompter = _FakePrompter(True)
    service.orchestrator = fake_orchestrator
    service.approval_prompter = fake_prompter

    response = asyncio.run(service.handle_voice_command("download discord for me"))

    assert fake_orchestrator.requests == ["download discord for me"]
    assert fake_prompter.prompted_task_ids == ["task-approval-1"]
    assert fake_orchestrator.approved_task_ids == ["task-approval-1"]
    assert response == "Download staged."
