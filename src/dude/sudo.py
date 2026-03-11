from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dude.config import DudeConfig, SudoConfig


@dataclass(slots=True)
class SudoEnvironment:
    env: dict[str, str]
    askpass_path: Path
    sudo_wrapper_path: Path


class SudoController:
    def __init__(self, config: DudeConfig) -> None:
        self.config = config
        helper_dir = config.sudo.helper_dir or (config.runtime.state_dir / "sudo")
        self.helper_dir = helper_dir.resolve()

    def prepare_environment(self, request_text: str) -> dict[str, str]:
        if not self.config.sudo.enabled:
            return {}
        sudo_path = shutil.which("sudo")
        if not sudo_path:
            return {}
        prompt_backend = self._resolve_prompt_backend(self.config.sudo)
        if prompt_backend is None:
            return {}
        environment = self.ensure_helpers(
            request_text=request_text,
            sudo_path=Path(sudo_path),
            prompt_backend=prompt_backend,
        )
        return environment.env

    def ensure_helpers(
        self,
        *,
        request_text: str,
        sudo_path: Path,
        prompt_backend: str,
    ) -> SudoEnvironment:
        self.helper_dir.mkdir(parents=True, exist_ok=True)
        askpass_path = self.helper_dir / "dude-askpass.sh"
        sudo_wrapper_path = self.helper_dir / "sudo"
        self._write_askpass_script(askpass_path)
        self._write_sudo_wrapper(sudo_wrapper_path, sudo_path)

        env = dict(os.environ)
        env["SUDO_ASKPASS"] = str(askpass_path)
        env["DUDE_SUDO_PROMPT_BACKEND"] = prompt_backend
        env["DUDE_SUDO_PROMPT_TITLE"] = self.config.sudo.prompt_title
        env["DUDE_SUDO_PROMPT_REASON"] = request_text
        env["DUDE_REAL_SUDO"] = str(sudo_path)
        env["PATH"] = f"{self.helper_dir}{os.pathsep}{env.get('PATH', '')}"
        return SudoEnvironment(
            env=env,
            askpass_path=askpass_path,
            sudo_wrapper_path=sudo_wrapper_path,
        )

    def _resolve_prompt_backend(self, config: SudoConfig) -> str | None:
        if config.prompt_backend == "none":
            return None
        if config.prompt_backend == "auto":
            if shutil.which("zenity"):
                return "zenity"
            if shutil.which("systemd-ask-password"):
                return "systemd-ask-password"
            return None
        if config.prompt_backend == "zenity" and not shutil.which("zenity"):
            return None
        if config.prompt_backend == "systemd-ask-password" and not shutil.which(
            "systemd-ask-password"
        ):
            return None
        return config.prompt_backend

    def _write_askpass_script(self, path: Path) -> None:
        script = """#!/usr/bin/env bash
set -eu
backend="${DUDE_SUDO_PROMPT_BACKEND:-auto}"
title="${DUDE_SUDO_PROMPT_TITLE:-Dude Sudo Required}"
prompt="${1:-Sudo password required}"
reason="${DUDE_SUDO_PROMPT_REASON:-Dude requires sudo to continue.}"
message="${reason}\n\n${prompt}"

if [[ "$backend" == "zenity" || "$backend" == "auto" ]]; then
  if command -v zenity >/dev/null 2>&1; then
    exec zenity --password --title="$title" --text="$message"
  fi
fi

if [[ "$backend" == "systemd-ask-password" || "$backend" == "auto" ]]; then
  if command -v systemd-ask-password >/dev/null 2>&1; then
    exec systemd-ask-password "$reason $prompt"
  fi
fi

exit 1
"""
        path.write_text(script, encoding="utf-8")
        path.chmod(0o700)

    def _write_sudo_wrapper(self, path: Path, sudo_path: Path) -> None:
        script = f"""#!/usr/bin/env bash
set -eu
exec "{sudo_path}" -A "$@"
"""
        path.write_text(script, encoding="utf-8")
        path.chmod(0o700)
