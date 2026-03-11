from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable

import numpy as np

from dude.audio import (
    AudioInput,
    AudioOutput,
    AudioRingBuffer,
    AudioSink,
    AudioSource,
    AudioSourceExhausted,
)
from dude.backends.asr import FasterWhisperBackend
from dude.backends.tts import SpeechSynthesizer
from dude.backends.vad import SileroVadBackend
from dude.config import DudeConfig
from dude.events import AssistantState, AssistantStatus
from dude.logging import log_event
from dude.metrics import LatencyRecorder
from dude.normalize import TranscriptNormalizer
from dude.wake import PhraseWakeDetector, build_stream_wake_detector

PipelineObserver = Callable[[str, dict[str, object]], None]
CommandHandler = Callable[[str], Awaitable[str]]


@dataclass(slots=True)
class ProcessedUtterance:
    raw_transcript: str
    transcript: str
    matched_wake_word: bool
    command_text: str
    response_text: str | None
    metrics: dict[str, float]
    capture_mode: str
    wake_backend: str
    asr_device: str


class VoicePipeline:
    def __init__(
        self,
        config: DudeConfig,
        logger: logging.Logger,
        status: AssistantStatus,
        *,
        audio_input: AudioSource | None = None,
        audio_output: AudioSink | None = None,
        vad: SileroVadBackend | None = None,
        asr: FasterWhisperBackend | None = None,
        tts: SpeechSynthesizer | None = None,
        wake: PhraseWakeDetector | None = None,
        stream_wake=None,
        normalizer: TranscriptNormalizer | None = None,
        command_handler: CommandHandler | None = None,
        observer: PipelineObserver | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.status = status
        self.audio_input = audio_input or AudioInput(config.audio)
        self.audio_output = audio_output or AudioOutput(config.audio)
        self.vad = vad or SileroVadBackend(config.vad.threshold)
        self.asr = asr or FasterWhisperBackend(config.asr, logger)
        self.tts = tts or SpeechSynthesizer(config.tts, logger)
        self.wake = wake or PhraseWakeDetector(config.activation.wake_word)
        self.stream_wake = stream_wake if stream_wake is not None else build_stream_wake_detector(
            config.wake_word, logger
        )
        self.normalizer = normalizer or TranscriptNormalizer(config.normalization)
        self.command_handler = command_handler
        self.observer = observer
        self._running = False
        self._follow_up_deadline = 0.0
        self._last_playback_started_at = 0.0
        self._playback_watch_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.audio_input.start()
        self._running = True
        log_event(
            self.logger,
            "voice_pipeline_started",
            sample_rate_hz=self.config.audio.sample_rate_hz,
        )

    async def stop(self) -> None:
        self._running = False
        await self.audio_output.stop()
        await self.audio_input.stop()
        log_event(self.logger, "voice_pipeline_stopped")

    def warmup(self) -> None:
        self.asr.warmup()

    def _emit_observer(self, event: str, **payload: object) -> None:
        if self.observer is not None:
            self.observer(event, payload)

    async def run(self) -> None:
        pre_roll = AudioRingBuffer(
            self.config.audio.pre_roll_seconds,
            self.config.audio.sample_rate_hz,
        )
        current_frames: list[np.ndarray] = []
        speech_active = False
        silence_run_ms = 0
        capture_mode = "idle"
        capture_started_at = 0.0
        capture_wake_backend = "transcript"
        max_samples = int(self.config.audio.max_request_seconds * self.config.audio.sample_rate_hz)

        while self._running:
            try:
                chunk = await self.audio_input.read()
            except AudioSourceExhausted:
                if speech_active and current_frames:
                    audio = np.concatenate(current_frames).astype(np.float32)
                    await self._process_utterance(
                        audio,
                        capture_mode,
                        capture_started_at,
                        capture_wake_backend,
                    )
                self._running = False
                break
            pre_roll.append(chunk.samples)
            vad_result = self.vad.detect(chunk.samples)

            if self.status.speaking and vad_result.is_speech:
                elapsed_ms = (monotonic() - self._last_playback_started_at) * 1000
                if elapsed_ms > self.config.audio.barge_in_grace_ms:
                    await self.audio_output.stop()
                    self.status.speaking = False
                    self.status.state = (
                        AssistantState.ARMED if self.status.armed else AssistantState.IDLE
                    )
                    log_event(self.logger, "barge_in_detected", elapsed_ms=round(elapsed_ms, 2))
                    self._emit_observer("barge_in_detected", elapsed_ms=round(elapsed_ms, 2))

            if not self.status.armed:
                current_frames.clear()
                speech_active = False
                silence_run_ms = 0
                capture_mode = "idle"
                capture_started_at = 0.0
                capture_wake_backend = "transcript"
                if self.stream_wake is not None:
                    self.stream_wake.reset()
                continue

            follow_up_active = monotonic() < self._follow_up_deadline

            if self.stream_wake is not None and not speech_active and not follow_up_active:
                wake_event = self.stream_wake.process_chunk(chunk.samples)
                if wake_event.triggered:
                    current_frames = [pre_roll.concat(), chunk.samples]
                    speech_active = True
                    silence_run_ms = 0
                    capture_mode = "wake_stream"
                    capture_started_at = monotonic()
                    capture_wake_backend = wake_event.backend
                    self.status.state = AssistantState.WAKE_DETECTED
                    log_event(
                        self.logger,
                        "wake_word_detected",
                        backend=wake_event.backend,
                        label=wake_event.label,
                        score=round(wake_event.score, 4),
                    )
                    self._emit_observer(
                        "wake_word_detected",
                        backend=wake_event.backend,
                        label=wake_event.label,
                        score=round(wake_event.score, 4),
                    )
                    continue

            should_capture = speech_active or follow_up_active or self.stream_wake is None
            if vad_result.is_speech and should_capture:
                if not speech_active:
                    current_frames = [pre_roll.concat()]
                    speech_active = True
                    silence_run_ms = 0
                    capture_mode = "follow_up" if follow_up_active else "transcript_gate"
                    capture_started_at = monotonic()
                    capture_wake_backend = "follow_up" if follow_up_active else "transcript"
                    self.status.state = AssistantState.RECORDING_REQUEST
                current_frames.append(chunk.samples)
                if sum(len(frame) for frame in current_frames) >= max_samples:
                    speech_active = False
                    silence_run_ms = 0
                    audio = np.concatenate(current_frames).astype(np.float32)
                    current_frames.clear()
                    current_mode = capture_mode
                    capture_mode = "idle"
                    await self._process_utterance(
                        audio,
                        current_mode,
                        capture_started_at,
                        capture_wake_backend,
                    )
                    if self.stream_wake is not None:
                        self.stream_wake.reset()
                continue

            if speech_active:
                current_frames.append(chunk.samples)
                silence_run_ms += self.config.audio.block_duration_ms
                if silence_run_ms >= self.config.vad.min_silence_ms:
                    speech_active = False
                    silence_run_ms = 0
                    audio = np.concatenate(current_frames).astype(np.float32)
                    current_frames.clear()
                    current_mode = capture_mode
                    capture_mode = "idle"
                    await self._process_utterance(
                        audio,
                        current_mode,
                        capture_started_at,
                        capture_wake_backend,
                    )
                    if self.stream_wake is not None:
                        self.stream_wake.reset()

    async def _process_utterance(
        self,
        samples: np.ndarray,
        capture_mode: str,
        capture_started_at: float,
        wake_backend_hint: str,
    ) -> ProcessedUtterance:
        recorder = LatencyRecorder(started_at=capture_started_at or monotonic())
        transcript = await asyncio.to_thread(
            self.asr.transcribe,
            samples,
            self.config.audio.sample_rate_hz,
        )
        recorder.mark("asr_final")
        raw_transcript = transcript.text.strip()
        normalized_transcript = self.normalizer.normalize(raw_transcript).text
        matched_wake_word = False
        command_text = ""
        wake_backend = wake_backend_hint
        wake_match = self.wake.detect(raw_transcript)

        if capture_mode == "follow_up":
            matched_wake_word = True
            command_text = self.normalizer.normalize(raw_transcript).text
            wake_backend = "follow_up"
        elif capture_mode == "wake_stream":
            matched_wake_word = True
            raw_command = wake_match.remainder.strip() if wake_match.triggered else raw_transcript
            command_text = (
                self.normalizer.normalize(raw_command).text
            )
            wake_backend = wake_backend_hint
        elif wake_match.triggered:
            matched_wake_word = True
            command_text = self.normalizer.normalize(wake_match.remainder.strip()).text
            wake_backend = wake_match.backend
            recorder.mark("wake_detected")
        else:
            wake_backend = "none"

        response_text: str | None = None
        if matched_wake_word:
            self.status.state = AssistantState.THINKING
            response_text = await self._build_response(command_text)
            recorder.mark("response_ready")
            await self._speak(response_text)
            recorder.mark("tts_first_audio")
            self._follow_up_deadline = (
                monotonic() + self.config.activation.follow_up_timeout_seconds
            )
        else:
            self.status.state = AssistantState.ARMED

        self.status.last_transcript = normalized_transcript
        self.status.last_response = response_text or ""
        metrics = recorder.to_deltas_ms()
        log_event(
            self.logger,
            "utterance_processed",
            raw_transcript=raw_transcript,
            transcript=normalized_transcript,
            matched_wake_word=matched_wake_word,
            command_text=command_text,
            response_text=response_text,
            metrics=metrics,
        )
        processed = ProcessedUtterance(
            raw_transcript,
            normalized_transcript,
            matched_wake_word,
            command_text,
            response_text,
            metrics,
            capture_mode,
            wake_backend,
            self.asr.device_in_use or "unknown",
        )
        self._emit_observer(
            "utterance_processed",
            raw_transcript=processed.raw_transcript,
            transcript=processed.transcript,
            matched_wake_word=processed.matched_wake_word,
            command_text=processed.command_text,
            response_text=processed.response_text or "",
            metrics=processed.metrics,
            capture_mode=processed.capture_mode,
            wake_backend=processed.wake_backend,
            asr_device=processed.asr_device,
        )
        return processed

    async def _build_response(self, command_text: str) -> str:
        command = command_text.strip().lower()
        if not command:
            return self.config.activation.greeting_text
        if any(token in command for token in ("hello", "hi", "hey")):
            return self.config.activation.greeting_text
        if "stop" in command:
            self.status.armed = False
            self.status.state = AssistantState.IDLE
            return "Stopping. Say Alt plus A when you want me again."
        if "status" in command:
            return f"I am {self.status.state.value.replace('_', ' ')} and listening."
        if self.command_handler is not None:
            return await self.command_handler(command_text)
        return "I heard you. Milestone one only supports greeting and control commands so far."

    async def _speak(self, text: str) -> None:
        self.status.speaking = True
        self.status.state = AssistantState.SPEAKING
        self._last_playback_started_at = monotonic()
        if self._playback_watch_task is not None:
            self._playback_watch_task.cancel()
        if self.config.tts.provider == "speechd":
            play_task = await self.audio_output.play_speechd(
                text=text,
                voice=self.config.tts.voice,
                language=self.config.tts.speechd_language,
                output_module=self.config.tts.speechd_output_module,
            )
            self._emit_observer(
                "playback_started",
                backend="speechd",
                text=text,
            )
        else:
            speech = await asyncio.to_thread(self.tts.synthesize, text)
            play_task = await self.audio_output.play(speech.samples, speech.sample_rate_hz)
            self._emit_observer(
                "playback_started",
                backend=speech.backend,
                text=text,
                sample_rate_hz=speech.sample_rate_hz,
                sample_count=int(speech.samples.shape[0]),
            )
        self._playback_watch_task = asyncio.create_task(self._watch_playback(play_task))

    async def _watch_playback(self, play_task: asyncio.Task[None]) -> None:
        try:
            await play_task
        except asyncio.CancelledError:
            return
        finally:
            self.status.speaking = False
            if self.status.armed:
                self.status.state = AssistantState.ARMED
