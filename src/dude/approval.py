from __future__ import annotations

import shutil
import subprocess

from dude.config import ApprovalConfig
from dude.orchestrator import TaskResult


class DesktopApprovalPrompter:
    def __init__(self, config: ApprovalConfig) -> None:
        self.config = config

    def prompt_task(self, result: TaskResult) -> bool:
        if not self.config.desktop_prompt:
            return False
        backend = self._select_backend()
        if backend == "zenity":
            return self._prompt_with_zenity(result)
        if backend == "notify-send":
            self._notify(result)
            return False
        return False

    def _select_backend(self) -> str:
        if self.config.prompt_backend != "auto":
            return self.config.prompt_backend
        if shutil.which("zenity"):
            return "zenity"
        if shutil.which("notify-send"):
            return "notify-send"
        return "none"

    def _prompt_with_zenity(self, result: TaskResult) -> bool:
        message = (
            f"Dude needs approval for a {result.approval_class.value} task.\n\n"
            f"Request: {result.request_text}\n\n"
            "Approve now?"
        )
        completed = subprocess.run(
            [
                "zenity",
                "--question",
                "--title=Dude Approval Required",
                f"--text={message}",
                "--width=480",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return completed.returncode == 0

    def _notify(self, result: TaskResult) -> None:
        subprocess.run(
            [
                "notify-send",
                "Dude approval required",
                f"{result.approval_class.value}: {result.request_text}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
