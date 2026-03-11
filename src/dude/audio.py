from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Protocol

import numpy as np

from dude.config import AudioConfig


@dataclass(slots=True)
class AudioChunk:
    samples: np.ndarray


class AudioSourceExhausted(Exception):
    pass


class AudioSource(Protocol):
    async def start(self) -> None: ...

    async def read(self) -> AudioChunk: ...

    async def stop(self) -> None: ...


class AudioSink(Protocol):
    async def play(self, samples: np.ndarray, sample_rate_hz: int) -> asyncio.Task[None]: ...

    async def play_speechd(
        self,
        text: str,
        voice: str,
        language: str,
        output_module: str | None = None,
    ) -> asyncio.Task[None]: ...

    async def stop(self) -> None: ...


class AudioInput:
    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self.queue: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=128)
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        command = [
            "parec",
            "--raw",
            "--format=s16le",
            f"--rate={self.config.sample_rate_hz}",
            f"--channels={self.config.channels}",
        ]
        if self.config.input_device is not None:
            command.append(f"--device={self.config.input_device}")
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        bytes_per_chunk = self.config.block_samples * 2
        try:
            while True:
                raw = await self._process.stdout.readexactly(bytes_per_chunk)
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                if self.queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self.queue.get_nowait()
                self.queue.put_nowait(AudioChunk(samples=samples))
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            return

    async def read(self) -> AudioChunk:
        return await self.queue.get()

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            with contextlib.suppress(ProcessLookupError):
                await self._process.wait()
            self._process = None


class ReplayAudioInput:
    def __init__(
        self,
        config: AudioConfig,
        samples: np.ndarray,
        *,
        realtime: bool = False,
        tail_silence_ms: int = 0,
    ) -> None:
        self.config = config
        self.realtime = realtime
        self._started = False
        self._index = 0
        prepared = np.asarray(samples, dtype=np.float32)
        if tail_silence_ms > 0:
            tail_samples = int(config.sample_rate_hz * (tail_silence_ms / 1000))
            prepared = np.concatenate(
                [prepared, np.zeros(tail_samples, dtype=np.float32)]
            ).astype(np.float32)
        chunk_size = config.block_samples
        if prepared.size and prepared.size % chunk_size:
            prepared = np.pad(prepared, (0, chunk_size - (prepared.size % chunk_size)))
        self._chunks = [
            prepared[offset : offset + chunk_size].astype(np.float32)
            for offset in range(0, prepared.size, chunk_size)
        ]

    async def start(self) -> None:
        self._started = True
        self._index = 0

    async def read(self) -> AudioChunk:
        if not self._started:
            raise RuntimeError("ReplayAudioInput must be started before reading.")
        if self._index >= len(self._chunks):
            raise AudioSourceExhausted()
        if self.realtime and self._index > 0:
            await asyncio.sleep(self.config.block_duration_ms / 1000)
        chunk = self._chunks[self._index]
        self._index += 1
        return AudioChunk(samples=chunk)

    async def stop(self) -> None:
        self._started = False


class AudioOutput:
    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._play_task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._temp_path: Path | None = None

    async def play(self, samples: np.ndarray, sample_rate_hz: int) -> asyncio.Task[None]:
        await self.stop()
        fd, path = tempfile.mkstemp(prefix="dude-", suffix=".wav")
        self._temp_path = Path(path)
        with os.fdopen(fd, "wb") as raw_handle:
            with wave.open(raw_handle, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sample_rate_hz)
                pcm = np.clip(samples, -1.0, 1.0)
                handle.writeframes((pcm * 32767).astype(np.int16).tobytes())
        self._process = await asyncio.create_subprocess_exec(
            "paplay",
            str(self._temp_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def _runner() -> None:
            assert self._process is not None
            await self._process.wait()
            self._cleanup_temp()

        self._play_task = asyncio.create_task(_runner())
        return self._play_task

    async def play_speechd(
        self,
        text: str,
        voice: str,
        language: str,
        output_module: str | None = None,
    ) -> asyncio.Task[None]:
        await self.stop()
        command = ["spd-say", "-w", "-l", language, "-t", voice, text]
        if output_module:
            command[1:1] = ["-o", output_module]
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def _runner() -> None:
            assert self._process is not None
            await self._process.wait()

        self._play_task = asyncio.create_task(_runner())
        return self._play_task

    async def stop(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            with contextlib.suppress(ProcessLookupError):
                await self._process.wait()
        self._process = None
        if self._play_task is not None:
            self._play_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._play_task
            self._play_task = None
        self._cleanup_temp()

    def _cleanup_temp(self) -> None:
        if self._temp_path is not None and self._temp_path.exists():
            self._temp_path.unlink()
        self._temp_path = None


class CaptureAudioOutput:
    def __init__(self, config: AudioConfig, *, simulate_realtime: bool = False) -> None:
        self.config = config
        self.simulate_realtime = simulate_realtime
        self.records: list[dict[str, object]] = []
        self._play_task: asyncio.Task[None] | None = None
        self._active_record: dict[str, object] | None = None

    async def play(self, samples: np.ndarray, sample_rate_hz: int) -> asyncio.Task[None]:
        await self.stop()
        duration_seconds = float(samples.shape[0] / sample_rate_hz) if sample_rate_hz else 0.0
        record: dict[str, object] = {
            "backend": "capture",
            "sample_rate_hz": sample_rate_hz,
            "sample_count": int(samples.shape[0]),
            "duration_ms": round(duration_seconds * 1000, 2),
            "stopped": False,
        }
        self.records.append(record)
        self._active_record = record

        async def _runner() -> None:
            try:
                if self.simulate_realtime and duration_seconds > 0:
                    await asyncio.sleep(duration_seconds)
            finally:
                self._active_record = None

        self._play_task = asyncio.create_task(_runner())
        return self._play_task

    async def play_speechd(
        self,
        text: str,
        voice: str,
        language: str,
        output_module: str | None = None,
    ) -> asyncio.Task[None]:
        del voice, language, output_module
        await self.stop()
        duration_seconds = max(0.45, min(2.0, len(text) / 18))
        record: dict[str, object] = {
            "backend": "speechd",
            "text": text,
            "duration_ms": round(duration_seconds * 1000, 2),
            "stopped": False,
        }
        self.records.append(record)
        self._active_record = record

        async def _runner() -> None:
            try:
                if self.simulate_realtime and duration_seconds > 0:
                    await asyncio.sleep(duration_seconds)
            finally:
                self._active_record = None

        self._play_task = asyncio.create_task(_runner())
        return self._play_task

    async def stop(self) -> None:
        if self._play_task is not None and not self._play_task.done():
            if self._active_record is not None:
                self._active_record["stopped"] = True
            self._play_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._play_task
        self._play_task = None
        self._active_record = None


class AudioRingBuffer:
    def __init__(self, max_seconds: float, sample_rate_hz: int) -> None:
        self.max_samples = int(max_seconds * sample_rate_hz)
        self._frames: Deque[np.ndarray] = deque()
        self._sample_count = 0

    def append(self, samples: np.ndarray) -> None:
        self._frames.append(samples)
        self._sample_count += len(samples)
        while self._sample_count > self.max_samples and self._frames:
            removed = self._frames.popleft()
            self._sample_count -= len(removed)

    def concat(self) -> np.ndarray:
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(list(self._frames)).astype(np.float32)
