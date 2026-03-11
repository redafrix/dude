from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from dude.approval import DesktopApprovalPrompter
from dude.config import DudeConfig
from dude.control import ControlPlane
from dude.events import AssistantState, AssistantStatus
from dude.logging import log_event
from dude.metrics import collect_resource_snapshot, write_benchmark_result
from dude.orchestrator import BackendKind, Orchestrator, TaskRequest, TaskStatus
from dude.pipeline import VoicePipeline


class DudeService:
    def __init__(self, config: DudeConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.status = AssistantStatus()
        self.pipeline = VoicePipeline(config, logger, self.status)
        self.orchestrator = Orchestrator(config, logger)
        self.approval_prompter = DesktopApprovalPrompter(config.approval)
        self.control = ControlPlane(
            config.runtime.control_socket_path,
            self.handle_command,
        )
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self.config.runtime.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.runtime.benchmark_output_dir.mkdir(parents=True, exist_ok=True)
        self.config.runtime.audit_db_path.parent.mkdir(parents=True, exist_ok=True)
        await self.pipeline.start()
        await self.control.start()
        log_event(
            self.logger,
            "service_started",
            control_socket_path=str(self.config.runtime.control_socket_path),
        )

    async def stop(self) -> None:
        await self.control.close()
        await self.pipeline.stop()
        log_event(self.logger, "service_stopped")

    async def run(self) -> None:
        await self.start()
        tasks = [
            asyncio.create_task(self.control.serve_forever(), name="control-plane"),
            asyncio.create_task(self.pipeline.run(), name="voice-pipeline"),
            asyncio.create_task(self._stop_event.wait(), name="stop-waiter"),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        finally:
            await self.stop()

    async def handle_command(self, payload: dict[str, object]) -> dict[str, object]:
        command = str(payload.get("command", "status"))
        if command == "arm":
            self.status.armed = True
            self.status.state = AssistantState.ARMED
            self.status.updated_at = asyncio.get_running_loop().time()
            log_event(self.logger, "assistant_armed")
            return {"ok": True, "status": self.status.to_dict()}
        if command == "disarm":
            self.status.armed = False
            self.status.speaking = False
            self.status.state = AssistantState.IDLE
            await self.pipeline.audio_output.stop()
            self.status.updated_at = asyncio.get_running_loop().time()
            log_event(self.logger, "assistant_disarmed")
            return {"ok": True, "status": self.status.to_dict()}
        if command == "status":
            return {"ok": True, "status": self.status.to_dict()}
        if command == "benchmark":
            result = await self._run_smoke_benchmark()
            return {"ok": True, "benchmark": result}
        if command == "task":
            text = str(payload.get("text", "")).strip()
            backend = BackendKind(str(payload.get("backend", "auto")))
            auto_approve = bool(payload.get("auto_approve", False))
            result = await asyncio.to_thread(
                self.orchestrator.run_task,
                TaskRequest(
                    text=text,
                    preferred_backend=backend,
                    auto_approve=auto_approve,
                ),
            )
            return {"ok": True, "task": result.to_dict()}
        if command == "approve":
            task_id = payload.get("task_id")
            latest = bool(payload.get("latest", False))
            result = await asyncio.to_thread(
                self.orchestrator.approve_task,
                str(task_id) if task_id is not None else None,
                latest=latest,
            )
            return {"ok": True, "task": result.to_dict()}
        if command == "audit":
            limit = int(payload.get("limit", 20))
            return {"ok": True, "tasks": self.orchestrator.list_recent_tasks(limit)}
        if command == "shutdown":
            self._stop_event.set()
            return {"ok": True, "status": self.status.to_dict()}
        return {"ok": False, "error": f"Unsupported command: {command}"}

    async def handle_voice_command(self, text: str) -> str:
        lowered = text.strip().lower()
        if lowered in {
            "approve latest task",
            "approve the latest task",
            "approve last task",
            "approve the last task",
        }:
            result = await asyncio.to_thread(self.orchestrator.approve_task, None, latest=True)
            return self.orchestrator.voice_response_for(result)
        result = await asyncio.to_thread(
            self.orchestrator.run_task,
            TaskRequest(
                text=text,
                preferred_backend=BackendKind.AUTO,
                auto_approve=False,
            ),
        )
        if result.status == TaskStatus.APPROVAL_REQUIRED:
            approved = await asyncio.to_thread(self.approval_prompter.prompt_task, result)
            if approved:
                result = await asyncio.to_thread(
                    self.orchestrator.approve_task,
                    result.task_id,
                    latest=False,
                )
        return self.orchestrator.voice_response_for(result)

    async def _run_smoke_benchmark(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status.to_dict(),
            "resources": collect_resource_snapshot(),
        }
        output = self.config.runtime.benchmark_output_dir / "smoke-benchmark.json"
        write_benchmark_result(output, payload)
        return payload


async def run_service(config: DudeConfig, logger: logging.Logger, warmup: bool = False) -> None:
    service = DudeService(config, logger)
    service.pipeline.command_handler = service.handle_voice_command
    if warmup:
        await asyncio.to_thread(service.pipeline.warmup)
    await service.run()
