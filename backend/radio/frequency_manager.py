from __future__ import annotations

from typing import Optional

from ..database import load_channels as load_legacy_channels
from .bandplans import load_bandplans
from .banks import load_default_banks
from .models import Bank, Channel, SearchRange


class FrequencyManager:
    def __init__(self) -> None:
        self.banks: list[Bank] = load_default_banks()
        self.bandplans: list[SearchRange] = load_bandplans()
        self.channels: list[Channel] = self._load_channels()

    def _load_channels(self) -> list[Channel]:
        channels: list[Channel] = []
        for legacy in load_legacy_channels():
            bank_id, service_type = self._classify_channel(
                legacy.service_type,
                legacy.category,
                legacy.modulation,
                legacy.frequency_hz,
            )
            modulation = self._normalize_modulation(legacy.modulation, service_type)
            unavailable = bool(legacy.encrypted or modulation == "p25_placeholder")
            notes = "Unavailable: encrypted." if legacy.encrypted else None
            if modulation == "p25_placeholder" and notes is None:
                notes = "P25 placeholder. Full P25 decoding is planned later."

            channels.append(Channel(
                id=legacy.id,
                name=legacy.name,
                frequency_hz=legacy.frequency_hz,
                modulation=modulation,
                service_type=service_type,
                bank_id=bank_id,
                system_name=legacy.system,
                encrypted=legacy.encrypted,
                unavailable=unavailable,
                favorite=legacy.favorite,
                priority=legacy.priority,
                locked_out=False,
                notes=notes,
            ))
        return channels

    def reload(self) -> None:
        self.channels = self._load_channels()

    def list_banks(self) -> list[Bank]:
        return sorted(self.banks, key=lambda bank: bank.priority)

    def list_channels(self) -> list[Channel]:
        return self.channels

    def list_bandplans(self) -> list[SearchRange]:
        return self.bandplans

    def get_bank(self, bank_id: str) -> Optional[Bank]:
        return next((bank for bank in self.banks if bank.id == bank_id), None)

    def set_bank_enabled(self, bank_id: str, enabled: bool) -> Optional[Bank]:
        bank = self.get_bank(bank_id)
        if bank is None:
            return None
        updated = bank.model_copy(update={"enabled": enabled})
        self.banks = [updated if item.id == bank_id else item for item in self.banks]
        return updated

    def set_channel_lockout(self, channel_id: str, locked_out: bool) -> Optional[Channel]:
        channel = self.get_channel(channel_id)
        if channel is None:
            return None
        updated = channel.model_copy(update={"locked_out": locked_out})
        self.channels = [updated if item.id == channel_id else item for item in self.channels]
        return updated

    def set_channel_priority(self, channel_id: str, priority: bool) -> Optional[Channel]:
        channel = self.get_channel(channel_id)
        if channel is None:
            return None
        updated = channel.model_copy(update={"priority": priority})
        self.channels = [updated if item.id == channel_id else item for item in self.channels]
        return updated

    def get_channel(self, channel_id: str) -> Optional[Channel]:
        return next((channel for channel in self.channels if channel.id == channel_id), None)

    def enabled_bank_ids(self) -> list[str]:
        return [bank.id for bank in self.list_banks() if bank.enabled]

    def scan_candidates(self) -> list[Channel]:
        enabled = set(self.enabled_bank_ids())
        return [
            channel
            for channel in self.channels
            if channel.bank_id in enabled
            and not channel.encrypted
            and not channel.unavailable
            and not channel.locked_out
        ]

    def first_bandplan(self, range_id: str | None = None) -> Optional[SearchRange]:
        if range_id:
            match = next((item for item in self.bandplans if item.id == range_id), None)
            if match is not None:
                return match
        return self.bandplans[0] if self.bandplans else None

    def channel_for_manual_tune(self, frequency_hz: int, modulation: str = "nfm", name: str | None = None) -> Channel:
        bank_id, service_type = self._classify_channel("custom", "custom", modulation, frequency_hz)
        return Channel(
            id=f"manual-{frequency_hz}-{modulation}",
            name=name or "Manual Tune",
            frequency_hz=frequency_hz,
            modulation=self._normalize_modulation(modulation, service_type),
            service_type=service_type,
            bank_id=bank_id,
            system_name="Manual",
            notes="Manual tune channel.",
        )

    def search_channel(self, search_range: SearchRange, index: int) -> Channel:
        width = max(search_range.end_hz - search_range.start_hz, search_range.step_hz)
        frequency = search_range.start_hz + ((index * search_range.step_hz) % width)
        return Channel(
            id=f"search-{search_range.id}-{frequency}",
            name=f"{search_range.name} Search",
            frequency_hz=frequency,
            modulation=search_range.modulation,
            service_type=search_range.service_type,
            bank_id=self._bank_for_service(search_range.service_type),
            system_name="Search",
            notes=search_range.description,
        )

    def _normalize_modulation(self, modulation: str | None, service_type: str) -> str:
        value = str(modulation or "").lower()
        if value in {"wfm", "fm_broadcast"} or service_type == "fm_broadcast":
            return "wfm"
        if value in {"am", "airband"} or service_type == "airband":
            return "am"
        if value in {"p25", "p25_placeholder"}:
            return "p25_placeholder"
        return "nfm"

    def _classify_channel(self, service: str | None, category: str | None, modulation: str | None, frequency_hz: int) -> tuple[str, str]:
        text = f"{service or ''} {category or ''} {modulation or ''}".lower()
        if "fm_radio" in text or "broadcast" in text or 88_000_000 <= frequency_hz <= 108_000_000:
            return "fm-broadcast", "fm_broadcast"
        if "weather" in text or 162_400_000 <= frequency_hz <= 162_550_000:
            return "noaa-weather", "noaa_weather"
        if "rail" in text or 160_000_000 <= frequency_hz <= 161_995_000:
            return "railroad", "railroad"
        if "air" in text or 118_000_000 <= frequency_hz <= 137_000_000:
            return "airband", "airband"
        if "marine" in text or 156_000_000 <= frequency_hz <= 162_000_000:
            return "marine", "marine"
        if "fire" in text or "ems" in text or "hospital" in text:
            return "fire-ems", "fire_ems"
        if "police" in text or "interop" in text or "public_safety" in text:
            return "public-safety", "police"
        if "public_works" in text or "utility" in text:
            return "business-local", "public_works"
        if "business" in text or "school" in text or "security" in text:
            return "business-local", "business"
        if "p25" in text or "trunk" in text:
            return "public-safety", "public_safety"
        return "custom", "custom"

    def _bank_for_service(self, service_type: str) -> str:
        return next((bank.id for bank in self.banks if bank.service_type == service_type), "custom")

