"""FFmpeg subprocess execution engine with progress tracking.

Uses a temp file with FFmpeg's -progress flag for reliable progress
updates across all platforms (avoids pipe buffering issues on Windows).
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


def _parse_time_ms(time_str: str) -> float | None:
    """Convert FFmpeg time string (HH:MM:SS.xx) to seconds."""
    m = re.match(r"(\d{2}):(\d{2}):(\d{2})\.(\d+)", time_str)
    if m:
        h, mi, s, _ = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
    return None


def _inject_progress_flag(cmd: list[str], progress_file: str) -> list[str]:
    """Insert -progress flag before -y/-output in the command."""
    new_cmd = list(cmd)
    # Find where -y or the output path is
    for i, arg in enumerate(new_cmd):
        if arg == "-y":
            new_cmd.insert(i, progress_file)
            new_cmd.insert(i, "pipe:1")
            new_cmd.insert(i, "-progress")
            break
    else:
        # No -y found, append before last arg (output path)
        new_cmd.insert(-1, progress_file)
        new_cmd.insert(-1, "pipe:1")
        new_cmd.insert(-1, "-progress")
    return new_cmd


async def run_conversion(
    input_path: str,
    output_path: str,
    cmd: list[str],
    progress_callback: Callable[[int, str], None] | None = None,
) -> ConversionResult:
    """Execute an FFmpeg conversion with progress tracking.

    Uses FFmpeg's -progress flag writing to a temp file, which is
    read periodically. This avoids pipe buffering issues on Windows.
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

        # Platform-specific: hide console window on Windows
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        process = await asyncio.create_subprocess_exec(
            *cmd_with_progress,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creation_flags,
        )

        stderr_lines: list[str] = []
        last_pct = 0
        last_pos = 0  # File position for reading progress file

        async def _read_progress_file():
            """Poll progress file every 200ms."""
            nonlocal last_pct
            while process.returncode is None:
                await asyncio.sleep(0.2)
                data = _read_progress_file(progress_file)
                if not data:
                    continue

                # Extract time
                out_time = data.get("out_time_ms", "")
                speed = data.get("speed", "")

                current_seconds = None
                if out_time and out_time != "N/A":
                    try:
                        current_seconds = float(out_time) / 1_000_000  # microseconds
                    except ValueError:
                        time_str = data.get("out_time", "")
                        current_seconds = _parse_time_ms(time_str)

                speed_str = speed if speed else ""

                if progress_callback and current_seconds and total_seconds:
                    pct = min(int((current_seconds / total_seconds) * 100), 99)
                    if pct != last_pct:
                        last_pct = pct
                        progress_callback(pct, speed_str)
                elif progress_callback and current_seconds:
                    # No total duration, use fallback
                    last_pct = min(last_pct + 1, 99)
                    progress_callback(last_pct, speed_str)

        async def _read_stderr():
            """Capture stderr for error reporting."""
            nonlocal stderr_lines
            assert process.stderr is not None
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                stderr_lines.append(
                    line.decode("utf-8", errors="replace").strip()
                )

        # Poll progress and read stderr concurrently
        await asyncio.gather(
            _read_progress_file(),
            _read_stderr(),
        )

        await process.wait()

        if process.returncode == 0:
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
