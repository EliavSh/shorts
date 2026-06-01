"""Per-pipeline background-job tracking.

Every generate / regenerate / publish trigger goes through `start()` so we keep
a persistent record on disk (`data/<pipeline>/jobs.json`). A daemon thread
watches each subprocess and flips the status to done/failed when it exits.

The dashboard reads `list_jobs()` to show a running-jobs panel — so a reviewer
who refreshes can see what's still in flight.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from shorts.config import pipeline_data_dir

_lock = threading.Lock()
_MAX_JOBS_KEPT = 50
_LOG_TAIL_BYTES = 2000


def _jobs_path(pipeline: str) -> Path:
    return pipeline_data_dir(pipeline) / "jobs.json"


def _load(pipeline: str) -> list[dict[str, Any]]:
    p = _jobs_path(pipeline)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(pipeline: str, jobs: list[dict[str, Any]]) -> None:
    _jobs_path(pipeline).parent.mkdir(parents=True, exist_ok=True)
    _jobs_path(pipeline).write_text(
        json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(ok) and exit_code.value == STILL_ACTIVE
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _set_fields(pipeline: str, job_id: str, **fields: Any) -> None:
    """Thread-safe partial update of a single job record."""
    with _lock:
        jobs = _load(pipeline)
        for j in jobs:
            if j["id"] == job_id:
                j.update(fields)
                break
        _save(pipeline, jobs)


def start(
    pipeline: str,
    kind: str,
    label: str,
    cmd: list[str],
    cwd: str | None = None,
    stage_patterns: list[tuple[str, str]] | None = None,
) -> str:
    """Spawn `cmd` as a child process and persist a job record.

    `kind` is a coarse category (make-short, regenerate, publish, run, ...)
    `label` is human-readable (e.g. the URL or slug).
    `stage_patterns` is an optional ordered list of `(substring, label)` pairs;
    when set, the watcher scans the child's stdout and advances `stage_label`/
    `stage_idx` as those substrings appear — giving the dashboard a live
    per-stage progress signal. None → no parsing (status-only, as before).
    Returns the job_id.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    job_id = f"{int(datetime.now().timestamp() * 1000)}"
    job = {
        "id": job_id,
        "kind": kind,
        "label": label,
        "started_at": _now(),
        "pid": proc.pid,
        "status": "running",
        "finished_at": None,
        "exit_code": None,
        "log_tail": "",
        "stage_label": "Queued…",
        "stage_idx": 0,
        "stage_total": len(stage_patterns or []),
    }
    with _lock:
        jobs = _load(pipeline)
        jobs.append(job)
        jobs = jobs[-_MAX_JOBS_KEPT:]
        _save(pipeline, jobs)
    threading.Thread(
        target=_watch, args=(pipeline, job_id, proc, stage_patterns), daemon=True
    ).start()
    return job_id


def _watch(
    pipeline: str,
    job_id: str,
    proc: subprocess.Popen,
    stage_patterns: list[tuple[str, str]] | None = None,
) -> None:
    """Stream the child's stdout line-by-line so we can (a) report live stage
    progress and (b) keep a rolling log tail — then record the final status when
    it exits."""
    patterns = stage_patterns or []
    tail: list[str] = []
    tail_bytes = 0
    best_idx = -1  # furthest-progressed stage matched so far
    try:
        stream = proc.stdout
        if stream is not None:
            for raw in stream:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                tail.append(line)
                tail_bytes += len(line) + 1
                while tail_bytes > _LOG_TAIL_BYTES and len(tail) > 1:
                    tail_bytes -= len(tail.pop(0)) + 1
                # Advance the stage if this line matches a later marker than the
                # best we've seen. Only persist when the stage actually changes.
                for i, (needle, label) in enumerate(patterns):
                    if i > best_idx and needle in line:
                        best_idx = i
                        _set_fields(pipeline, job_id,
                                    stage_label=label, stage_idx=i + 1)
                        break
        rc = proc.wait()
        _set_fields(
            pipeline, job_id,
            status="done" if rc == 0 else "failed",
            exit_code=rc,
            finished_at=_now(),
            log_tail="\n".join(tail)[-_LOG_TAIL_BYTES:],
            stage_label="Done" if rc == 0 else "Failed",
            stage_idx=len(patterns),
        )
    except Exception as e:
        _set_fields(
            pipeline, job_id,
            status="failed",
            log_tail=("\n".join(tail) + f"\nwatcher error: {e}")[-_LOG_TAIL_BYTES:],
            finished_at=_now(),
        )


def list_jobs(pipeline: str, limit: int = 20) -> list[dict[str, Any]]:
    """Reconcile stale 'running' rows (dead PID) then return newest-first."""
    with _lock:
        jobs = _load(pipeline)
        dirty = False
        for j in jobs:
            if j["status"] == "running" and not _is_alive(j.get("pid")):
                j["status"] = "failed"
                j["exit_code"] = -1
                j["finished_at"] = _now()
                j["log_tail"] = j.get("log_tail") or "(process gone — likely killed when server restarted)"
                dirty = True
        if dirty:
            _save(pipeline, jobs)
    return list(reversed(jobs))[:limit]


def list_active(pipeline: str) -> list[dict[str, Any]]:
    return [j for j in list_jobs(pipeline) if j["status"] == "running"]


def get_job(pipeline: str, job_id: str) -> dict[str, Any] | None:
    for j in list_jobs(pipeline, limit=_MAX_JOBS_KEPT):
        if j["id"] == job_id:
            return j
    return None
