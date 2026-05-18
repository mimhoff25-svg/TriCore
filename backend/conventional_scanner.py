from __future__ import annotations

from .models import Channel


def next_scannable_channel(channels: list[Channel], start_index: int = 0) -> Channel | None:
    if not channels:
        return None
    if start_index >= len(channels):
        start_index = 0
    return channels[start_index]