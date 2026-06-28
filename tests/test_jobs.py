"""Background job runner — the seam the web API submits long sims to."""
import time

from mtg_analyzer.jobs import JobRunner


def _wait(runner: JobRunner, job_id: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = runner.get(job_id)
        if job and job.status in ("done", "error"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish in time")


def test_job_runs_reports_progress_and_returns_result() -> None:
    runner = JobRunner(max_workers=2)
    try:
        def task(report):
            report(0.5, "halfway")
            return {"answer": 42}
        jid = runner.submit(task, label="demo")
        job = _wait(runner, jid)
        assert job.status == "done"
        assert job.result == {"answer": 42}
        assert job.progress == 1.0
        assert job.label == "demo"
        assert jid in {j.id for j in runner.list()}
    finally:
        runner.shutdown()


def test_job_captures_error_without_crashing_pool() -> None:
    runner = JobRunner()
    try:
        def boom(report):
            raise ValueError("nope")
        job = _wait(runner, runner.submit(boom))
        assert job.status == "error"
        assert "ValueError" in (job.error or "") and "nope" in (job.error or "")
        # the pool still works after a failed job
        ok = _wait(runner, runner.submit(lambda report: 1))
        assert ok.status == "done" and ok.result == 1
    finally:
        runner.shutdown()
