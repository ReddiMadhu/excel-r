"""
Structured timing logs for upload / discovery extraction profiling.

Logs to:
  - Python logger "timing" (INFO) — visible in server terminal
  - data/output/timing.log — append-only audit trail
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("timing")

_DEFAULT_LOG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "output", "timing.log")
)


def _log_path() -> str:
    return os.getenv("TIMING_LOG_PATH", _DEFAULT_LOG_PATH)


def _write_line(line: str) -> None:
    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_step(
    phase: str,
    step: str,
    elapsed_sec: float,
    *,
    scan_id: Optional[str] = None,
    file_name: Optional[str] = None,
    **extra: Any,
) -> None:
    """Log a single timed step."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ctx = []
    if scan_id:
        ctx.append(f"scan={scan_id[:8]}")
    if file_name:
        ctx.append(f"file={file_name}")
    for k, v in extra.items():
        if v is not None:
            ctx.append(f"{k}={v}")
    ctx_str = " | ".join(ctx)
    msg = f"[TIMING] {phase} | {step} | {elapsed_sec:.3f}s"
    if ctx_str:
        msg = f"{msg} | {ctx_str}"
    logger.info(msg)
    _write_line(f"{ts} | {phase} | {step} | {elapsed_sec:.6f}s | {ctx_str}")


@contextmanager
def timed_step(
    phase: str,
    step: str,
    *,
    scan_id: Optional[str] = None,
    file_name: Optional[str] = None,
    **extra: Any,
):
    """Context manager: time a block and log on exit."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log_step(
            phase,
            step,
            time.perf_counter() - t0,
            scan_id=scan_id,
            file_name=file_name,
            **extra,
        )


class PipelineTimer:
    """Accumulates steps and prints a ranked summary at the end."""

    def __init__(
        self,
        phase: str,
        *,
        scan_id: Optional[str] = None,
        file_name: Optional[str] = None,
    ):
        self.phase = phase
        self.scan_id = scan_id
        self.file_name = file_name
        self._steps: List[Tuple[str, float]] = []
        self._t0 = time.perf_counter()

    @contextmanager
    def step(self, name: str, **extra: Any):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t0
            self._steps.append((name, elapsed))
            log_step(
                self.phase,
                name,
                elapsed,
                scan_id=self.scan_id,
                file_name=self.file_name,
                **extra,
            )

    def finish(self, label: str = "TOTAL") -> float:
        total = time.perf_counter() - self._t0
        log_step(
            self.phase,
            label,
            total,
            scan_id=self.scan_id,
            file_name=self.file_name,
        )
        if self._steps:
            ranked = sorted(self._steps, key=lambda x: x[1], reverse=True)
            top = ", ".join(f"{name}:{sec:.2f}s" for name, sec in ranked[:8])
            log_step(
                self.phase,
                "SLOWEST_STEPS",
                total,
                scan_id=self.scan_id,
                file_name=self.file_name,
                breakdown=top,
            )
        return total
