from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dude.config import load_config
from dude.orchestrator import ApprovalClass, CodexRunner
from dude.sudo import SudoController


def test_sudo_controller_writes_askpass_and_wrapper(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")
    config.runtime.state_dir = tmp_path / "runtime"
    config.sudo.helper_dir = tmp_path / "sudo"

    def _fake_which(command: str) -> str | None:
        if command == "sudo":
            return "/usr/bin/sudo"
        if command == "zenity":
            return "/usr/bin/zenity"
        return None

    monkeypatch.setattr("dude.sudo.shutil.which", _fake_which)

    controller = SudoController(config)
    env = controller.prepare_environment("install discord")

    assert env["SUDO_ASKPASS"].endswith("dude-askpass.sh")
    assert env["DUDE_SUDO_PROMPT_REASON"] == "install discord"
    assert env["PATH"].startswith(str(config.sudo.helper_dir.resolve()))
    assert (config.sudo.helper_dir / "dude-askpass.sh").exists()
    assert (config.sudo.helper_dir / "sudo").exists()


def test_codex_runner_uses_sudo_environment_for_sudo_tasks(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")
    config.runtime.state_dir = tmp_path / "runtime"
    config.sudo.helper_dir = tmp_path / "sudo"
    runner = CodexRunner(config)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        runner.sudo,
        "prepare_environment",
        lambda request_text: {
            "PATH": "/tmp/dude-sudo:/usr/bin",
            "SUDO_ASKPASS": "/tmp/dude-sudo/askpass.sh",
            "DUDE_SUDO_PROMPT_REASON": request_text,
        },
    )

    def _fake_run(command, *, cwd, capture_output, text, timeout, env=None):
        del cwd, capture_output, text, timeout
        captured["command"] = command
        captured["env"] = env
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    result = runner.run(
        "install package",
        working_dir=tmp_path,
        timeout_seconds=30,
        approval_class=ApprovalClass.SUDO,
        request_text="install package",
    )

    assert result.exit_code == 0
    assert result.stdout_text == "ok"
    assert "-s" in captured["command"]
    assert "danger-full-access" in captured["command"]
    assert captured["env"]["SUDO_ASKPASS"] == "/tmp/dude-sudo/askpass.sh"


def test_codex_runner_attaches_images(monkeypatch, tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")
    runner = CodexRunner(config)
    captured: dict[str, object] = {}
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"png")

    def _fake_run(command, *, cwd, capture_output, text, timeout, env=None):
        del cwd, capture_output, text, timeout, env
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    runner.run(
        "describe the screen",
        working_dir=tmp_path,
        timeout_seconds=30,
        approval_class=ApprovalClass.USER_CONFIRM,
        request_text="describe the screen",
        image_paths=[image_path],
    )

    assert "-i" in captured["command"]
    image_index = captured["command"].index("-i")
    assert captured["command"][image_index + 1] == str(image_path)
