from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from dude.config import DudeConfig


@dataclass(slots=True)
class TailscaleServeResult:
    command: list[str]
    exit_code: int
    stdout_text: str
    stderr_text: str
    url: str | None = None


class TailscaleController:
    def __init__(self, config: DudeConfig) -> None:
        self.config = config

    def serve_remote_api(self) -> TailscaleServeResult:
        self._require_tailscale()
        target = f"127.0.0.1:{self.config.remote.port}"
        command = ["tailscale", "serve", "--bg", target]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
        url = self._tailscale_https_url() if completed.returncode == 0 else None
        return TailscaleServeResult(
            command=command,
            exit_code=completed.returncode,
            stdout_text=completed.stdout.strip(),
            stderr_text=completed.stderr.strip(),
            url=url,
        )

    def serve_status(self) -> TailscaleServeResult:
        self._require_tailscale()
        command = ["tailscale", "serve", "status"]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return TailscaleServeResult(
            command=command,
            exit_code=completed.returncode,
            stdout_text=completed.stdout.strip(),
            stderr_text=completed.stderr.strip(),
            url=self._tailscale_https_url() if completed.returncode == 0 else None,
        )

    def reset_serve(self) -> TailscaleServeResult:
        self._require_tailscale()
        command = ["tailscale", "serve", "reset", "--yes"]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return TailscaleServeResult(
            command=command,
            exit_code=completed.returncode,
            stdout_text=completed.stdout.strip(),
            stderr_text=completed.stderr.strip(),
            url=None,
        )

    def _tailscale_https_url(self) -> str | None:
        command = ["tailscale", "status", "--json"]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        self_payload = payload.get("Self", {})
        if not isinstance(self_payload, dict):
            return None
        dns_name = str(self_payload.get("DNSName", "")).strip().rstrip(".")
        if not dns_name:
            return None
        return f"https://{dns_name}"

    def _require_tailscale(self) -> None:
        if shutil.which("tailscale") is None:
            raise RuntimeError("tailscale is not installed or not available in PATH.")
