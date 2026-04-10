"""Conversion queue management with persistence, scheduling, and job control."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable


JOB_STATUS = ["pending", "running", "completed", "failed", "paused", "scheduled"]


@dataclass
class QueueJob:
    """Represents a single conversion job in the queue."""

    id: str
    input_path: str
    output_path: str
    profile_id: str
    profile_name: str
    status: str = "pending"
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    scheduled_at: str | None = None
    error: str | None = None
    speed: str | None = None
    progress_pct: int = 0
    remote_temp_dir: str | None = None
    engine: str = "ffmpeg"  # "ffmpeg" or "handbrake"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class QueueManager:
    """Manages a persistent queue of conversion jobs."""

    def __init__(self, queue_file: str | None = None):
        if queue_file is None:
            queue_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "queue.json",
            )
        self._queue_file = os.path.normpath(queue_file)
        self._jobs: list[QueueJob] = []
        self._paused = False
        self._load()

    # ─── Persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        if not os.path.exists(self._queue_file):
            return
        try:
            with open(self._queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._jobs = [QueueJob(**item) for item in data.get("jobs", [])]
            self._paused = data.get("paused", False)
        except (json.JSONDecodeError, KeyError, TypeError):
            self._jobs = []

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._queue_file), exist_ok=True)
        data = {
            "jobs": [asdict(j) for j in self._jobs],
            "paused": self._paused,
        }
        with open(self._queue_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ─── Queue Operations ──────────────────────────────────────────

    @property
    def jobs(self) -> list[QueueJob]:
        return self._jobs

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def pending_count(self) -> int:
        return sum(1 for j in self._jobs if j.status == "pending")

    @property
    def running_count(self) -> int:
        return sum(1 for j in self._jobs if j.status == "running")

    @property
    def failed_count(self) -> int:
        return sum(1 for j in self._jobs if j.status == "failed")

    @property
    def completed_count(self) -> int:
        return sum(1 for j in self._jobs if j.status == "completed")

    @property
    def scheduled_count(self) -> int:
        return sum(1 for j in self._jobs if j.status == "scheduled")

    def add(
        self,
        input_path: str,
        output_path: str,
        profile_id: str,
        profile_name: str,
        scheduled_at: str | None = None,
        remote_temp_dir: str | None = None,
        engine: str = "ffmpeg",
    ) -> QueueJob:
        job = QueueJob(
            id=str(uuid.uuid4())[:8],
            input_path=input_path,
            output_path=output_path,
            profile_id=profile_id,
            profile_name=profile_name,
            scheduled_at=scheduled_at,
            remote_temp_dir=remote_temp_dir,
            status="scheduled" if scheduled_at else "pending",
            engine=engine,
        )
        self._jobs.append(job)
        self.save()
        return job

    def remove(self, job_id: str, cancel_running: bool = False) -> bool:
        for i, j in enumerate(self._jobs):
            if j.id == job_id:
                if j.status == "running" and not cancel_running:
                    return False
                self._jobs.pop(i)
                self.save()
                return True
        return False

    def remove_completed(self) -> int:
        """Remove all completed jobs. Returns count removed."""
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.status != "completed"]
        removed = before - len(self._jobs)
        if removed:
            self.save()
        return removed

    def retry_failed(self) -> int:
        """Reset all failed jobs to pending. Returns count reset."""
        count = 0
        for j in self._jobs:
            if j.status == "failed":
                j.status = "pending"
                j.error = None
                j.progress_pct = 0
                j.started_at = None
                j.finished_at = None
                j.speed = None
                count += 1
        if count:
            self.save()
        return count

    def move_up(self, job_id: str) -> bool:
        for i, j in enumerate(self._jobs):
            if j.id == job_id and i > 0:
                self._jobs[i], self._jobs[i - 1] = self._jobs[i - 1], self._jobs[i]
                self.save()
                return True
        return False

    def move_down(self, job_id: str) -> bool:
        for i, j in enumerate(self._jobs):
            if j.id == job_id and i < len(self._jobs) - 1:
                self._jobs[i], self._jobs[i + 1] = self._jobs[i + 1], self._jobs[i]
                self.save()
                return True
        return False

    def toggle_pause(self) -> bool:
        """Toggle pause state. Returns new paused value."""
        self._paused = not self._paused
        self.save()
        return self._paused

    # ─── Processing ────────────────────────────────────────────────

    def get_next_job(self) -> QueueJob | None:
        """Get the next pending (or due scheduled) job, marking it running."""
        now = datetime.now().isoformat()
        for j in self._jobs:
            if j.status == "failed":
                continue
            if j.status == "pending":
                j.status = "running"
                j.started_at = now
                j.progress_pct = 0
                self.save()
                return j
            if j.status == "scheduled" and j.scheduled_at:
                if j.scheduled_at <= now:
                    j.status = "running"
                    j.started_at = now
                    j.progress_pct = 0
                    self.save()
                    return j
        return None

    def mark_job_progress(self, job_id: str, pct: int, speed: str) -> None:
        """Update job progress in memory only (no disk I/O)."""
        for j in self._jobs:
            if j.id == job_id:
                j.progress_pct = pct
                j.speed = speed
                break

    def mark_job_done(self, job_id: str, success: bool, error: str | None = None) -> None:
        for j in self._jobs:
            if j.id == job_id:
                j.status = "completed" if success else "failed"
                j.finished_at = datetime.now().isoformat()
                j.progress_pct = 100 if success else j.progress_pct
                j.error = error
                self.save()
                break

    def get_stats(self) -> dict:
        return {
            "total": len(self._jobs),
            "pending": self.pending_count,
            "running": self.running_count,
            "completed": self.completed_count,
            "failed": self.failed_count,
            "scheduled": sum(1 for j in self._jobs if j.status == "scheduled"),
            "paused": self._paused,
        }

    def clear_all(self, delete_outputs: bool = False, temp_dir: str | None = None) -> int:
        """Clear all jobs. If delete_outputs is True, also remove generated output files.
        If temp_dir is provided, also remove pending temp files ({temp_dir}/{job_id}_{filename}).

        Returns the number of files deleted.
        """
        deleted = 0
        if delete_outputs:
            for job in self._jobs:
                output = job.output_path
                if output and os.path.exists(output):
                    try:
                        os.remove(output)
                        deleted += 1
                    except OSError:
                        pass

        if temp_dir:
            for job in self._jobs:
                filename = Path(job.output_path).name
                temp_path = os.path.join(temp_dir, f"{job.id}_{filename}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                        deleted += 1
                    except OSError:
                        pass

        self._jobs = []
        self._paused = False
        self.save()
        return deleted

    # ─── Remote Temp Dir Tracking ────────────────────────────────────

    def get_pending_remote_dirs(self) -> list[tuple[str, str]]:
        """Return list of (job_id, temp_dir) for jobs with uncleaned remote dirs."""
        return [
            (j.id, j.remote_temp_dir)
            for j in self._jobs
            if j.remote_temp_dir and j.status in ("running", "completed", "failed", "paused")
        ]

    def mark_remote_dirs_cleaned(self, job_ids: list[str]) -> None:
        """Clear remote_temp_dir for the given jobs and save."""
        changed = False
        for j in self._jobs:
            if j.id in job_ids and j.remote_temp_dir:
                j.remote_temp_dir = None
                changed = True
        if changed:
            self.save()
