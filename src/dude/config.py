from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


@dataclass(slots=True)
class RuntimeConfig:
    state_dir: Path = Path("./state")
    log_dir: Path = Path("./logs")
    control_socket_path: Path = Path("./state/control.sock")
    benchmark_output_dir: Path = Path("./benchmarks/results")
    audit_db_path: Path = Path("./state/dude.db")


@dataclass(slots=True)
class AudioConfig:
    input_device: str | int | None = None
    output_device: str | int | None = None
    sample_rate_hz: int = 16000
    block_duration_ms: int = 80
    channels: int = 1
    max_request_seconds: float = 12.0
    pre_roll_seconds: float = 1.2
    post_speech_seconds: float = 0.8
    barge_in_grace_ms: int = 180

    @property
    def block_samples(self) -> int:
        return int(self.sample_rate_hz * (self.block_duration_ms / 1000))


@dataclass(slots=True)
class ActivationConfig:
    hotkey_hint: str = "Alt+A"
    wake_word: str = "dude"
    greeting_text: str = "Hi, what can I help you with?"
    follow_up_timeout_seconds: float = 6.0


@dataclass(slots=True)
class VadConfig:
    threshold: float = 0.55
    min_silence_ms: int = 600
    speech_pad_ms: int = 250


@dataclass(slots=True)
class WakeWordConfig:
    backend: Literal["transcript", "openwakeword"] = "transcript"
    model_name: str = "dude"
    model_path: Path | None = None
    threshold: float = 0.5
    trigger_cooldown_ms: int = 1600


@dataclass(slots=True)
class AsrConfig:
    provider: Literal["faster_whisper"] = "faster_whisper"
    model_name: str = "distil-small.en"
    device: str = "auto"
    language: str = "en"


@dataclass(slots=True)
class TtsConfig:
    provider: Literal["speechd", "tone", "kokoro"] = "kokoro"
    voice: str = "af_heart"
    sample_rate_hz: int = 24000
    speed: float = 1.0
    fallback_to_tone: bool = True
    kokoro_model_path: Path | None = None
    kokoro_voice_path: Path | None = None
    speechd_output_module: str | None = None
    speechd_language: str = "en"


@dataclass(slots=True)
class NormalizationConfig:
    enabled: bool = True
    format_numbers: bool = True
    format_symbols: bool = True


@dataclass(slots=True)
class OrchestratorConfig:
    default_backend: Literal["auto", "local", "codex", "gemini"] = "auto"
    codex_model: str | None = None
    gemini_model: str | None = None
    codex_sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    task_timeout_seconds: int = 600
    gemini_plan_only: bool = True


@dataclass(slots=True)
class BrowserConfig:
    preferred_engine: Literal["playwright", "chrome_cli"] = "playwright"
    executable_path: Path | None = None
    artifact_dir: Path | None = None
    default_url: str = "https://example.com"
    headless_by_default: bool = True
    viewport_width: int = 1440
    viewport_height: int = 1024
    navigation_timeout_ms: int = 15000
    settle_time_ms: int = 750


@dataclass(slots=True)
class RemoteConfig:
    enabled: bool = False
    bind_host: str = "127.0.0.1"
    port: int = 8765
    auth_token: str | None = None
    auth_token_path: Path | None = None


@dataclass(slots=True)
class ScreenConfig:
    artifact_dir: Path | None = None
    display: str | None = None
    framerate: int = 12
    default_clip_seconds: float = 6.0
    screenshot_timeout_seconds: int = 10
    record_timeout_seconds: int = 20


@dataclass(slots=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str | None = None
    allowed_chat_ids: list[int] = field(default_factory=list)
    poll_timeout_seconds: int = 30
    voice_replies: bool = True


@dataclass(slots=True)
class MemoryConfig:
    enabled: bool = True
    max_entries: int = 200
    summary_max_chars: int = 280


@dataclass(slots=True)
class PersonaConfig:
    mode: Literal["neutral", "witty", "narcissistic"] = "neutral"
    operator_name: str = "Reda"


@dataclass(slots=True)
class ApprovalConfig:
    desktop_prompt: bool = True
    prompt_backend: Literal["auto", "zenity", "notify-send", "none"] = "auto"


@dataclass(slots=True)
class BenchmarkConfig:
    idle_false_accept_window_seconds: int = 1800
    warm_target_first_audio_ms: int = 1500
    cold_target_first_audio_ms: int = 3000
    barge_in_target_ms: int = 250


@dataclass(slots=True)
class DudeConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    wake_word: WakeWordConfig = field(default_factory=WakeWordConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    approval: ApprovalConfig = field(default_factory=ApprovalConfig)
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)


def _resolve_path(value: str | Path | None, base_dir: Path) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _get_section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    section = raw.get(key, {})
    if not isinstance(section, dict):
        raise ValueError(f"Expected '{key}' to be a mapping.")
    return section


def load_config(path: str | Path) -> DudeConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("Top-level config must be a mapping.")

    base_dir = config_path.parent
    runtime_raw = _get_section(raw, "runtime")
    audio_raw = _get_section(raw, "audio")
    activation_raw = _get_section(raw, "activation")
    vad_raw = _get_section(raw, "vad")
    wake_word_raw = _get_section(raw, "wake_word")
    asr_raw = _get_section(raw, "asr")
    tts_raw = _get_section(raw, "tts")
    normalization_raw = _get_section(raw, "normalization")
    orchestrator_raw = _get_section(raw, "orchestrator")
    browser_raw = _get_section(raw, "browser")
    remote_raw = _get_section(raw, "remote")
    screen_raw = _get_section(raw, "screen")
    telegram_raw = _get_section(raw, "telegram")
    memory_raw = _get_section(raw, "memory")
    persona_raw = _get_section(raw, "persona")
    approval_raw = _get_section(raw, "approval")
    benchmark_raw = _get_section(raw, "benchmark")

    runtime_defaults = RuntimeConfig()
    config = DudeConfig(
        runtime=RuntimeConfig(
            state_dir=_resolve_path(runtime_raw.get("state_dir"), base_dir)
            or runtime_defaults.state_dir,
            log_dir=_resolve_path(runtime_raw.get("log_dir"), base_dir)
            or runtime_defaults.log_dir,
            control_socket_path=_resolve_path(runtime_raw.get("control_socket_path"), base_dir)
            or runtime_defaults.control_socket_path,
            benchmark_output_dir=_resolve_path(runtime_raw.get("benchmark_output_dir"), base_dir)
            or runtime_defaults.benchmark_output_dir,
            audit_db_path=_resolve_path(runtime_raw.get("audit_db_path"), base_dir)
            or runtime_defaults.audit_db_path,
        ),
        audio=AudioConfig(
            input_device=audio_raw.get("input_device"),
            output_device=audio_raw.get("output_device"),
            sample_rate_hz=int(audio_raw.get("sample_rate_hz", 16000)),
            block_duration_ms=int(audio_raw.get("block_duration_ms", 80)),
            channels=int(audio_raw.get("channels", 1)),
            max_request_seconds=float(audio_raw.get("max_request_seconds", 12.0)),
            pre_roll_seconds=float(audio_raw.get("pre_roll_seconds", 1.2)),
            post_speech_seconds=float(audio_raw.get("post_speech_seconds", 0.8)),
            barge_in_grace_ms=int(audio_raw.get("barge_in_grace_ms", 180)),
        ),
        activation=ActivationConfig(
            hotkey_hint=str(activation_raw.get("hotkey_hint", "Alt+A")),
            wake_word=str(activation_raw.get("wake_word", "dude")),
            greeting_text=str(
                activation_raw.get("greeting_text", "Hi, what can I help you with?")
            ),
            follow_up_timeout_seconds=float(activation_raw.get("follow_up_timeout_seconds", 6.0)),
        ),
        vad=VadConfig(
            threshold=float(vad_raw.get("threshold", 0.55)),
            min_silence_ms=int(vad_raw.get("min_silence_ms", 600)),
            speech_pad_ms=int(vad_raw.get("speech_pad_ms", 250)),
        ),
        wake_word=WakeWordConfig(
            backend=str(wake_word_raw.get("backend", "transcript")),  # type: ignore[arg-type]
            model_name=str(wake_word_raw.get("model_name", "dude")),
            model_path=_resolve_path(wake_word_raw.get("model_path"), base_dir),
            threshold=float(wake_word_raw.get("threshold", 0.5)),
            trigger_cooldown_ms=int(wake_word_raw.get("trigger_cooldown_ms", 1600)),
        ),
        asr=AsrConfig(
            provider=str(asr_raw.get("provider", "faster_whisper")),  # type: ignore[arg-type]
            model_name=str(asr_raw.get("model_name", "distil-small.en")),
            device=str(asr_raw.get("device", "auto")),
            language=str(asr_raw.get("language", "en")),
        ),
        tts=TtsConfig(
            provider=str(tts_raw.get("provider", "kokoro")),  # type: ignore[arg-type]
            voice=str(tts_raw.get("voice", "af_heart")),
            sample_rate_hz=int(tts_raw.get("sample_rate_hz", 24000)),
            speed=float(tts_raw.get("speed", 1.0)),
            fallback_to_tone=bool(tts_raw.get("fallback_to_tone", True)),
            kokoro_model_path=_resolve_path(tts_raw.get("kokoro_model_path"), base_dir),
            kokoro_voice_path=_resolve_path(tts_raw.get("kokoro_voice_path"), base_dir),
            speechd_output_module=tts_raw.get("speechd_output_module"),
            speechd_language=str(tts_raw.get("speechd_language", "en")),
        ),
        normalization=NormalizationConfig(
            enabled=bool(normalization_raw.get("enabled", True)),
            format_numbers=bool(normalization_raw.get("format_numbers", True)),
            format_symbols=bool(normalization_raw.get("format_symbols", True)),
        ),
        orchestrator=OrchestratorConfig(
            default_backend=str(orchestrator_raw.get("default_backend", "auto")),  # type: ignore[arg-type]
            codex_model=orchestrator_raw.get("codex_model"),
            gemini_model=orchestrator_raw.get("gemini_model"),
            codex_sandbox=str(orchestrator_raw.get("codex_sandbox", "workspace-write")),  # type: ignore[arg-type]
            task_timeout_seconds=int(orchestrator_raw.get("task_timeout_seconds", 600)),
            gemini_plan_only=bool(orchestrator_raw.get("gemini_plan_only", True)),
        ),
        browser=BrowserConfig(
            preferred_engine=str(browser_raw.get("preferred_engine", "playwright")),  # type: ignore[arg-type]
            executable_path=_resolve_path(browser_raw.get("executable_path"), base_dir),
            artifact_dir=_resolve_path(browser_raw.get("artifact_dir"), base_dir),
            default_url=str(browser_raw.get("default_url", "https://example.com")),
            headless_by_default=bool(browser_raw.get("headless_by_default", True)),
            viewport_width=int(browser_raw.get("viewport_width", 1440)),
            viewport_height=int(browser_raw.get("viewport_height", 1024)),
            navigation_timeout_ms=int(browser_raw.get("navigation_timeout_ms", 15000)),
            settle_time_ms=int(browser_raw.get("settle_time_ms", 750)),
        ),
        remote=RemoteConfig(
            enabled=bool(remote_raw.get("enabled", False)),
            bind_host=str(remote_raw.get("bind_host", "127.0.0.1")),
            port=int(remote_raw.get("port", 8765)),
            auth_token=remote_raw.get("auth_token"),
            auth_token_path=_resolve_path(remote_raw.get("auth_token_path"), base_dir),
        ),
        screen=ScreenConfig(
            artifact_dir=_resolve_path(screen_raw.get("artifact_dir"), base_dir),
            display=screen_raw.get("display"),
            framerate=int(screen_raw.get("framerate", 12)),
            default_clip_seconds=float(screen_raw.get("default_clip_seconds", 6.0)),
            screenshot_timeout_seconds=int(screen_raw.get("screenshot_timeout_seconds", 10)),
            record_timeout_seconds=int(screen_raw.get("record_timeout_seconds", 20)),
        ),
        telegram=TelegramConfig(
            enabled=bool(telegram_raw.get("enabled", False)),
            bot_token=telegram_raw.get("bot_token"),
            allowed_chat_ids=[int(value) for value in telegram_raw.get("allowed_chat_ids", [])],
            poll_timeout_seconds=int(telegram_raw.get("poll_timeout_seconds", 30)),
            voice_replies=bool(telegram_raw.get("voice_replies", True)),
        ),
        memory=MemoryConfig(
            enabled=bool(memory_raw.get("enabled", True)),
            max_entries=int(memory_raw.get("max_entries", 200)),
            summary_max_chars=int(memory_raw.get("summary_max_chars", 280)),
        ),
        persona=PersonaConfig(
            mode=str(persona_raw.get("mode", "neutral")),  # type: ignore[arg-type]
            operator_name=str(persona_raw.get("operator_name", "Reda")),
        ),
        approval=ApprovalConfig(
            desktop_prompt=bool(approval_raw.get("desktop_prompt", True)),
            prompt_backend=str(approval_raw.get("prompt_backend", "auto")),  # type: ignore[arg-type]
        ),
        benchmark=BenchmarkConfig(
            idle_false_accept_window_seconds=int(
                benchmark_raw.get("idle_false_accept_window_seconds", 1800)
            ),
            warm_target_first_audio_ms=int(benchmark_raw.get("warm_target_first_audio_ms", 1500)),
            cold_target_first_audio_ms=int(benchmark_raw.get("cold_target_first_audio_ms", 3000)),
            barge_in_target_ms=int(benchmark_raw.get("barge_in_target_ms", 250)),
        ),
    )

    if config.audio.channels != 1:
        raise ValueError("Milestone 1 only supports mono audio.")
    return config
