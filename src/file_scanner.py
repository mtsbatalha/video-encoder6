"""File discovery, external subtitle detection, and HDR detection."""

import json
import os
import subprocess
import sys
from pathlib import Path

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".smi"}
HDR_TRANSFER_CHARACTERISTICS = {"smpte2084", "arib-std-b67"}


def scan_video_files(path: str) -> list[str]:
    """Find all video files in a path. If path is a file, returns it if valid. If directory, scans recursively."""
    p = Path(path)
    if p.is_file():
        if p.suffix.lower() in VIDEO_EXTENSIONS:
            return [str(p)]
        return []
    if p.is_dir():
        videos = []
        for root, _dirs, files in os.walk(p):
            for f in sorted(files):
                if Path(f).suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(os.path.join(root, f))
        return videos
    return []


def find_external_subtitles(video_path: str) -> list[str]:
    """Find subtitle files that share the same base name as the video, in the same directory."""
    video = Path(video_path)
    base = video.stem
    directory = video.parent
    subs = []
    for sub_ext in SUBTITLE_EXTENSIONS:
        sub_path = directory / (base + sub_ext)
        if sub_path.exists():
            subs.append(str(sub_path))
    return sorted(subs)


def build_output_dir(input_path: str, output_dir: str, suffix: str) -> str:
    """Build the output folder path: {output_dir}/{filename_without_ext}_{suffix}/."""
    base = Path(input_path).stem
    folder_name = f"{base}_{suffix}"
    return os.path.join(output_dir, folder_name)


def build_output_path(input_path: str, output_dir: str, suffix: str) -> str:
    """Build the full output file path: {output_dir}/{filename}_{suffix}/{filename}_{suffix}.mkv."""
    folder = build_output_dir(input_path, output_dir, suffix)
    base = Path(input_path).stem
    filename = f"{base}_{suffix}.mkv"
    return os.path.join(folder, filename)


def detect_hdr(input_path: str) -> bool:
    """Detect if a video file is HDR by checking color transfer characteristics.

    Uses ffprobe to read color_transfer (transfer characteristics).
    HDR is identified by smpte2084 (PQ) or arib-std-b67 (HLG).
    Returns True if HDR, False if SDR or unable to determine.
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=color_transfer,color_primaries,color_space",
                "-of", "json",
                input_path,
            ],
            capture_output=True,
            creationflags=creation_flags,
            timeout=30,
        )
        output = result.stdout.decode("utf-8", errors="replace")
        data = json.loads(output)

        streams = data.get("streams", [])
        if not streams:
            return False

        stream = streams[0]
        color_transfer = stream.get("color_transfer", "")
        return color_transfer in HDR_TRANSFER_CHARACTERISTICS

    except Exception:
        # If detection fails, default to SDR (safest assumption)
        return False
