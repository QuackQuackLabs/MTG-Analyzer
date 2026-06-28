"""In-process background-job runner for long simulations.

The metagame sweep / 1v1 matrix / sensitivity scan take minutes — too long for a synchronous web
request. This is the seam the web API submits them to: `submit()` returns a job id immediately, the
work runs on a thread pool, and the client polls `get(id)` for status / progress / result.

UI-agnostic (no FastAPI dependency): the API owns a `JobRunner`, submits `lambda report: svc.metagame(
…, on_progress=report)`, and serializes the polled `Job` via `service.to_jsonable`. The submitted
callable receives a `report(fraction, message)` callback to publish progress.
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

JobStatus = Literal["pending", "running", "done", "error"]

# A job body: receives a progress reporter `report(fraction_0_to_1, message)` and returns its result.
Progress = Callable[[float, str], None]
JobFn = Callable[[Progress], Any]


@dataclass
class Job:
    id: str
    label: str
    status: JobStatus = "pending"
    progress: float = 0.0            # 0.0 → 1.0
    message: str = ""
    result: Any | None = None
    error: str | None = None


class JobRunner:
    """Thread-pool job runner with pollable status/progress. Thread-safe; results live in memory until
    the runner is discarded (single-user/local scope — no persistence needed yet)."""

    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mtg-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, fn: JobFn, *, label: str = "") -> str:
        job = Job(id=uuid.uuid4().hex, label=label)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, fn)
        return job.id

    def _run(self, job: Job, fn: JobFn) -> None:
        def report(fraction: float, message: str = "") -> None:
            with self._lock:
                job.progress = max(0.0, min(1.0, fraction))
                if message:
                    job.message = message
        with self._lock:
            job.status = "running"
        try:
            result = fn(report)
            with self._lock:
                job.result = result
                job.progress = 1.0
                job.status = "done"
        except Exception as e:  # noqa: BLE001 — surface any failure to the poller, don't crash the pool
            with self._lock:
                job.error = f"{type(e).__name__}: {e}"
                job.status = "error"

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def shutdown(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait)
