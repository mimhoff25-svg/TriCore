from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..database import load_channels as load_legacy_channels
from .bandplans import load_bandplans
from .banks import load_default_banks
from .models import Bank, Channel, SearchRange


AUDIBLE_AUSTIN_FM_IDS = {
    "knle-881",
    "kazi-887",
    "kmfa-895",
    "kut-905",
    "koop-917",
    "kvrx-917",
    "k221gc-921",
    "kylr-921",
    "kvlr-925",
    "k225ca-929",
    "kgsr-933",
    "klbj-937",
    "kxpelp-941",
    "kbphlp-943",
    "kcdrlp-943",
    "kkmj-955",
    "k240el-959",
    "khfi-967",
    "k246bd-971",
    "kvet-981",
    "kutx-989",
    "k259aj-997",
    "kase-1007",
    "krox-1015",
    "kpez-1023",
    "k274ax-1027",
    "k276el-1031",
    "kbpa-1035",
    "klqb-1043",
    "ktxx-1049",
    "kfmk-1059",
    "klzt-1071",
    "klja-1077",
}
RTL_MIN_TUNABLE_HZ = 24_000_000
RTL_MAX_TUNABLE_HZ = 1_766_000_000
TRUNKED_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "trunked" / "gatrrs_travis_county.json"
DEFAULT_GATRRS_TALKGROUP_DECIMALS = {
    2403,
    2405,
}
STARTER_TCSO_TALKGROUP_DECIMALS = {2403, 2404, 2405, 2406}


class FrequencyManager:
    def __init__(self) -> None:
        self.banks: list[Bank] = load_default_banks()
        self.bandplans: list[SearchRange] = load_bandplans()
        self._talkgroup_scan_overrides: dict[int, bool] = {}
        self._trunked_config_cache: dict | None = None
        self._trunked_config_mtime: float | None = None
        self.channels: list[Channel] = self._load_channels()
        self._sync_trunked_bank_enabled_state()

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
            unavailable = bool(legacy.encrypted)
            notes = "Unavailable: encrypted." if legacy.encrypted else None
            if modulation == "p25_placeholder" and notes is None:
                notes = "Managed P25 control channel. Tune individually from the P25 test bank."
            if service_type == "fm_broadcast" and legacy.id not in AUDIBLE_AUSTIN_FM_IDS:
                unavailable = True
                notes = "Outside the Austin FM scan bin or duplicate/distant listing."
            if not (RTL_MIN_TUNABLE_HZ <= legacy.frequency_hz <= RTL_MAX_TUNABLE_HZ):
                unavailable = True
                notes = (
                    f"Outside RTL-SDR tuner range "
                    f"({RTL_MIN_TUNABLE_HZ / 1_000_000:.1f}-{RTL_MAX_TUNABLE_HZ / 1_000_000:.0f} MHz)."
                )
            bank = self.get_bank(bank_id)

            channels.append(Channel(
                id=legacy.id,
                name=legacy.name,
                frequency_hz=legacy.frequency_hz,
                modulation=modulation,
                service_type=service_type,
                bank_id=bank_id,
                system_name=legacy.system,
                category=self._normalize_category(getattr(legacy, "category", None), service_type),
                encrypted=legacy.encrypted,
                unavailable=unavailable,
                favorite=legacy.favorite,
                priority=legacy.priority,
                scan_enabled=bank.enabled if bank is not None else True,
                locked_out=False,
                delay_seconds=self._coerce_delay_seconds(getattr(legacy, "delay_seconds", None)),
                number_tag=getattr(legacy, "number_tag", None),
                notes=notes,
                stream_url=legacy.stream_url,
            ))

        channels.extend(self._p25_control_channels())
        channels.extend(self._tcso_p25_channels())
        return channels

    def _load_trunked_config(self) -> dict:
        if not TRUNKED_CONFIG_PATH.exists():
            return {}
        try:
            mtime = TRUNKED_CONFIG_PATH.stat().st_mtime
            if self._trunked_config_cache is not None and self._trunked_config_mtime == mtime:
                return self._trunked_config_cache
            self._trunked_config_cache = json.loads(TRUNKED_CONFIG_PATH.read_text(encoding="utf-8"))
            self._trunked_config_mtime = mtime
            return self._trunked_config_cache
        except (OSError, json.JSONDecodeError):
            return {}

    def _p25_control_channels(self) -> list[Channel]:
        data = self._load_trunked_config()
        if not data:
            return []

        system_name = str(data.get("short_name") or data.get("name") or "P25 System")
        sites = data.get("sites") or []
        if not isinstance(sites, list):
            return []

        channels: list[Channel] = []
        bank = self.get_bank("p25-control")
        for site in sites:
            if not isinstance(site, dict):
                continue
            site_name = str(site.get("name") or site.get("id") or "Control Site")
            for index, frequency_hz in enumerate(site.get("control_channels_hz") or [], start=1):
                try:
                    parsed = int(frequency_hz)
                except (TypeError, ValueError):
                    continue
                channels.append(Channel(
                    id=f"p25-control-{site.get('id') or 'site'}-{parsed}",
                    name=f"{site_name} Control {index}",
                    frequency_hz=parsed,
                    modulation="p25_placeholder",
                    service_type="public_safety",
                    bank_id="p25-control",
                    system_name=system_name,
                    category="P25 Test",
                    encrypted=False,
                    unavailable=not (RTL_MIN_TUNABLE_HZ <= parsed <= RTL_MAX_TUNABLE_HZ),
                    scan_enabled=bank.enabled if bank is not None else False,
                    delay_seconds=0.0,
                    notes="Managed P25 control channel. Tune individually from the P25 test bank.",
                ))
        return channels

    def _tcso_p25_channels(self) -> list[Channel]:
        data = self._load_trunked_config()
        if not data:
            return []

        system_name = str(data.get("short_name") or data.get("name") or "P25 System")
        sites = data.get("sites") or []
        if not isinstance(sites, list) or not sites:
            return []
        primary_site = sites[0] if isinstance(sites[0], dict) else {}
        control_channels = [
            int(freq)
            for freq in primary_site.get("control_channels_hz") or []
            if isinstance(freq, (int, float)) or str(freq).isdigit()
        ]
        if not control_channels:
            return []

        preferred_control_channel_hz = control_channels[0]
        talkgroups = data.get("talkgroups") or []
        if not isinstance(talkgroups, list):
            return []

        channels: list[Channel] = []
        bank = self.get_bank("tcso-p25")
        for item in talkgroups:
            if not isinstance(item, dict):
                continue
            try:
                decimal = int(item.get("decimal"))
            except (TypeError, ValueError):
                continue
            if decimal not in STARTER_TCSO_TALKGROUP_DECIMALS or bool(item.get("encrypted")):
                continue

            alpha_tag = str(item.get("alpha_tag") or f"TCSO TG {decimal}")
            description = str(item.get("description") or item.get("tag") or "")
            channels.append(Channel(
                id=f"p25-tcso-{decimal}",
                name=alpha_tag,
                frequency_hz=preferred_control_channel_hz,
                modulation="p25_placeholder",
                service_type="police",
                bank_id="tcso-p25",
                system_name=system_name,
                category="Law Dispatch",
                p25_talkgroup_decimal=decimal,
                p25_control_channels_hz=control_channels,
                encrypted=False,
                unavailable=False,
                favorite=decimal == 2406,
                priority=decimal == 2406,
                scan_enabled=bank.enabled if bank is not None else True,
                delay_seconds=2.5,
                notes=description or f"TCSO talkgroup {decimal}.",
            ))

        channels.sort(key=lambda channel: (channel.p25_talkgroup_decimal or 0, channel.name))
        return channels

    def trunked_catalog(self) -> dict:
        return self._load_trunked_config()

    def trunked_talkgroups(self, include_encrypted: bool = False) -> list[dict]:
        data = self._load_trunked_config()
        talkgroups = data.get("talkgroups") or []
        if not isinstance(talkgroups, list):
            return []
        filtered = [
            {
                **dict(item),
                "scan_enabled": self.talkgroup_scan_enabled(int(item.get("decimal") or 0), encrypted=bool(item.get("encrypted"))),
            }
            for item in talkgroups
            if isinstance(item, dict) and (include_encrypted or not bool(item.get("encrypted")))
        ]
        return sorted(
            filtered,
            key=lambda item: (
                str(item.get("tag") or ""),
                int(item.get("decimal") or 0),
                str(item.get("alpha_tag") or ""),
            ),
        )

    def p25_talkgroup_channel(self, decimal: int) -> Optional[Channel]:
        data = self._load_trunked_config()
        talkgroups = data.get("talkgroups") or []
        try:
            requested_decimal = int(decimal)
        except (TypeError, ValueError):
            return None

        talkgroup = next(
            (
                item
                for item in talkgroups
                if isinstance(item, dict) and int(item.get("decimal") or -1) == requested_decimal
            ),
            None,
        )
        if not isinstance(talkgroup, dict):
            return None

        sites = data.get("sites") or []
        control_channels: list[int] = []
        if isinstance(sites, list):
            for site in sites:
                if not isinstance(site, dict):
                    continue
                for frequency_hz in site.get("control_channels_hz") or []:
                    try:
                        parsed = int(frequency_hz)
                    except (TypeError, ValueError):
                        continue
                    if parsed > 0 and parsed not in control_channels:
                        control_channels.append(parsed)

        if not control_channels:
            return None

        alpha_tag = str(talkgroup.get("alpha_tag") or f"GATRRS TG {requested_decimal}")
        description = str(talkgroup.get("description") or talkgroup.get("tag") or "")
        encrypted = bool(talkgroup.get("encrypted"))
        service_type = str(talkgroup.get("service_type") or "public_safety")
        system_name = str(data.get("short_name") or data.get("name") or "GATRRS")
        return Channel(
            id=f"gatrrs-talkgroup-{requested_decimal}",
            name=alpha_tag,
            frequency_hz=control_channels[0],
            modulation="p25_placeholder",
            service_type=service_type,
            bank_id="gatrrs-p25",
            system_name=system_name,
            category=self._talkgroup_category_name(talkgroup),
            p25_talkgroup_decimal=requested_decimal,
            p25_control_channels_hz=control_channels,
            encrypted=encrypted,
            unavailable=encrypted,
            favorite=False,
            priority=True,
            locked_out=False,
            scan_enabled=self.talkgroup_scan_enabled(requested_decimal, encrypted=encrypted),
            delay_seconds=2.5,
            notes=description or str(talkgroup.get("tag") or f"GATRRS talkgroup {requested_decimal}."),
        )

    def enabled_trunked_talkgroup_targets(self) -> list[tuple[int, str]]:
        targets = [
            (int(item.get("decimal") or 0), str(item.get("alpha_tag") or f"TG {item.get('decimal')}"))
            for item in self.trunked_talkgroups(include_encrypted=False)
            if bool(item.get("scan_enabled")) and int(item.get("decimal") or 0) > 0
        ]
        return sorted(targets, key=lambda item: item[0])

    def hold_trunked_talkgroup_targets(self, decimal: int) -> list[tuple[int, str]]:
        channel = self.p25_talkgroup_channel(decimal)
        if channel is None or channel.p25_talkgroup_decimal is None:
            return []

        selected_decimal = int(channel.p25_talkgroup_decimal)
        return [(selected_decimal, channel.name)]

    def monitorable_trunked_talkgroup_targets(self) -> list[tuple[int, str]]:
        targets = [
            (int(item.get("decimal") or 0), str(item.get("alpha_tag") or f"TG {item.get('decimal')}"))
            for item in self.trunked_talkgroups(include_encrypted=False)
            if int(item.get("decimal") or 0) > 0
        ]
        return sorted(targets, key=lambda item: item[0])

    def known_trunked_talkgroup_targets(self) -> list[tuple[int, str]]:
        targets = [
            (int(item.get("decimal") or 0), str(item.get("alpha_tag") or f"TG {item.get('decimal')}"))
            for item in self.trunked_talkgroups(include_encrypted=True)
            if int(item.get("decimal") or 0) > 0
        ]
        return sorted(targets, key=lambda item: item[0])

    def encrypted_trunked_talkgroup_decimals(self) -> list[int]:
        decimals = [
            int(item.get("decimal") or 0)
            for item in self.trunked_talkgroups(include_encrypted=True)
            if bool(item.get("encrypted")) and int(item.get("decimal") or 0) > 0
        ]
        return sorted(set(decimals))

    def trunked_scan_channel(self) -> Optional[Channel]:
        targets = self.enabled_trunked_talkgroup_targets()
        if not targets:
            return None

        data = self._load_trunked_config()
        sites = data.get("sites") or []
        control_channels: list[int] = []
        if isinstance(sites, list):
            for site in sites:
                if not isinstance(site, dict):
                    continue
                for frequency_hz in site.get("control_channels_hz") or []:
                    try:
                        parsed = int(frequency_hz)
                    except (TypeError, ValueError):
                        continue
                    if parsed > 0 and parsed not in control_channels:
                        control_channels.append(parsed)

        if not control_channels:
            return None

        system_name = str(data.get("short_name") or data.get("name") or "GATRRS")
        return Channel(
            id="trunked-scan-gatrrs",
            name=f"{system_name} Scan",
            frequency_hz=control_channels[0],
            modulation="p25_placeholder",
            service_type="public_safety",
            bank_id="gatrrs-p25",
            system_name=system_name,
            category="Trunked Scan",
            p25_control_channels_hz=control_channels,
            encrypted=False,
            unavailable=False,
            favorite=False,
            priority=False,
            scan_enabled=True,
            locked_out=False,
            delay_seconds=5.0,
            notes=f"Scanning {len(targets)} enabled GATRRS talkgroups.",
        )

    def reload(self) -> None:
        self._trunked_config_cache = None
        self._trunked_config_mtime = None
        self.channels = self._load_channels()

    def list_banks(self) -> list[Bank]:
        return sorted(self.banks, key=lambda bank: bank.priority)

    def list_channels(self) -> list[Channel]:
        return self.channels

    def list_bandplans(self) -> list[SearchRange]:
        return self.bandplans

    def get_bank(self, bank_id: str) -> Optional[Bank]:
        return next((bank for bank in self.banks if bank.id == bank_id), None)

    def set_bank_enabled(self, bank_id: str, enabled: bool, force_apply: bool = False) -> Optional[Bank]:
        bank = self.get_bank(bank_id)
        if bank is None:
            return None
        if bank.enabled == enabled and not force_apply:
            return bank
        updated = bank.model_copy(update={"enabled": enabled})
        self.banks = [updated if item.id == bank_id else item for item in self.banks]
        channel_ids = [channel.id for channel in self.channels if channel.bank_id == bank_id]
        self.set_channel_scan_enabled_bulk(channel_ids, enabled, sync_banks=False)
        return updated

    def set_channel_scan_enabled_bulk(
        self,
        channel_ids: list[str],
        enabled: bool,
        sync_banks: bool = True,
    ) -> int:
        requested = {channel_id for channel_id in channel_ids if channel_id}
        if not requested:
            return 0

        updated_count = 0
        touched_banks: set[str] = set()
        talkgroup_decimals: set[int] = set()
        next_channels: list[Channel] = []
        for channel in self.channels:
            if channel.id not in requested:
                next_channels.append(channel)
                continue
            touched_banks.add(channel.bank_id)
            if channel.p25_talkgroup_decimal is not None:
                talkgroup_decimals.add(int(channel.p25_talkgroup_decimal))
            if channel.scan_enabled == enabled:
                next_channels.append(channel)
                continue
            next_channels.append(channel.model_copy(update={"scan_enabled": enabled}))
            updated_count += 1
        self.channels = next_channels
        if talkgroup_decimals:
            self.set_talkgroup_scan_enabled_bulk(sorted(talkgroup_decimals), enabled)
        if sync_banks and touched_banks:
            self._sync_bank_enabled_states(touched_banks)
        return updated_count

    def talkgroup_scan_enabled(self, decimal: int, encrypted: bool = False) -> bool:
        if encrypted:
            return False
        normalized_decimal = int(decimal)
        return self._talkgroup_scan_overrides.get(
            normalized_decimal,
            normalized_decimal in DEFAULT_GATRRS_TALKGROUP_DECIMALS,
        )

    def set_talkgroup_scan_enabled_bulk(self, decimals: list[int], enabled: bool) -> int:
        updated_count = 0
        for decimal in {int(value) for value in decimals if value is not None}:
            current = self.talkgroup_scan_enabled(decimal)
            if current == enabled:
                continue
            self._talkgroup_scan_overrides[decimal] = enabled
            updated_count += 1
        self._sync_trunked_bank_enabled_state()
        return updated_count

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
        candidates = [
            channel
            for channel in self.channels
            if channel.scan_enabled
            and channel.modulation != "p25_placeholder"
            and not channel.encrypted
            and not channel.unavailable
            and not channel.locked_out
        ]
        trunked_scan_channel = self.trunked_scan_channel()
        if trunked_scan_channel is not None:
            candidates.append(trunked_scan_channel)
        return sorted(
            candidates,
            key=lambda channel: (
                0 if channel.priority else 1,
                0 if channel.favorite else 1,
                self._bank_priority(channel.bank_id),
                str(channel.system_name or "").lower(),
                str(channel.category or "").lower(),
                str(channel.name or "").lower(),
                int(channel.frequency_hz),
            ),
        )

    def first_bandplan(self, range_id: str | None = None) -> Optional[SearchRange]:
        if range_id:
            match = next((item for item in self.bandplans if item.id == range_id), None)
            if match is not None:
                return match
        return self.bandplans[0] if self.bandplans else None

    def channel_for_manual_tune(self, frequency_hz: int, modulation: str = "nfm", name: str | None = None) -> Channel:
        bank_id, service_type = self._classify_channel("custom", "custom", modulation, frequency_hz)
        normalized_modulation = self._normalize_modulation(modulation, service_type)
        existing = next(
            (
                channel for channel in self.channels
                if channel.frequency_hz == frequency_hz and channel.modulation == normalized_modulation
            ),
            None,
        )
        if existing is not None and not (normalized_modulation == "p25_placeholder" and existing.unavailable):
            return existing.model_copy(update={"name": name or existing.name})

        return Channel(
            id=f"manual-{frequency_hz}-{modulation}",
            name=name or "Manual Tune",
            frequency_hz=frequency_hz,
            modulation=normalized_modulation,
            service_type=service_type,
            bank_id=bank_id,
            system_name="Manual",
            category="Manual",
            scan_enabled=True,
            delay_seconds=2.0,
            notes="Manual P25 control channel." if normalized_modulation == "p25_placeholder" else "Manual tune channel.",
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
            category=search_range.name,
            scan_enabled=True,
            delay_seconds=2.0,
            notes=search_range.description,
        )

    def is_channel_scan_enabled(self, channel_id: str) -> bool:
        channel = self.get_channel(channel_id)
        return bool(channel.scan_enabled) if channel is not None else False

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
        if "p25" in text or "trunk" in text:
            return "p25-control", "public_safety"
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
        return "custom", "custom"

    def _bank_for_service(self, service_type: str) -> str:
        return next((bank.id for bank in self.banks if bank.service_type == service_type), "custom")

    def _bank_priority(self, bank_id: str) -> int:
        bank = self.get_bank(bank_id)
        return bank.priority if bank is not None else 999

    def _normalize_category(self, category: str | None, service_type: str | None = None) -> str:
        raw = str(category or "").strip()
        if raw:
            return raw
        return str(service_type or "other").strip() or "other"

    def _coerce_delay_seconds(self, value: object, default: float = 2.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.5, parsed)

    def _talkgroup_category_name(self, talkgroup: dict) -> str:
        tag = str(talkgroup.get("tag") or "").strip()
        if " / " in tag:
            return tag.split(" / ", 1)[1].strip() or "Talkgroups"
        return str(talkgroup.get("service_type") or "Talkgroups")

    def _sync_bank_enabled_states(self, bank_ids: set[str] | None = None) -> None:
        targets = bank_ids or {bank.id for bank in self.banks}
        if not targets:
            return

        enabled_by_bank = {
            bank_id: any(channel.bank_id == bank_id and channel.scan_enabled for channel in self.channels)
            for bank_id in targets
        }
        self.banks = [
            bank.model_copy(update={"enabled": enabled_by_bank.get(bank.id, bank.enabled)})
            if bank.id in targets else bank
            for bank in self.banks
        ]

    def _sync_trunked_bank_enabled_state(self) -> None:
        enabled = bool(self.enabled_trunked_talkgroup_targets())
        self.banks = [
            bank.model_copy(update={"enabled": enabled}) if bank.id == "gatrrs-p25" else bank
            for bank in self.banks
        ]
