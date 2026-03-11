from __future__ import annotations

import subprocess
from pathlib import Path

from dude.config import load_config
from dude.tailscale import TailscaleController


def test_tailscale_controller_builds_https_url(monkeypatch) -> None:
    config = load_config(Path("configs/default.yaml"))
    controller = TailscaleController(config)

    monkeypatch.setattr("dude.tailscale.shutil.which", lambda name: "/usr/bin/tailscale")

    def _run(command, **kwargs):
        del kwargs
        if command[:3] == ["tailscale", "status", "--json"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout='{"Self":{"DNSName":"dude-machine.tail123.ts.net."}}',
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="configured",
            stderr="",
        )

    monkeypatch.setattr("dude.tailscale.subprocess.run", _run)

    result = controller.serve_remote_api()

    assert result.exit_code == 0
    assert result.url == "https://dude-machine.tail123.ts.net"
    assert result.command == ["tailscale", "serve", "--bg", "127.0.0.1:8765"]


def test_tailscale_controller_can_reset(monkeypatch) -> None:
    config = load_config(Path("configs/default.yaml"))
    controller = TailscaleController(config)

    monkeypatch.setattr("dude.tailscale.shutil.which", lambda name: "/usr/bin/tailscale")
    monkeypatch.setattr(
        "dude.tailscale.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="reset",
            stderr="",
        ),
    )

    result = controller.reset_serve()

    assert result.exit_code == 0
    assert result.command == ["tailscale", "serve", "reset", "--yes"]
