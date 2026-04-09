"""FFmpeg subprocess execution engine with real-time progress tracking.

Uses sync subprocess + ThreadPoolExecutor. The main thread polls
a shared state dict to update Rich Progress bars in real time.
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.file_scanner import find_external_subtitles


@dataclass
class ConversionResult:
    """Result of a single conversion."""

    file: str
    success: bool
    details: str = ""


# Shared progress state: {input_path: {"pct": int, "speed": str}}
class ProgressState:
    """Thread-safe progress state shared between worker threads and main thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}

    def set(self, key: str, pct: int, speed: str) -> None:
        with self._lock:
            self._data[key] = {"pct": pct, "speed": speed}

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._data)

    def mark_done(self, key: str) -> None:
        with self._lock:
            if key in self._data:
                self._data[key] = {"pct": 100, "speed": "Concluído"}

    def mark_started(self, key: str) -> None:
        with self._lock:
            if key not in self._data:
                self._data[key] = {"pct": 0, "speed": "", "started": True}
            else:
                self._data[key]["started"] = True

    def get_started_keys(self) -> set[str]:
        with self._lock:
            return {k for k, v in self._data.items() if v.get("started")}


def _get_duration(input_path: str) -> float | None:
    """Get video duration in seconds using ffprobe."""
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            capture_output=True,
            creationflags=creation_flags,
            timeout=30,
        )
        out = result.stdout.decode("utf-8", errors="replace").strip()
        if out:
            return float(out)
    except Exception:
        pass
    return None


def _read_progress_file(path: str) -> dict:
    """Parse key=value pairs from FFmpeg progress file."""
    data = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, _, value = line.partition("=")
                    data[key.strip()] = value.strip()
    except (OSError, IOError):
        pass
    return data


def _parse_time_seconds(time_str: str) -> float | None:
    """Convert FFmpeg time string (HH:MM:SS.xxxxxx) to seconds."""
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})\.(\d+)", time_str)
    if m:
        h, mi, s, frac = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(f"{s}.{frac}")
    return None


def _inject_progress_flag(cmd: list[str], progress_file: str) -> list[str]:
    """Insert -progress <file> flag before -y or the output path."""
    new_cmd = list(cmd)
    for i, arg in enumerate(new_cmd):
        if arg == "-y":
            new_cmd.insert(i, "-progress")
            new_cmd.insert(i + 1, progress_file)
            return new_cmd
    new_cmd.insert(-1, "-progress")
    new_cmd.insert(-1, progress_file)
    return new_cmd


def _run_ffmpeg_worker(
    input_path: str,
    output_path: str,
    cmd: list[str],
    progress: ProgressState,
) -> ConversionResult:
    """Worker function: runs FFmpeg and reports progress to shared state."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    total_seconds = _get_duration(input_path)

    progress_fd, progress_file = tempfile.mkstemp(suffix=".progress")
    os.close(progress_fd)

    try:
        cmd_with_progress = _inject_progress_flag(cmd, progress_file)

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        process = subprocess.Popen(
            cmd_with_progress,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )

        # Signal that this conversion has started
        progress.mark_started(input_path)

        stderr_lines: list[str] = []

        def read_stderr():
            assert process.stderr is not None
            for line in process.stderr:
                stderr_lines.append(
                    line.decode("utf-8", errors="replace").strip()
                )

        t_stderr = threading.Thread(target=read_stderr, daemon=True)
        t_stderr.start()

        # Poll progress and update shared state
        while process.poll() is None:
            time.sleep(0.2)
            data = _read_progress_file(progress_file)
            if data:
                out_time_ms = data.get("out_time_ms", "")
                current_seconds = None
                if out_time_ms and out_time_ms != "N/A":
                    try:
                        current_seconds = float(out_time_ms) / 1_000_000
                    except ValueError:
                        pass

                if current_seconds is None:
                    t = data.get("out_time", "")
                    if t and t != "N/A":
                        current_seconds = _parse_time_seconds(t)

                speed = data.get("speed", "")
                speed_str = speed if speed and speed != "N/A" else ""

                if current_seconds and total_seconds:
                    pct = min(int((current_seconds / total_seconds) * 100), 99)
                    progress.set(input_path, pct, speed_str)
                elif current_seconds:
                    progress.set(input_path, 1, speed_str)

        t_stderr.join(timeout=2)

        if process.returncode == 0:
            _copy_external_subtitles(input_path, output_path)
            progress.mark_done(input_path)
            return ConversionResult(
                file=input_path,
                success=True,
                details=f"Salvo em: {output_path}",
            )
        else:
            error_msg = _extract_error(stderr_lines)
            progress.set(input_path, 0, f"ERRO: {error_msg}")
            return ConversionResult(
                file=input_path,
                success=False,
                details=error_msg,
            )

    except FileNotFoundError:
        progress.set(input_path, 0, "ffmpeg não encontrado")
        return ConversionResult(
            file=input_path,
            success=False,
            details="ffmpeg não encontrado. Instale o FFmpeg com suporte a NVENC.",
        )
    except Exception as e:
        progress.set(input_path, 0, str(e))
        return ConversionResult(
            file=input_path,
            success=False,
            details=str(e),
        )
    finally:
        try:
            os.unlink(progress_file)
        except OSError:
            pass


async def run_conversion(
    input_path: str,
    output_path: str,
    cmd: list[str],
    progress_callback: Callable[[int, str], None] | None = None,
) -> ConversionResult:
    """Run a single conversion synchronously (for single-file mode)."""
    progress = ProgressState()

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _run_ffmpeg_worker(input_path, output_path, cmd, progress),
    )

    # Report final state via callback
    if progress_callback:
        if result.success:
            progress_callback(100, "Concluído")
        else:
            progress_callback(0, f"ERRO: {result.details}")

    return result


async def run_batch_conversions(
    jobs: list[dict],
    max_parallel: int = 2,
    progress_callback: Callable[[str, int, str, bool], None] | None = None,
) -> list[ConversionResult]:
    """Run batch conversions with real-time progress polling from main thread.

    Worker threads update ProgressState. The main thread polls and calls
    the callback with latest values, then waits for all to finish.
    """
    progress = ProgressState()
    results: list[ConversionResult] = [None] * len(jobs)  # type: ignore[list-item]

    # Map input_path -> index
    path_to_idx = {job["input_path"]: i for i, job in enumerate(jobs)}

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {}
        for job in jobs:
            future = executor.submit(
                _run_ffmpeg_worker,
                job["input_path"],
                job["output_path"],
                job["cmd"],
                progress,
            )
            futures[future] = job["input_path"]

        # Main thread: poll progress state and call callback
        known_started: set[str] = set()
        all_done = False
        while not all_done:
            await asyncio.sleep(0.2)  # Yield to event loop for Rich Progress refresh
            snapshot = progress.snapshot()
            for key, state in snapshot.items():
                if key in path_to_idx:
                    idx = path_to_idx[key]
                    if results[idx] is None and progress_callback:
                        just_started = key not in known_started
                        if just_started:
                            known_started.add(key)
                        progress_callback(key, state["pct"], state["speed"], just_started)

            all_done = all(f.done() for f in futures)

        # Collect results
        for future, input_path in futures.items():
            idx = path_to_idx[input_path]
            results[idx] = future.result()

    return results  # type: ignore[return-value]


def _extract_error(stderr_lines: list[str]) -> str:
    """Extract meaningful error message from FFmpeg stderr output."""
    error_keywords = [
        "error", "invalid", "failed", "unsupported",
        "cannot", "unable", "no such", "not found",
    ]
    for line in reversed(stderr_lines):
        lower = line.lower()
        if any(kw in lower for kw in error_keywords):
            clean = re.sub(r"\[.*?\]", "", line).strip()
            if clean and len(clean) > 5:
                return clean[:200]
    return "Erro desconhecido do FFmpeg (código de saída não-zero)"


def _copy_external_subtitles(video_path: str, output_path: str) -> None:
    """Find and copy external subtitle files to the output folder."""
    subs = find_external_subtitles(video_path)
    if not subs:
        return

    output_dir = os.path.dirname(output_path)
    output_base = Path(output_path).stem

    for sub_path in subs:
        sub_ext = Path(sub_path).suffix
        dest = os.path.join(output_dir, f"{output_base}{sub_ext}")
        shutil.copy2(sub_path, dest)
