"""Debug: capture FFmpeg stderr output to understand progress format."""

import asyncio
import re
import subprocess
import sys
import os

async def main():
    # Change this path to an actual video file on your system
    input_path = input("Path to a video file: ").strip()
    if not os.path.isfile(input_path):
        print("File not found!")
        return

    output_path = os.path.join(os.path.dirname(input_path), "debug_test.mkv")

    cmd = [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-thread_queue_size", "512",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-c:v", "hevc_nvenc",
        "-preset", "p4",
        "-rc", "vbr",
        "-b:v", "4M",
        "-c:a", "aac",
        "-t", "5",  # Only encode 5 seconds for testing
        "-y",
        output_path,
    ]

    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creation_flags,
    )

    time_pattern = re.compile(r"time=\s*(\d{2}:\d{2}:\d{2}\.\d{2})")
    speed_pattern = re.compile(r"speed=\s*([\d.]+)\s*x")

    print(f"\n--- Capturing stderr ---\n")
    line_count = 0

    assert process.stderr is not None
    while True:
        line = await process.stderr.readline()
        if not line:
            break
        line_str = line.decode("utf-8", errors="replace").strip()
        line_count += 1

        # Print EVERY line from stderr
        print(f"  [{line_count}] {line_str[:200]}")

        time_match = time_pattern.search(line_str)
        speed_match = speed_pattern.search(line_str)

        if time_match:
            print(f"       >>> TIME MATCH: {time_match.group(1)}")
        if speed_match:
            print(f"       >>> SPEED MATCH: {speed_match.group(1)}x")

    await process.wait()

    print(f"\n--- Done. Total lines: {line_count}, Return code: {process.returncode} ---")

    # Cleanup
    if os.path.exists(output_path):
        os.remove(output_path)


asyncio.run(main())
