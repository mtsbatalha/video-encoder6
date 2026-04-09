"""Conversion profiles for FFmpeg video encoding."""

from dataclasses import dataclass
from typing import Callable


@dataclass
class ConversionProfile:
    """Describes a single FFmpeg conversion profile."""

    id: str
    name: str
    description: str
    suffix: str
    build_command: Callable[[str, str], list[str]]


def _build_4k_sdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 4K SDR: tonemap to SDR, HEVC 20M VBR."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-thread_queue_size", "512",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-map", "0:s?",
        "-vf", "tonemap=hable:desat=0,format=yuv420p",
        "-c:v", "hevc_nvenc",
        "-preset", "p6",
        "-rc", "vbr",
        "-b:v", "20M",
        "-maxrate", "25M",
        "-bufsize", "50M",
        "-profile:v", "main",
        "-spatial_aq", "1",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-color_range", "tv",
        "-c:a", "aac",
        "-b:a", "384k",
        "-ar", "48000",
        "-c:s", "copy",
        "-y",
        output_path,
    ]


def _build_4k_hdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 4K HDR: keep HDR metadata, HEVC 20M VBR main10."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-thread_queue_size", "512",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-map", "0:s?",
        "-c:v", "hevc_nvenc",
        "-preset", "p6",
        "-rc", "vbr",
        "-b:v", "20M",
        "-maxrate", "25M",
        "-bufsize", "50M",
        "-profile:v", "main10",
        "-pix_fmt", "p010le",
        "-spatial_aq", "1",
        "-color_primaries", "bt2020",
        "-color_trc", "smpte2084",
        "-colorspace", "bt2020nc",
        "-color_range", "tv",
        "-c:a", "aac",
        "-b:a", "384k",
        "-ar", "48000",
        "-c:s", "copy",
        "-y",
        output_path,
    ]


def _build_1080p_hdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 1080p HDR: scale down, keep HDR."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-thread_queue_size", "512",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-map", "0:s?",
        "-vf", "scale=1920:1080,format=p010le",
        "-c:v", "hevc_nvenc",
        "-preset", "p6",
        "-rc", "vbr",
        "-b:v", "6M",
        "-maxrate", "8M",
        "-bufsize", "16M",
        "-profile:v", "main10",
        "-spatial_aq", "1",
        "-color_primaries", "bt2020",
        "-color_trc", "smpte2084",
        "-colorspace", "bt2020nc",
        "-color_range", "tv",
        "-c:a", "aac",
        "-b:a", "384k",
        "-ar", "48000",
        "-c:s", "copy",
        "-y",
        output_path,
    ]


def _build_1080p_sdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 1080p SDR: scale down + tonemap."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-thread_queue_size", "512",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-map", "0:s?",
        "-vf", "scale=1920:1080,tonemap=hable:desat=0,format=yuv420p",
        "-c:v", "hevc_nvenc",
        "-preset", "p6",
        "-rc", "vbr",
        "-b:v", "4.5M",
        "-maxrate", "6M",
        "-bufsize", "12M",
        "-profile:v", "main",
        "-spatial_aq", "1",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-color_range", "tv",
        "-c:a", "aac",
        "-b:a", "384k",
        "-ar", "48000",
        "-c:s", "copy",
        "-y",
        output_path,
    ]


def _build_sdr_to_4k(input_path: str, output_path: str) -> list[str]:
    """SDR → 4K SDR: keep resolution, no tonemap needed."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-thread_queue_size", "512",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-map", "0:s?",
        "-vf", "format=yuv420p",
        "-c:v", "hevc_nvenc",
        "-preset", "p6",
        "-rc", "vbr",
        "-b:v", "20M",
        "-maxrate", "25M",
        "-bufsize", "50M",
        "-profile:v", "main",
        "-spatial_aq", "1",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-color_range", "tv",
        "-c:a", "aac",
        "-b:a", "384k",
        "-ar", "48000",
        "-c:s", "copy",
        "-y",
        output_path,
    ]


def _build_sdr_to_1080p(input_path: str, output_path: str) -> list[str]:
    """SDR → 1080p SDR: scale down, no tonemap needed."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-thread_queue_size", "512",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-map", "0:s?",
        "-vf", "scale=1920:1080,format=yuv420p",
        "-c:v", "hevc_nvenc",
        "-preset", "p6",
        "-rc", "vbr",
        "-b:v", "4.5M",
        "-maxrate", "6M",
        "-bufsize", "12M",
        "-profile:v", "main",
        "-spatial_aq", "1",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-color_range", "tv",
        "-c:a", "aac",
        "-b:a", "384k",
        "-ar", "48000",
        "-c:s", "copy",
        "-y",
        output_path,
    ]


PROFILES: dict[str, ConversionProfile] = {
    "hdr_to_4k_sdr": ConversionProfile(
        id="hdr_to_4k_sdr",
        name="HDR → 4K SDR",
        description="Converte HDR para SDR (tonemap Hable). HEVC 20M, áudio AAC 384k.",
        suffix="4K_SDR",
        build_command=_build_4k_sdr,
    ),
    "hdr_to_4k_hdr": ConversionProfile(
        id="hdr_to_4k_hdr",
        name="HDR → 4K HDR",
        description="Mantém HDR (DV/HDR). HEVC 20M main10 10-bit, áudio AAC 384k.",
        suffix="4K_HDR",
        build_command=_build_4k_hdr,
    ),
    "hdr_to_1080p_hdr": ConversionProfile(
        id="hdr_to_1080p_hdr",
        name="HDR → 1080p HDR",
        description="Reduz para 1080p mantendo HDR. HEVC 6M main10, áudio AAC 384k.",
        suffix="1080p_HDR",
        build_command=_build_1080p_hdr,
    ),
    "hdr_to_1080p_sdr": ConversionProfile(
        id="hdr_to_1080p_sdr",
        name="HDR → 1080p SDR",
        description="Reduz para 1080p e converte para SDR. HEVC 4.5M, áudio AAC 384k.",
        suffix="1080p_SDR",
        build_command=_build_1080p_sdr,
    ),
    "sdr_to_4k_sdr": ConversionProfile(
        id="sdr_to_4k_sdr",
        name="SDR → 4K SDR",
        description="Mantém SDR em 4K. HEVC 20M, áudio AAC 384k.",
        suffix="4K_SDR",
        build_command=_build_sdr_to_4k,
    ),
    "sdr_to_1080p_sdr": ConversionProfile(
        id="sdr_to_1080p_sdr",
        name="SDR → 1080p SDR",
        description="Reduz para 1080p mantendo SDR. HEVC 4.5M, áudio AAC 384k.",
        suffix="1080p_SDR",
        build_command=_build_sdr_to_1080p,
    ),
}

HDR_PROFILES = ["hdr_to_4k_sdr", "hdr_to_4k_hdr", "hdr_to_1080p_hdr", "hdr_to_1080p_sdr"]
SDR_PROFILES = ["sdr_to_4k_sdr", "sdr_to_1080p_sdr"]


def get_matching_profiles(is_hdr: bool) -> list[ConversionProfile]:
    """Return profiles that match the source content type.

    is_hdr=True → HDR source profiles (tonemap available)
    is_hdr=False → SDR source profiles (no tonemap needed)
    """
    ids = HDR_PROFILES if is_hdr else SDR_PROFILES
    return [PROFILES[pid] for pid in ids]


def get_profile(profile_id: str) -> ConversionProfile | None:
    """Get a profile by ID, or None if not found."""
    return PROFILES.get(profile_id)


def list_profiles() -> list[ConversionProfile]:
    """Return all available profiles as a list."""
    return list(PROFILES.values())
