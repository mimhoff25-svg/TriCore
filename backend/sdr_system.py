from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import (
    Channel,
    SdrBand,
    SdrBandplan,
    SdrDecoderEngine,
    SdrSystemNode,
    SdrSystemProfile,
    SdrTunerProfile,
)
from .windows_rtlsdr_tools import PROJECT_ROOT, WORKSPACE_ROOT


SYSTEM_PROFILE_PATH = PROJECT_ROOT / "configs" / "system" / "tricore_austin.json"
DEFAULT_BAND_NAMES = {
    "FM Broadcast",
    "Air Band Voice",
    "NOAA Weather Radio",
    "Marine",
    "2m Ham Band",
    "70cm Ham Band",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_workspace_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    return WORKSPACE_ROOT / Path(raw_path)


def _workspace_label(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(WORKSPACE_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_sample_rate(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if not value:
        return None

    text = str(value).upper()
    digits = "".join(char for char in text if char.isdigit())
    if not digits:
        return None

    base = int(digits)
    if "MHZ" in text:
        return base * 1000
    if "KHZ" in text:
        return base
    return base


def _gain_profile(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in config.items()
        if "gain" in key.lower() and value not in (None, "")
    }


def _configured_frequencies(channels: list[Channel], trunked_catalog: dict[str, Any]) -> set[int]:
    frequencies = {int(channel.frequency_hz) for channel in channels if channel.frequency_hz}
    for site in trunked_catalog.get("sites", []):
        frequencies.update(int(freq) for freq in site.get("control_channels_hz", []) if freq)
        frequencies.update(int(freq) for freq in site.get("voice_channels_hz", []) if freq)
    return frequencies


def _build_bandplan(profile_data: dict[str, Any], configured_frequencies: set[int]) -> SdrBandplan | None:
    bandplan_path = _resolve_workspace_path(profile_data.get("bandplan_path"))
    if bandplan_path is None:
        return None

    bandplan_data = _load_json(bandplan_path)
    featured_bands: list[SdrBand] = []
    fallback_bands: list[SdrBand] = []

    for item in bandplan_data.get("bands", []):
        start = _maybe_int(item.get("start"))
        end = _maybe_int(item.get("end"))
        if start is None or end is None:
            continue
        band = SdrBand(
            name=str(item.get("name") or "Band"),
            band_type=str(item.get("type") or "other"),
            start_hz=start,
            end_hz=end,
        )
        if any(start <= frequency <= end for frequency in configured_frequencies):
            featured_bands.append(band)
        elif band.name in DEFAULT_BAND_NAMES:
            fallback_bands.append(band)

    if not featured_bands:
        featured_bands = fallback_bands[:8]

    bandplan_name = str(bandplan_data.get("name") or profile_data.get("name") or "Bandplan")
    return SdrBandplan(
        id=_slugify(str(bandplan_data.get("country_code") or bandplan_name)),
        name=bandplan_name,
        country_code=bandplan_data.get("country_code"),
        source_path=str(_workspace_label(bandplan_path) or bandplan_path),
        band_count=len(bandplan_data.get("bands", [])),
        featured_bands=featured_bands[:12],
    )


def _build_tuner_profiles(profile_data: dict[str, Any]) -> list[SdrTunerProfile]:
    tuner_path = _resolve_workspace_path(profile_data.get("tuner_config_path"))
    if tuner_path is None:
        return []

    tuner_data = _load_json(tuner_path)
    tuner_configs = tuner_data.get("tunerConfigurations", [])
    declared_profiles = profile_data.get("tuner_profiles", []) or [{} for _ in tuner_configs]
    profiles: list[SdrTunerProfile] = []

    for index, tuner_config in enumerate(tuner_configs):
        declared = declared_profiles[index] if index < len(declared_profiles) else {}
        profile_id = str(declared.get("id") or f"tuner-{index + 1}")
        profile_name = str(declared.get("name") or tuner_config.get("uniqueID") or f"Tuner {index + 1}")
        profiles.append(SdrTunerProfile(
            id=profile_id,
            name=profile_name,
            tuner_type=str(declared.get("type") or tuner_config.get("type") or "rtl_sdr"),
            source_path=str(_workspace_label(tuner_path) or tuner_path),
            unique_id=tuner_config.get("uniqueID"),
            sample_rate_hz=_parse_sample_rate(tuner_config.get("sampleRate")),
            frequency_correction_ppm=_maybe_float(tuner_config.get("frequencyCorrection")),
            minimum_frequency_hz=_maybe_int(tuner_config.get("minimumFrequency")),
            maximum_frequency_hz=_maybe_int(tuner_config.get("maximumFrequency")),
            gain_profile=_gain_profile(tuner_config),
        ))

    return profiles


def build_sdr_system_profile(
    channels: list[Channel],
    trunked_catalog: dict[str, Any],
    runtime_tools: dict[str, bool],
    runtime_diagnostics: dict[str, Any],
) -> SdrSystemProfile:
    profile_data = _load_json(SYSTEM_PROFILE_PATH)
    configured_frequencies = _configured_frequencies(channels, trunked_catalog)
    bandplan = _build_bandplan(profile_data, configured_frequencies)
    tuner_profiles = _build_tuner_profiles(profile_data)

    decoder_engines: list[SdrDecoderEngine] = []
    for engine in profile_data.get("decoder_engines", []):
        source_path = _resolve_workspace_path(engine.get("source_path"))
        decoder_engines.append(SdrDecoderEngine(
            id=str(engine.get("id") or "decoder"),
            name=str(engine.get("name") or "Decoder"),
            managed=bool(runtime_diagnostics.get("managed", True)),
            headless=bool(runtime_diagnostics.get("headless", engine.get("headless", False))),
            source_path=_workspace_label(source_path),
            protocols=[str(protocol) for protocol in engine.get("protocols", [])],
            health=str(runtime_diagnostics.get("health")) if runtime_diagnostics.get("health") else None,
            running=bool(runtime_diagnostics.get("running")),
            message=str(runtime_diagnostics.get("message")) if runtime_diagnostics.get("message") else None,
        ))

    sites = trunked_catalog.get("sites", [])
    primary_site = sites[0] if sites else {}
    systems: list[SdrSystemNode] = []
    for item in profile_data.get("systems", []):
        source_path = _resolve_workspace_path(item.get("trunked_config_path"))
        systems.append(SdrSystemNode(
            id=str(item.get("id") or "primary-system"),
            name=str(item.get("name") or trunked_catalog.get("name") or "Primary System"),
            system_type=str(item.get("system_type") or trunked_catalog.get("system_type") or "Unknown"),
            source_path=_workspace_label(source_path),
            location=str(item.get("location") or trunked_catalog.get("location") or primary_site.get("name") or ""),
            control_channels_hz=[int(freq) for freq in primary_site.get("control_channels_hz", []) if freq],
            active_control_channel_hz=_maybe_int(runtime_diagnostics.get("control_channel_hz")),
            voice_channel_count=len(primary_site.get("voice_channels_hz", [])),
            talkgroup_count=len(trunked_catalog.get("talkgroups", [])),
            preferred_tuner_profile_id=item.get("preferred_tuner_profile_id"),
            preferred_decoder_engine_id=item.get("preferred_decoder_engine_id"),
        ))

    capabilities = list(dict.fromkeys(profile_data.get("capabilities", [])))
    if runtime_tools.get("rtl_test"):
        capabilities.append("rtl_sdr_probe")
    if runtime_diagnostics.get("headless"):
        capabilities.append("headless_p25_runtime")
    capabilities = list(dict.fromkeys(capabilities))

    return SdrSystemProfile(
        id=str(profile_data.get("id") or "tricore-sdr"),
        name=str(profile_data.get("name") or "TriCore SDR"),
        location=profile_data.get("location"),
        focus=profile_data.get("focus"),
        capabilities=capabilities,
        bandplan=bandplan,
        tuner_profiles=tuner_profiles,
        decoder_engines=decoder_engines,
        systems=systems,
    )