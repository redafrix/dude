from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import soundfile as sf
import yaml

from dude.audio import AudioInput, CaptureAudioOutput, ReplayAudioInput
from dude.backends.asr import FasterWhisperBackend
from dude.backends.tts import SpeechSynthesizer
from dude.config import DudeConfig
from dude.events import AssistantState, AssistantStatus
from dude.metrics import collect_resource_snapshot, write_benchmark_result
from dude.normalize import TranscriptNormalizer
from dude.pipeline import VoicePipeline
from dude.wake import PhraseWakeDetector, build_stream_wake_detector


@dataclass(slots=True)
class FixtureCase:
    fixture_id: str
    path: Path
    scenario: str = "generic"
    expected_wake: bool | None = None
    expected_transcript_contains: list[str] = field(default_factory=list)
    expected_response_contains: list[str] = field(default_factory=list)


def _load_audio(path: Path, target_rate_hz: int) -> np.ndarray:
    samples, sample_rate_hz = sf.read(path, always_2d=False)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if sample_rate_hz == target_rate_hz:
        return samples.astype(np.float32)
    new_length = int(round(len(samples) * target_rate_hz / sample_rate_hz))
    source_idx = np.arange(len(samples), dtype=np.float32)
    target_idx = np.linspace(0, max(len(samples) - 1, 0), num=new_length, dtype=np.float32)
    return np.interp(target_idx, source_idx, samples).astype(np.float32)


def load_fixture_manifest(path: Path) -> list[FixtureCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw_cases = raw.get("cases", [])
    else:
        raw_cases = raw
    cases: list[FixtureCase] = []
    base_dir = path.parent
    for item in raw_cases:
        fixture_path = (base_dir / item["path"]).resolve()
        transcript_contains = item.get("expected_transcript_contains", [])
        if isinstance(transcript_contains, str):
            transcript_contains = [transcript_contains]
        response_contains = item.get("expected_response_contains", [])
        if isinstance(response_contains, str):
            response_contains = [response_contains]
        cases.append(
            FixtureCase(
                fixture_id=str(item["id"]),
                path=fixture_path,
                scenario=str(item.get("scenario", "generic")),
                expected_wake=item.get("expected_wake"),
                expected_transcript_contains=[str(part).lower() for part in transcript_contains],
                expected_response_contains=[str(part).lower() for part in response_contains],
            )
        )
    return cases


async def record_fixture(
    config: DudeConfig,
    output_path: Path,
    duration_seconds: float,
) -> dict[str, Any]:
    audio_input = AudioInput(config.audio)
    await audio_input.start()
    total_samples = int(config.audio.sample_rate_hz * duration_seconds)
    captured: list[np.ndarray] = []
    collected = 0
    try:
        while collected < total_samples:
            chunk = await audio_input.read()
            captured.append(chunk.samples)
            collected += len(chunk.samples)
    finally:
        await audio_input.stop()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.concatenate(captured)[:total_samples].astype(np.float32)
    sf.write(output_path, audio, config.audio.sample_rate_hz)
    return {
        "output_path": str(output_path),
        "duration_seconds": round(len(audio) / config.audio.sample_rate_hz, 3),
        "sample_rate_hz": config.audio.sample_rate_hz,
    }


async def record_wake_enrollment(
    config: DudeConfig,
    output_dir: Path,
    *,
    phrase: str,
    take_count: int,
    duration_seconds: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    takes: list[dict[str, Any]] = []
    for index in range(1, take_count + 1):
        output_path = output_dir / f"wake-{index:03d}.wav"
        fixture = await record_fixture(config, output_path, duration_seconds)
        takes.append(
            {
                "id": f"wake-{index:03d}",
                "phrase": phrase,
                "path": output_path.name,
                "duration_seconds": fixture["duration_seconds"],
            }
        )

    manifest = {
        "kind": "wake_enrollment",
        "phrase": phrase,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "take_count": take_count,
        "sample_rate_hz": config.audio.sample_rate_hz,
        "takes": takes,
    }
    manifest_path = output_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "manifest_path": str(manifest_path),
        "take_count": take_count,
        "phrase": phrase,
        "takes": takes,
    }


def _stream_wake_metrics(
    config: DudeConfig,
    samples: np.ndarray,
    logger: logging.Logger,
) -> dict[str, Any]:
    detector = build_stream_wake_detector(config.wake_word, logger)
    if detector is None:
        return {"backend": "transcript", "triggered": None, "max_score": None, "trigger_ms": None}

    chunk_size = config.audio.block_samples
    max_score = 0.0
    trigger_ms: float | None = None
    for offset in range(0, len(samples), chunk_size):
        chunk = samples[offset : offset + chunk_size]
        if len(chunk) < chunk_size:
            chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
        event = detector.process_chunk(chunk.astype(np.float32))
        max_score = max(max_score, event.score)
        if event.triggered and trigger_ms is None:
            trigger_ms = round((offset / config.audio.sample_rate_hz) * 1000, 2)
    detector.reset()
    return {
        "backend": event.backend if "event" in locals() else "openwakeword",
        "triggered": trigger_ms is not None,
        "max_score": round(max_score, 4),
        "trigger_ms": trigger_ms,
    }


def benchmark_backends(
    config: DudeConfig,
    logger: logging.Logger,
    *,
    fixture_path: Path | None = None,
    benchmark_text: str = "Hi, what can I help you with?",
) -> dict[str, Any]:
    fixture_audio = (
        _load_audio(fixture_path, config.audio.sample_rate_hz) if fixture_path is not None else None
    )

    asr_backend = FasterWhisperBackend(config.asr, logger)
    normalizer = TranscriptNormalizer(config.normalization)
    start = perf_counter()
    asr_backend.warmup()
    asr_load_ms = round((perf_counter() - start) * 1000, 2)

    asr_metrics: dict[str, Any] = {
        "load_ms": asr_load_ms,
        "fixture": str(fixture_path) if fixture_path else None,
        "device": asr_backend.device_in_use,
        "compute_type": asr_backend.compute_type_in_use,
    }
    if fixture_audio is not None:
        start = perf_counter()
        transcript = asr_backend.transcribe(fixture_audio, config.audio.sample_rate_hz)
        asr_metrics["transcribe_ms"] = round((perf_counter() - start) * 1000, 2)
        asr_metrics["transcript"] = normalizer.normalize(transcript.text).text
        asr_metrics["raw_transcript"] = transcript.text
        asr_metrics["device"] = asr_backend.device_in_use
        asr_metrics["compute_type"] = asr_backend.compute_type_in_use

    tts_backend = SpeechSynthesizer(config.tts, logger)
    start = perf_counter()
    speech = tts_backend.synthesize(benchmark_text)
    cold_tts_ms = round((perf_counter() - start) * 1000, 2)
    start = perf_counter()
    warm_speech = tts_backend.synthesize(benchmark_text)
    warm_tts_ms = round((perf_counter() - start) * 1000, 2)

    payload = {
        "fixture": str(fixture_path) if fixture_path else None,
        "asr": asr_metrics,
        "tts": {
            "cold_ms": cold_tts_ms,
            "warm_ms": warm_tts_ms,
            "backend": speech.backend,
            "sample_rate_hz": speech.sample_rate_hz,
            "samples": int(warm_speech.samples.shape[0]),
        },
        "resources": collect_resource_snapshot(),
    }
    return payload


def evaluate_fixtures(
    config: DudeConfig,
    manifest_path: Path,
    logger: logging.Logger,
) -> dict[str, Any]:
    cases = load_fixture_manifest(manifest_path)
    asr_backend = FasterWhisperBackend(config.asr, logger)
    normalizer = TranscriptNormalizer(config.normalization)
    transcript_wake = PhraseWakeDetector(config.activation.wake_word)
    results: list[dict[str, Any]] = []

    wake_expected = 0
    wake_passed = 0
    transcript_passed = 0

    for case in cases:
        audio = _load_audio(case.path, config.audio.sample_rate_hz)
        start = perf_counter()
        transcript = asr_backend.transcribe(audio, config.audio.sample_rate_hz)
        asr_ms = round((perf_counter() - start) * 1000, 2)
        raw_transcript = transcript.text.strip()
        transcript_text = normalizer.normalize(raw_transcript).text
        wake_decision = transcript_wake.detect(raw_transcript)
        stream_wake = _stream_wake_metrics(config, audio, logger)

        transcript_ok = all(
            part in transcript_text.lower() for part in case.expected_transcript_contains
        )
        if transcript_ok:
            transcript_passed += 1

        wake_ok: bool | None
        if case.expected_wake is None:
            wake_ok = None
        else:
            wake_expected += 1
            actual_wake = (
                bool(stream_wake["triggered"])
                if stream_wake["triggered"] is not None
                else wake_decision.triggered
            )
            wake_ok = actual_wake == case.expected_wake
            if wake_ok:
                wake_passed += 1

        results.append(
            {
                "id": case.fixture_id,
                "path": str(case.path),
                "raw_transcript": raw_transcript,
                "transcript": transcript_text,
                "asr_ms": asr_ms,
                "asr_device": asr_backend.device_in_use,
                "expected_wake": case.expected_wake,
                "wake_transcript": wake_decision.triggered,
                "wake_stream": stream_wake,
                "wake_ok": wake_ok,
                "expected_transcript_contains": case.expected_transcript_contains,
                "transcript_ok": transcript_ok,
            }
        )

    return {
        "manifest_path": str(manifest_path),
        "case_count": len(results),
        "wake_expected_count": wake_expected,
        "wake_pass_count": wake_passed,
        "transcript_pass_count": transcript_passed,
        "results": results,
        "resources": collect_resource_snapshot(),
    }


@dataclass(slots=True)
class _PipelineObserverCollector:
    wake_events: list[dict[str, object]] = field(default_factory=list)
    utterances: list[dict[str, object]] = field(default_factory=list)
    barge_in_events: list[dict[str, object]] = field(default_factory=list)
    playback_events: list[dict[str, object]] = field(default_factory=list)

    def __call__(self, event: str, payload: dict[str, object]) -> None:
        if event == "wake_word_detected":
            self.wake_events.append(dict(payload))
        elif event == "utterance_processed":
            self.utterances.append(dict(payload))
        elif event == "barge_in_detected":
            self.barge_in_events.append(dict(payload))
        elif event == "playback_started":
            self.playback_events.append(dict(payload))


async def evaluate_pipeline(
    config: DudeConfig,
    manifest_path: Path,
    logger: logging.Logger,
    *,
    wake_backend: str | None = None,
    realtime: bool = False,
) -> dict[str, Any]:
    cases = load_fixture_manifest(manifest_path)
    eval_config = copy.deepcopy(config)
    if wake_backend is not None:
        eval_config.wake_word.backend = wake_backend  # type: ignore[assignment]

    asr_backend = FasterWhisperBackend(eval_config.asr, logger)
    tts_backend = SpeechSynthesizer(eval_config.tts, logger)
    asr_backend.warmup()

    results: list[dict[str, Any]] = []
    wake_expected_count = 0
    wake_pass_count = 0
    transcript_expected_count = 0
    transcript_pass_count = 0
    response_expected_count = 0
    response_pass_count = 0
    barge_in_case_count = 0
    barge_in_detected_count = 0
    scenario_summary: dict[str, dict[str, int]] = {}

    for case in cases:
        audio = _load_audio(case.path, eval_config.audio.sample_rate_hz)
        case_realtime = realtime or case.scenario == "barge_in"
        source = ReplayAudioInput(
            eval_config.audio,
            audio,
            realtime=case_realtime,
            tail_silence_ms=eval_config.vad.min_silence_ms + eval_config.audio.block_duration_ms,
        )
        sink = CaptureAudioOutput(eval_config.audio, simulate_realtime=case_realtime)
        observer = _PipelineObserverCollector()
        status = AssistantStatus(state=AssistantState.ARMED, armed=True)
        pipeline = VoicePipeline(
            eval_config,
            logger,
            status,
            audio_input=source,
            audio_output=sink,
            asr=asr_backend,
            tts=tts_backend,
            observer=observer,
        )

        await pipeline.start()
        try:
            await pipeline.run()
        finally:
            await pipeline.stop()

        utterances = observer.utterances
        transcripts = " ".join(str(item.get("transcript", "")) for item in utterances).lower()
        responses = " ".join(str(item.get("response_text", "")) for item in utterances).lower()
        actual_wake = bool(observer.wake_events) or any(
            bool(item.get("matched_wake_word")) for item in utterances
        )

        wake_ok: bool | None
        if case.expected_wake is None:
            wake_ok = None
        else:
            wake_expected_count += 1
            wake_ok = actual_wake == case.expected_wake
            if wake_ok:
                wake_pass_count += 1

        transcript_ok: bool | None = None
        if case.expected_transcript_contains:
            transcript_expected_count += 1
            transcript_ok = all(part in transcripts for part in case.expected_transcript_contains)
            if transcript_ok:
                transcript_pass_count += 1

        response_ok: bool | None = None
        if case.expected_response_contains:
            response_expected_count += 1
            response_ok = all(part in responses for part in case.expected_response_contains)
            if response_ok:
                response_pass_count += 1

        if case.scenario == "barge_in":
            barge_in_case_count += 1
            if observer.barge_in_events:
                barge_in_detected_count += 1

        scenario_metrics = scenario_summary.setdefault(case.scenario, {"cases": 0, "wake_pass": 0})
        scenario_metrics["cases"] += 1
        if wake_ok:
            scenario_metrics["wake_pass"] += 1

        results.append(
            {
                "id": case.fixture_id,
                "scenario": case.scenario,
                "path": str(case.path),
                "expected_wake": case.expected_wake,
                "wake_triggered": actual_wake,
                "wake_ok": wake_ok,
                "wake_events": observer.wake_events,
                "utterance_count": len(utterances),
                "utterances": utterances,
                "transcript_ok": transcript_ok,
                "response_ok": response_ok,
                "barge_in_detected": bool(observer.barge_in_events),
                "barge_in_events": observer.barge_in_events,
                "playback": sink.records,
            }
        )

    return {
        "manifest_path": str(manifest_path),
        "wake_backend": eval_config.wake_word.backend,
        "realtime": realtime,
        "case_count": len(results),
        "wake_expected_count": wake_expected_count,
        "wake_pass_count": wake_pass_count,
        "transcript_expected_count": transcript_expected_count,
        "transcript_pass_count": transcript_pass_count,
        "response_expected_count": response_expected_count,
        "response_pass_count": response_pass_count,
        "barge_in_case_count": barge_in_case_count,
        "barge_in_detected_count": barge_in_detected_count,
        "scenario_summary": scenario_summary,
        "results": results,
        "resources": collect_resource_snapshot(),
    }


def write_named_report(output_path: Path, payload: dict[str, Any]) -> Path:
    write_benchmark_result(output_path, payload)
    return output_path
