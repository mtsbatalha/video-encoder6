"""FFmpeg subprocess execution engine with progress tracking."""

import asyncio
import os
import re
import shutil
import subprocess
import sys
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


async def run_conversion(
    input_path: str,
    output_path: str,
    cmd: list[str],
    progress_callback: Callable[[int, str], None] | None = None,
) -> ConversionResult:
    """Execute an FFmpeg conversion with progress tracking.

    Args:
        input_path: Path to the input video file.
        output_path: Path where the output will be written.
        cmd: The FFmpeg command list.
        progress_callback: Optional callback(completed_percent: int, speed: str).

    Returns:
        ConversionResult with success/failure status.
    """
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Platform-specific: hide console window on Windows
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creation_flags,
        )

        # Read stderr line by line for progress
        speed_pattern = re.compile(r"speed=\s*([\d.]+)\s*x")
        time_pattern = re.compile(r"time=\s*(\d{2}:\d{2}:\d{2}\.\d{2})")

        # We need total duration for percentage calculation
        # FFmpeg prints duration early in stderr: "Duration: HH:MM:SS.cc"
        duration_pattern = re.compile(
            r"Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{2})"
        )
        total_seconds = None
        current_seconds = None

        stderr_lines: list[str] = []

        assert process.stderr is not None
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="replace").strip()
            stderr_lines.append(line_str)

            # Try to extract total duration
            if total_seconds is None:
                dur_match = duration_pattern.search(line_str)
                if dur_match:
                    h, m, s, _ = dur_match.groups()
                    total_seconds = int(h) * 3600 + int(m) * 60 + float(s)

            # Extract current time
            time_match = time_pattern.search(line_str)
            if time_match:
                parts = time_match.group(1).split(":")
                h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
                current_seconds = h * 3600 + m * 60 + s

            # Extract speed
            speed_match = speed_pattern.search(line_str)
            speed_str = f"{speed_match.group(1)}x" if speed_match else ""

            # Calculate percentage
            if (
                progress_callback
                and total_seconds
                and current_seconds is not None
            ):
                pct = min(int((current_seconds / total_seconds) * 100), 99)
                progress_callback(pct, speed_str)

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


async def run_batch_conversions(
    jobs: list[dict],
    max_parallel: int = 2,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> list[ConversionResult]:
    """Run multiple conversions with configurable parallelism.

    Args:
        jobs: List of dicts with keys: input_path, output_path, cmd
        max_parallel: Maximum number of concurrent conversions.
        progress_callback: Optional callback(filename, percent, speed).

    Returns:
        List of ConversionResult.
    """
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
            # Clean up the line
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
