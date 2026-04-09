"""FFmpeg subprocess execution engine with progress tracking.

Uses a temp file with FFmpeg's -progress flag for reliable progress
updates. Subprocess is run in a thread pool to avoid async pipe issues.
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.file_scanner import find_external_subtitles

# Thread pool for running FFmpeg processes
_executor = ThreadPoolExecutor(max_workers=8)


@dataclass
class ConversionResult:
    """Result of a single conversion."""

    file: str
    success: bool
    details: str = ""


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
    # No -y found, insert before the last arg (output path)
    new_cmd.insert(-1, "-progress")
    new_cmd.insert(-1, progress_file)
    return new_cmd


def _run_ffmpeg_sync(
    cmd: list[str],
    progress_file: str,
    total_seconds: float | None,
    progress_callback: Callable[[int, str], None] | None,
) -> tuple[int, list[str]]:
    """Run FFmpeg synchronously with progress polling.

    Returns (returncode, stderr_lines).
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
    )

    last_pct = 0
    stderr_lines: list[str] = []

    # Poll progress file and read stderr concurrently
    def poll_progress():
        nonlocal last_pct
        while process.poll() is None:
            time.sleep(0.2)
            data = _read_progress_file(progress_file)
            if not data:
                continue

            # Try out_time_ms first (microseconds as integer string)
            out_time_ms = data.get("out_time_ms", "")
            current_seconds = None
            if out_time_ms and out_time_ms != "N/A":
                try:
                    current_seconds = float(out_time_ms) / 1_000_000
                except ValueError:
                    pass

            # Fall back to out_time (HH:MM:SS.xxxxxx)
            if current_seconds is None:
                time_str = data.get("out_time", "")
                if time_str and time_str != "N/A":
                    current_seconds = _parse_time_seconds(time_str)

            speed = data.get("speed", "")
            speed_str = speed if speed and speed != "N/A" else ""

            if progress_callback and current_seconds and total_seconds:
                pct = min(int((current_seconds / total_seconds) * 100), 99)
                if pct != last_pct:
                    last_pct = pct
                    progress_callback(pct, speed_str)
            elif progress_callback and current_seconds:
                last_pct = min(last_pct + 1, 99)
                progress_callback(last_pct, speed_str)

    def read_stderr():
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(
                line.decode("utf-8", errors="replace").strip()
            )

    import threading
    t1 = threading.Thread(target=poll_progress, daemon=True)
    t2 = threading.Thread(target=read_stderr, daemon=True)
    t1.start()
    t2.start()

    process.wait()
    t1.join(timeout=2)
    t2.join(timeout=2)

    return process.returncode, stderr_lines


async def run_conversion(
    input_path: str,
    output_path: str,
    cmd: list[str],
    progress_callback: Callable[[int, str], None] | None = None,
) -> ConversionResult:
    """Execute an FFmpeg conversion with progress tracking.

    Uses a temp file for FFmpeg's -progress flag, run in a thread pool
    to avoid async subprocess pipe issues on Windows.
    """
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Get total duration via ffprobe
    total_seconds = _get_duration(input_path)

    # Create temp progress file
    progress_fd, progress_file = tempfile.mkstemp(suffix=".progress")
    os.close(progress_fd)

    try:
        # Build command with -progress flag pointing to temp file
        cmd_with_progress = _inject_progress_flag(cmd, progress_file)

        # Run FFmpeg in thread pool
        returncode, stderr_lines = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: _run_ffmpeg_sync(
                cmd_with_progress, progress_file, total_seconds, progress_callback
            ),
        )

        if returncode == 0:
            # Copy external subtitles to output folder
            _copy_external_subtitles(input_path, output_path)

            if progress_callback:
                progress_callback(100, "Concluído")
            return ConversionResult(
                file=input_path,
                success=True,
                details=f"Salvo em: {output_path}",
            )
        else:
            error_msg = _extract_error(stderr_lines)
            return ConversionResult(
                file=input_path,
                success=False,
                details=error_msg,
            )

    except FileNotFoundError:
        return ConversionResult(
            file=input_path,
            success=False,
            details="ffmpeg não encontrado. Instale o FFmpeg com suporte a NVENC.",
        )
    except Exception as e:
        return ConversionResult(
            file=input_path,
            success=False,
            details=str(e),
        )
    finally:
        # Clean up temp file
        try:
            os.unlink(progress_file)
        except OSError:
            pass


async def run_batch_conversions(
    jobs: list[dict],
    max_parallel: int = 2,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> list[ConversionResult]:
    """Run multiple conversions with configurable parallelism."""
    semaphore = asyncio.Semaphore(max_parallel)
    results: list[ConversionResult] = []

    async def _run(job: dict) -> ConversionResult:
        async with semaphore:
            input_path = job["input_path"]
            output_path = job["output_path"]
            cmd = job["cmd"]
            filename = Path(input_path).name

            def _cb(pct: int, speed: str) -> None:
                if progress_callback:
                    progress_callback(filename, pct, speed)

            result = await run_conversion(
                input_path, output_path, cmd, progress_callback=_cb
            )
            results.append(result)
            return result

    tasks = [asyncio.create_task(_run(job)) for job in jobs]
    await asyncio.gather(*tasks)
    return results


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
