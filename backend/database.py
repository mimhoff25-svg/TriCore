from __future__ import annotations

import json
from pathlib import Path

from .models import Channel, ChannelCreate, Talkgroup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FREQUENCY_CONFIG_PATH = PROJECT_ROOT / "configs" / "frequencies" / "sample_frequencies.json"
TRUNKED_CONFIG_PATH = PROJECT_ROOT / "configs" / "trunked" / "gatrrs_travis_county.json"
USER_CHANNELS_PATH = PROJECT_ROOT / "data" / "channels.user.json"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_channels() -> list[Channel]:
    channels: list[Channel] = []

    if FREQUENCY_CONFIG_PATH.exists():
      data = _read_json(FREQUENCY_CONFIG_PATH)
      channels.extend(Channel.model_validate(channel) for channel in data.get("channels", []))

    if USER_CHANNELS_PATH.exists():
      data = _read_json(USER_CHANNELS_PATH)
      channels.extend(Channel.model_validate(channel) for channel in data.get("channels", []))

    return channels


def save_user_channel(channel_create: ChannelCreate) -> Channel:
    channel_id = f"user-{channel_create.system.lower().replace(' ', '-')}-{channel_create.name.lower().replace(' ', '-')}"
    channel = Channel(
        id=channel_id,
        name=channel_create.name,
        system=channel_create.system,
        category=channel_create.category,
        frequency_hz=channel_create.frequency_hz,
        modulation=channel_create.modulation,
        encrypted=channel_create.encrypted,
        favorite=channel_create.favorite,
        priority=channel_create.priority,
        service_type=channel_create.service_type,
        delay_seconds=channel_create.delay_seconds,
    )

    payload = {"channels": []}
    if USER_CHANNELS_PATH.exists():
        payload = _read_json(USER_CHANNELS_PATH)
        payload.setdefault("channels", [])

    payload["channels"] = [
        existing for existing in payload["channels"] if existing.get("id") != channel.id
    ]
    payload["channels"].append(channel.model_dump())
    USER_CHANNELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with USER_CHANNELS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return channel


def load_talkgroups() -> tuple[list[Talkgroup], dict]:
    if not TRUNKED_CONFIG_PATH.exists():
        return [], {}

    data = _read_json(TRUNKED_CONFIG_PATH)
    talkgroups = [Talkgroup.model_validate(item) for item in data.get("talkgroups", [])]
    return talkgroups, data