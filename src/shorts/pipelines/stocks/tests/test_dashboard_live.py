"""Unit tests for the live-dashboard work: schedule countdown + per-stage job
progress parsing. Offline — the job watcher is driven with a fake process."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from shorts.pipelines.stocks.schedule import SCHEDULE_UTC_HOURS, next_runs


# ── Part 1: schedule.next_runs ─────────────────────────────────────────────────

def test_next_runs_rolls_over_day() -> None:
    now = datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc)  # just after the 12:00 slot
    r = next_runs(3, now=now)
    assert [(d.day, d.hour) for d in r] == [(1, 15), (1, 18), (2, 6)]
    assert all(r[i] < r[i + 1] for i in range(len(r) - 1))
    assert all(d.tzinfo is not None for d in r)


def test_next_runs_before_first_slot() -> None:
    now = datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc)
    r = next_runs(5, now=now)
    assert [(d.day, d.hour) for d in r] == [(1, 6), (1, 9), (1, 12), (1, 15), (1, 18)]


def test_schedule_hours_match_workflow() -> None:
    # Guards against silent drift from the documented cron in autopilot.yml.
    assert SCHEDULE_UTC_HOURS == (6, 9, 12, 15, 18)


# ── Part 2: per-stage progress in the job watcher ──────────────────────────────

class _FakeProc:
    """Minimal subprocess.Popen stand-in for _watch."""
    def __init__(self, lines: list[str], returncode: int = 0):
        self.stdout = io.BytesIO("".join(l + "\n" for l in lines).encode("utf-8"))
        self.pid = 4321
        self._rc = returncode

    def wait(self) -> int:
        return self._rc


def test_watch_advances_stages(tmp_path, monkeypatch) -> None:
    from shorts.core import jobs as job_mod

    # Redirect the jobs.json to a temp dir.
    monkeypatch.setattr(job_mod, "_jobs_path", lambda pipeline: tmp_path / "jobs.json")

    patterns = [
        ("topic =", "Researching the topic…"),
        ("script written", "Writing the script…"),
        ("synthesizing voice", "Recording the voiceover…"),
        ("done.", "Wrapping up…"),
    ]
    pipeline = "stocks"
    # Seed a running job record (as start() would).
    job = {
        "id": "job1", "kind": "daily-run", "label": "x", "started_at": "t",
        "pid": 4321, "status": "running", "finished_at": None, "exit_code": None,
        "log_tail": "", "stage_label": "Queued…", "stage_idx": 0,
        "stage_total": len(patterns),
    }
    job_mod._save(pipeline, [job])

    lines = [
        "INFO [20260601_en_nvda] topic = 12 (primary NVDA)",
        "INFO [20260601_en_nvda] TTS done: 1.0s",   # contains 'done' but not 'done.'
        "INFO [20260601_en_nvda] script written: 8 beats",
        "INFO [20260601_en_nvda] synthesizing voice ...",
        "INFO [20260601_en_nvda] done. Review in dashboard",
    ]
    job_mod._watch(pipeline, "job1", _FakeProc(lines), patterns)

    saved = job_mod._load(pipeline)[0]
    assert saved["status"] == "done"
    assert saved["exit_code"] == 0
    # Terminal label is "Done"; bar reaches 100% (stage_idx == stage_total).
    assert saved["stage_label"] == "Done"
    assert saved["stage_idx"] == len(patterns)
    assert "topic = 12" in saved["log_tail"]


def test_watch_marks_failed_on_nonzero(tmp_path, monkeypatch) -> None:
    from shorts.core import jobs as job_mod
    monkeypatch.setattr(job_mod, "_jobs_path", lambda pipeline: tmp_path / "jobs.json")
    job = {
        "id": "j2", "kind": "daily-run", "label": "x", "started_at": "t",
        "pid": 1, "status": "running", "finished_at": None, "exit_code": None,
        "log_tail": "", "stage_label": "Queued…", "stage_idx": 0, "stage_total": 1,
    }
    job_mod._save("stocks", [job])
    job_mod._watch("stocks", "j2", _FakeProc(["boom traceback"], returncode=1),
                   [("never", "x")])
    saved = job_mod._load("stocks")[0]
    assert saved["status"] == "failed"
    assert saved["exit_code"] == 1
