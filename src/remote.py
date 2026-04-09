"""Remote source handling: copy files from remote/mounted paths to temp directories using rclone/rsync."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def _find_executable(name: str) -> str | None:
    """Check if an executable is available on PATH."""
    return shutil.which(name)


def create_temp_dir(prefix: str = "video_encoder_") -> str:
    """Create and return the path of a temporary directory."""
    return tempfile.mkdtemp(prefix=prefix)


def cleanup_temp_dir(path: str) -> bool:
    """Remove a temporary directory. Returns True on success."""
    try:
        shutil.rmtree(path)
        logger.info("Cleaned up temp dir: %s", path)
        return True
    except OSError as e:
        logger.warning("Failed to clean up temp dir %s: %s", path, e)
        return False


def copy_with_rclone(
    source: str,
    dest: str,
    progress_callback=None,
) -> bool:
    """Copy files from source to dest using rclone with multi-threading.

    Args:
        source: Remote path (rclone remote like gdrive:folder, or mounted path).
        dest: Local destination directory.
        progress_callback: Optional callable(line: str) for each progress line.

    Returns:
        True if copy succeeded, False otherwise.
    """
    cmd = [
        "rclone",
        "copy",
        source,
        dest,
        "--progress",
        "--transfers", "8",
        "--multi-thread-streams", "4",
        "--multi-thread-cutoff", "64M",
        "--retries", "3",
        "--log-level", "INFO",
        "-v",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None

        for line in proc.stdout:
            line = line.rstrip()
            if progress_callback:
                progress_callback(line)
            else:
                logger.info("rclone: %s", line)

        proc.wait()
        return proc.returncode == 0

    except FileNotFoundError:
        return False
    except Exception as e:
        logger.error("rclone error: %s", e)
        return False


def copy_with_rsync(
    source: str,
    dest: str,
    progress_callback=None,
) -> bool:
    """Copy files from source to dest using rsync as fallback.

    Args:
        source: Remote path (SSH user@host:path or local mounted path).
        dest: Local destination directory.
        progress_callback: Optional callable(line: str) for each progress line.

    Returns:
        True if copy succeeded, False otherwise.
    """
    os.makedirs(dest, exist_ok=True)
    # Ensure source has trailing slash for rsync directory semantics
    if source.endswith(os.sep) or source.endswith("/"):
        rsync_source = source
    else:
        rsync_source = source + os.sep

    cmd = [
        "rsync",
        "-avz",
        "--info=progress2",
        "--partial",
        rsync_source,
        dest,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None

        for line in proc.stdout:
            line = line.rstrip()
            if progress_callback:
                progress_callback(line)
            else:
                logger.info("rsync: %s", line)

        proc.wait()
        return proc.returncode == 0

    except FileNotFoundError:
        return False
    except Exception as e:
        logger.error("rsync error: %s", e)
        return False


def copy_remote_source(
    source: str,
    dest_dir: str,
    progress_callback=None,
) -> tuple[bool, str]:
    """Copy files from a remote source to a local directory.

    Tries rclone first, then rsync as fallback.

    Args:
        source: Remote path (rclone remote, mounted path, SSH path, etc.).
        dest_dir: Local destination directory.
        progress_callback: Optional callable(line: str) for progress output.

    Returns:
        Tuple of (success, method_used) where method_used is "rclone", "rsync", or empty string.
    """
    if _find_executable("rclone"):
        logger.info("Using rclone to copy %s -> %s", source, dest_dir)
        success = copy_with_rclone(source, dest_dir, progress_callback)
        if success:
            return True, "rclone"

    if _find_executable("rsync"):
        logger.info("Using rsync to copy %s -> %s", source, dest_dir)
        success = copy_with_rsync(source, dest_dir, progress_callback)
        if success:
            return True, "rsync"

    return False, ""
