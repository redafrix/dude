from pathlib import Path

from dude.config import load_config


def test_load_default_config() -> None:
    config = load_config(Path("configs/default.yaml"))
    assert config.activation.wake_word == "dude"
    assert config.audio.sample_rate_hz == 16000
    assert config.runtime.state_dir.name == "runtime"
    assert config.runtime.control_socket_path.name == "control.sock"
    assert config.runtime.audit_db_path.name == "dude.db"
    assert config.normalization.enabled is True
    assert config.orchestrator.default_backend == "auto"
