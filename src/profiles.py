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
    engine: str = "ffmpeg"  # "ffmpeg" or "handbrake"


def _build_4k_sdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR -> 4K SDR: GPU decode, tonemap on CPU, encode on GPU."""
    return [
        "ffmpeg",
        "-c:v", "hevc_cuvid",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-vf", "hwdownload,format=nv12,tonemap=hable:desat=0,hwupload_cuda,format=yuv420p",
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
        "-y",
        output_path,
    ]


def _build_4k_hdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR -> 4K HDR: full GPU pipeline (decode + encode)."""
    return [
        "ffmpeg",
        "-c:v", "hevc_cuvid",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
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
        "-y",
        output_path,
    ]


def _build_1080p_hdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR -> 1080p HDR: full GPU pipeline (decode + scale + encode)."""
    return [
        "ffmpeg",
        "-c:v", "hevc_cuvid",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-vf", "hwupload_cuda,scale_cuda=1920:1080:format=p010le",
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
        "-y",
        output_path,
    ]


def _build_1080p_sdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR -> 1080p SDR: GPU decode, tonemap on CPU, scale on GPU."""
    return [
        "ffmpeg",
        "-c:v", "hevc_cuvid",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-vf", "hwdownload,format=nv12,tonemap=hable:desat=0,hwupload_cuda,scale_cuda=1920:1080:format=yuv420p",
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
        "-y",
        output_path,
    ]


def _build_sdr_to_4k(input_path: str, output_path: str) -> list[str]:
    """SDR -> 4K SDR: no GPU decode (SDR source), encode on GPU."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
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
        "-y",
        output_path,
    ]


def _build_sdr_to_1080p(input_path: str, output_path: str) -> list[str]:
    """SDR -> 1080p SDR: hwaccel decode, scale on GPU, encode on GPU."""
    return [
        "ffmpeg",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-vf", "hwdownload,format=nv12,hwupload_cuda,scale_cuda=1920:1080:format=yuv420p",
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
        "-y",
        output_path,
    ]


PROFILES: dict[str, ConversionProfile] = {
    "hdr_to_4k_sdr": ConversionProfile(
        id="hdr_to_4k_sdr",
        name="HDR -> 4K SDR",
        description="GPU decode + tonemap CPU + encode GPU. HEVC 20M, audio AAC 384k.",
        suffix="4K_SDR",
        build_command=_build_4k_sdr,
    ),
    "hdr_to_4k_hdr": ConversionProfile(
        id="hdr_to_4k_hdr",
        name="HDR -> 4K HDR",
        description="Pipeline completa GPU (decode + encode). HEVC 20M main10 10-bit, audio AAC 384k.",
        suffix="4K_HDR",
        build_command=_build_4k_hdr,
    ),
    "hdr_to_1080p_hdr": ConversionProfile(
        id="hdr_to_1080p_hdr",
        name="HDR -> 1080p HDR",
        description="Pipeline completa GPU (decode + scale + encode). HEVC 6M main10, audio AAC 384k.",
        suffix="1080p_HDR",
        build_command=_build_1080p_hdr,
    ),
    "hdr_to_1080p_sdr": ConversionProfile(
        id="hdr_to_1080p_sdr",
        name="HDR -> 1080p SDR",
        description="GPU decode + tonemap CPU + scale GPU + encode GPU. HEVC 4.5M, audio AAC 384k.",
        suffix="1080p_SDR",
        build_command=_build_1080p_sdr,
    ),
    "sdr_to_4k_sdr": ConversionProfile(
        id="sdr_to_4k_sdr",
        name="SDR -> 4K SDR",
        description="Mantem SDR em 4K. HEVC 20M, audio AAC 384k.",
        suffix="4K_SDR",
        build_command=_build_sdr_to_4k,
    ),
    "sdr_to_1080p_sdr": ConversionProfile(
        id="sdr_to_1080p_sdr",
        name="SDR -> 1080p SDR",
        description="Reduz para 1080p mantendo SDR. HEVC 4.5M, audio AAC 384k.",
        suffix="1080p_SDR",
        build_command=_build_sdr_to_1080p,
    ),
}

HDR_PROFILES = ["hdr_to_4k_sdr", "hdr_to_4k_hdr", "hdr_to_1080p_hdr", "hdr_to_1080p_sdr"]
SDR_PROFILES = ["sdr_to_4k_sdr", "sdr_to_1080p_sdr"]


def get_matching_profiles(is_hdr: bool) -> list[ConversionProfile]:
    """Return profiles that match the source content type.

    is_hdr=True -> HDR source profiles (tonemap available)
    is_hdr=False -> SDR source profiles (no tonemap needed)
    """
    ids = HDR_PROFILES if is_hdr else SDR_PROFILES
    return [PROFILES[pid] for pid in ids]


def resolve_auto_profile(is_hdr: bool, resolution: str, hdr_mode: str) -> ConversionProfile:
    """Resolve the correct profile for a file given its HDR status and user choices.

    Args:
        is_hdr: Whether the source file is HDR.
        resolution: "4k" or "1080p".
        hdr_mode: "hdr" (keep HDR) or "sdr" (convert to SDR). Only affects HDR files.

    Returns:
        The matching ConversionProfile.
    """
    if is_hdr:
        if resolution == "4k":
            return PROFILES["hdr_to_4k_hdr" if hdr_mode == "hdr" else "hdr_to_4k_sdr"]
        else:
            return PROFILES["hdr_to_1080p_hdr" if hdr_mode == "hdr" else "hdr_to_1080p_sdr"]
    else:
        # SDR source -> always SDR output
        if resolution == "4k":
            return PROFILES["sdr_to_4k_sdr"]
        else:
            return PROFILES["sdr_to_1080p_sdr"]


def get_profile(profile_id: str) -> ConversionProfile | None:
    """Get a profile by ID, or None if not found."""
    return PROFILES.get(profile_id)


def list_profiles() -> list[ConversionProfile]:
    """Return all available profiles as a list."""
    return list(PROFILES.values())
