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


async def run_conversion(
    input_path: str,
    output_path: str,
    cmd: list[str],
    progress_callback: Callable[[int, str], None] | None = None,
) -> ConversionResult:
    """Execute an FFmpeg conversion with progress tracking.

    Uses FFmpeg's -progress pipe:1 to get periodic progress updates
    from stdout in a machine-readable format.

    Args:
        input_path: Path to the input video file.
        output_path: Path where the output will be written.
        cmd: The FFmpeg command list (should include -progress pipe:1).
        progress_callback: Optional callback(completed_percent: int, speed: str).

    Returns:
        ConversionResult with success/failure status.
    """
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Get total duration via ffprobe before starting
    total_seconds = _get_duration(input_path)

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

        # Parse progress blocks from stdout
        # Format: key=value pairs separated by blank lines
        # We care about: out_time=HH:MM:SS.xx and speed=X.Xx
        time_pattern = re.compile(r"^out_time=(\d{2}):(\d{2}):(\d{2})\.(\d+)$")
        speed_pattern = re.compile(r"^speed=([\d.]+)x$")
        progress_marker = re.compile(r"^progress=(continue|end)$")

        stderr_lines: list[str] = []
        last_pct = 0

        async def _read_stdout():
            """Parse progress blocks from FFmpeg stdout."""
            nonlocal last_pct
            assert process.stdout is not None

            buffer = ""
            while True:
                chunk = await process.stdout.read(256)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                # Process complete lines from the buffer
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()

                    time_match = time_pattern.match(line)
                    if time_match and progress_callback and total_seconds:
                        h, m, s, _ = time_match.groups()
                        current = int(h) * 3600 + int(m) * 60 + float(s)
                        pct = min(int((current / total_seconds) * 100), 99)
                        if pct != last_pct:
                            last_pct = pct

                    speed_match = speed_pattern.match(line)
                    speed_str = f"{speed_match.group(1)}x" if speed_match else ""

                    prog_match = progress_marker.match(line)
                    if prog_match and progress_callback:
                        speed = speed_str
                        if total_seconds:
                            progress_callback(last_pct, speed)
                        else:
                            # Fallback: increment progress on each block
                            last_pct = min(last_pct + 2, 99)
                            progress_callback(last_pct, speed)

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

        # Read stdout and stderr concurrently
        await asyncio.gather(
            _read_stdout(),
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
