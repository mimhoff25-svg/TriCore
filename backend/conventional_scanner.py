from __future__ import annotations

from collections.abc import Iterable

from .models import Channel


def is_channel_available(channel: Channel, skipped_channel_ids: Iterable[str] | None = None) -> bool:
    skipped = set(skipped_channel_ids or [])
    return not channel.encrypted and channel.id not in skipped


def next_scannable_channel_index(
    channels: list[Channel],
    start_index: int = 0,
    skipped_channel_ids: Iterable[str] | None = None,
) -> tuple[int, Channel] | None:
    if not channels:
        return None
    if start_index < 0 or start_index >= len(channels):
        start_index = 0

    for offset in range(len(channels)):
        index = (start_index + offset) % len(channels)
        channel = channels[index]
        if is_channel_available(channel, skipped_channel_ids):
            return index, channel
    return None


def next_scannable_channel(
    channels: list[Channel],
    start_index: int = 0,
    skipped_channel_ids: Iterable[str] | None = None,
) -> Channel | None:
    selected = next_scannable_channel_index(channels, start_index, skipped_channel_ids)
    return selected[1] if selected is not None else None
