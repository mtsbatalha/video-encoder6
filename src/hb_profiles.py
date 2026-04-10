"""HandBrakeCLI conversion profiles — equivalents to FFmpeg profiles."""

from typing import Callable

from src.profiles import ConversionProfile


def _build_4k_sdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 4K SDR: tonemap to SDR, HEVC 20M VBR."""
    return [
        "HandBrakeCLI",
        "-i", input_path,
        "-o", output_path,
        "-e", "nvenc_h265",
        "-b", "20000",
        "--encoder-profile", "main",
        "-w", "3840", "-l", "2160",
        "--color-matrix", "bt709",
        "--color-primaries", "bt709",
        "--color-transfer", "bt709",
        "-E", "av_aac",
        "-B", "384",
        "--arate", "48",
        "--all-subtitles",
        "--json",
    ]


def _build_4k_hdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 4K HDR: keep HDR metadata, HEVC 20M VBR main10."""
    return [
        "HandBrakeCLI",
        "-i", input_path,
        "-o", output_path,
        "-e", "nvenc_h265",
        "-b", "20000",
        "--encoder-profile", "main10",
        "--encoder-level", "auto",
        "--color-matrix", "bt2020nc",
        "--color-primaries", "bt2020",
        "--color-transfer", "smpte2084",
        "-E", "av_aac",
        "-B", "384",
        "--arate", "48",
        "--all-subtitles",
        "--json",
    ]


def _build_1080p_hdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 1080p HDR: scale down, keep HDR."""
    return [
        "HandBrakeCLI",
        "-i", input_path,
        "-o", output_path,
        "-e", "nvenc_h265",
        "-b", "6000",
        "--encoder-profile", "main10",
        "-w", "1920", "-l", "1080",
        "--color-matrix", "bt2020nc",
        "--color-primaries", "bt2020",
        "--color-transfer", "smpte2084",
        "-E", "av_aac",
        "-B", "384",
        "--arate", "48",
        "--all-subtitles",
        "--json",
    ]


def _build_1080p_sdr(input_path: str, output_path: str) -> list[str]:
    """4K HDR → 1080p SDR: scale down + tonemap."""
    return [
        "HandBrakeCLI",
        "-i", input_path,
        "-o", output_path,
        "-e", "nvenc_h265",
        "-b", "4500",
        "--encoder-profile", "main",
        "-w", "1920", "-l", "1080",
        "--color-matrix", "bt709",
        "--color-primaries", "bt709",
        "--color-transfer", "bt709",
        "-E", "av_aac",
        "-B", "384",
        "--arate", "48",
        "--all-subtitles",
        "--json",
    ]


def _build_sdr_to_4k(input_path: str, output_path: str) -> list[str]:
    """SDR → 4K SDR: keep resolution."""
    return [
        "HandBrakeCLI",
        "-i", input_path,
        "-o", output_path,
        "-e", "nvenc_h265",
        "-b", "20000",
        "--encoder-profile", "main",
        "--color-matrix", "bt709",
        "--color-primaries", "bt709",
        "--color-transfer", "bt709",
        "-E", "av_aac",
        "-B", "384",
        "--arate", "48",
        "--all-subtitles",
        "--json",
    ]


def _build_sdr_to_1080p(input_path: str, output_path: str) -> list[str]:
    """SDR → 1080p SDR: scale down."""
    return [
        "HandBrakeCLI",
        "-i", input_path,
        "-o", output_path,
        "-e", "nvenc_h265",
        "-b", "4500",
        "--encoder-profile", "main",
        "-w", "1920", "-l", "1080",
        "--color-matrix", "bt709",
        "--color-primaries", "bt709",
        "--color-transfer", "bt709",
        "-E", "av_aac",
        "-B", "384",
        "--arate", "48",
        "--all-subtitles",
        "--json",
    ]


HB_PROFILES: dict[str, ConversionProfile] = {
    "hdr_to_4k_sdr": ConversionProfile(
        id="hdr_to_4k_sdr",
        name="HDR → 4K SDR",
        description="Converte HDR para SDR (tonemap auto). HEVC 20M, áudio AAC 384k.",
        suffix="4K_SDR",
        build_command=_build_4k_sdr,
        engine="handbrake",
    ),
    "hdr_to_4k_hdr": ConversionProfile(
        id="hdr_to_4k_hdr",
        name="HDR → 4K HDR",
        description="Mantém HDR (10-bit). HEVC 20M main10, áudio AAC 384k.",
        suffix="4K_HDR",
        build_command=_build_4k_hdr,
        engine="handbrake",
    ),
    "hdr_to_1080p_hdr": ConversionProfile(
        id="hdr_to_1080p_hdr",
        name="HDR → 1080p HDR",
        description="Reduz para 1080p mantendo HDR. HEVC 6M main10, áudio AAC 384k.",
        suffix="1080p_HDR",
        build_command=_build_1080p_hdr,
        engine="handbrake",
    ),
    "hdr_to_1080p_sdr": ConversionProfile(
        id="hdr_to_1080p_sdr",
        name="HDR → 1080p SDR",
        description="Reduz para 1080p e converte para SDR. HEVC 4.5M, áudio AAC 384k.",
        suffix="1080p_SDR",
        build_command=_build_1080p_sdr,
        engine="handbrake",
    ),
    "sdr_to_4k_sdr": ConversionProfile(
        id="sdr_to_4k_sdr",
        name="SDR → 4K SDR",
        description="Mantém SDR em 4K. HEVC 20M, áudio AAC 384k.",
        suffix="4K_SDR",
        build_command=_build_sdr_to_4k,
        engine="handbrake",
    ),
    "sdr_to_1080p_sdr": ConversionProfile(
        id="sdr_to_1080p_sdr",
        name="SDR → 1080p SDR",
        description="Reduz para 1080p mantendo SDR. HEVC 4.5M, áudio AAC 384k.",
        suffix="1080p_SDR",
        build_command=_build_sdr_to_1080p,
        engine="handbrake",
    ),
}

HB_HDR_PROFILES = ["hdr_to_4k_sdr", "hdr_to_4k_hdr", "hdr_to_1080p_hdr", "hdr_to_1080p_sdr"]
HB_SDR_PROFILES = ["sdr_to_4k_sdr", "sdr_to_1080p_sdr"]


def get_matching_profiles(is_hdr: bool) -> list[ConversionProfile]:
    """Return HandBrake profiles that match the source content type."""
    ids = HB_HDR_PROFILES if is_hdr else HB_SDR_PROFILES
    return [HB_PROFILES[pid] for pid in ids]


def resolve_auto_profile(is_hdr: bool, resolution: str, hdr_mode: str) -> ConversionProfile:
    """Resolve the correct HandBrake profile for a file."""
    if is_hdr:
        if resolution == "4k":
            return HB_PROFILES["hdr_to_4k_hdr" if hdr_mode == "hdr" else "hdr_to_4k_sdr"]
        else:
            return HB_PROFILES["hdr_to_1080p_hdr" if hdr_mode == "hdr" else "hdr_to_1080p_sdr"]
    else:
        if resolution == "4k":
            return HB_PROFILES["sdr_to_4k_sdr"]
        else:
            return HB_PROFILES["sdr_to_1080p_sdr"]


def get_profile(profile_id: str) -> ConversionProfile | None:
    """Get a HandBrake profile by ID, or None if not found."""
    return HB_PROFILES.get(profile_id)


def list_profiles() -> list[ConversionProfile]:
    """Return all HandBrake profiles as a list."""
    return list(HB_PROFILES.values())
