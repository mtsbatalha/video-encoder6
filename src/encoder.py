"""FFmpeg subprocess execution engine with real-time progress tracking.

Uses frame counting (total_frames via ffprobe vs out_video_frames from
FFmpeg's -progress output) for accurate progress reporting, matching
how ffpb displays progress.
"""

from __future__ import annotations

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
                self._data[key] = {"pct": 0, "speed": ""}


def _get_video_frame_count(input_path: str) -> int:
    """Get total number of video frames using ffprobe.

    This is more accurate than duration-based progress because frames
    are processed sequentially by the encoder.
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-count_frames",
                "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            capture_output=True,
            creationflags=creation_flags,
            timeout=120,
        )
        out = result.stdout.decode("utf-8", errors="replace").strip()
        if out and out.isdigit():
            return int(out)
    except Exception:
        pass
    return 0


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
    """Worker function: runs FFmpeg and reports progress via frame counting."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Get total video frames for progress calculation
    total_frames = _get_video_frame_count(input_path)

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

        # Signal start
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

        # Poll progress file
        while process.poll() is None:
            time.sleep(0.2)
            data = _read_progress_file(progress_file)
            if not data:
                continue

            # out_video_frames is the number of encoded video frames
            frames = data.get("out_video_frames", "")
            speed = data.get("speed", "")
            speed_str = speed if speed and speed != "N/A" else ""

            if frames and frames.isdigit():
                encoded = int(frames)
                if total_frames > 0:
                    pct = min(int((encoded / total_frames) * 100), 99)
                else:
                    pct = min(encoded // 10, 99)  # rough fallback
                progress.set(input_path, pct, speed_str)

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
    """Run a single conversion with real-time progress polling."""
    progress = ProgressState()

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        None,
        lambda: _run_ffmpeg_worker(input_path, output_path, cmd, progress),
    )

    # Poll progress from worker and call callback in real-time
    last_pct = -1
    while not future.done():
        await asyncio.sleep(0.5)
        snapshot = progress.snapshot()
        if input_path in snapshot:
            state = snapshot[input_path]
            pct = state["pct"]
            speed = state.get("speed", "")
            # Only call back when % actually changes (debounce)
            if pct != last_pct and progress_callback:
                last_pct = pct
                progress_callback(pct, speed)

    result = await future

    # Final callback
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
    the callback with latest values.
    """
    progress = ProgressState()
    results: list[ConversionResult] = [None] * len(jobs)  # type: ignore[list-item]

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

        # Main thread: poll progress and update Rich Progress
        known_started: set[str] = set()
        all_done = False
        while not all_done:
            await asyncio.sleep(0.2)
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
