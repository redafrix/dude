from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

import psutil


@dataclass(slots=True)
class LatencyRecorder:
    marks: dict[str, float] = field(default_factory=dict)
    started_at: float = field(default_factory=monotonic)

    def mark(self, name: str) -> None:
        self.marks[name] = monotonic()

    def to_deltas_ms(self) -> dict[str, float]:
        if not self.marks:
            return {}
        return {
            name: round((mark - self.started_at) * 1000, 2)
            for name, mark in sorted(self.marks.items(), key=lambda item: item[1])
        }


def collect_resource_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_used_mb": round(psutil.virtual_memory().used / (1024 * 1024), 2),
        "ram_available_mb": round(psutil.virtual_memory().available / (1024 * 1024), 2),
    }
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
        )
        lines = result.stdout.strip().splitlines()
        if lines:
            util, memory_used, memory_total = [segment.strip() for segment in lines[0].split(",")]
            snapshot.update(
                {
                    "gpu_percent": float(util),
                    "vram_used_mb": float(memory_used),
                    "vram_total_mb": float(memory_total),
                }
            )
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        snapshot["gpu_percent"] = None
    return snapshot


def write_benchmark_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

