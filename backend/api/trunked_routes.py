from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Query

from .shared import scanner_core


router = APIRouter(prefix="/api/trunked", tags=["trunked"])


def _talkgroup_payload(item: dict[str, Any]) -> dict[str, Any]:
    encrypted = bool(item.get("encrypted"))
    tag = str(item.get("tag") or "Other")
    service_type = str(item.get("service_type") or "custom")
    payload = dict(item)
    payload["tag"] = tag
    payload["service_type"] = service_type
    payload["monitorable"] = not encrypted
    payload["availability"] = "Locked" if encrypted else "Clear"
    payload["category"] = tag
    return payload


def _category_payload(name: str, items: list[dict[str, Any]], include_talkgroups: bool) -> dict[str, Any]:
    service_counts = Counter(str(item.get("service_type") or "custom") for item in items)
    locked_count = sum(1 for item in items if bool(item.get("encrypted")))
    payload: dict[str, Any] = {
        "name": name,
        "talkgroup_count": len(items),
        "clear_count": len(items) - locked_count,
        "locked_count": locked_count,
        "service_counts": dict(sorted(service_counts.items())),
    }
    if include_talkgroups:
        payload["talkgroups"] = items
    return payload


@router.get("/systems")
def get_trunked_systems():
    catalog = scanner_core.frequency_manager.trunked_catalog()
    talkgroups = scanner_core.frequency_manager.trunked_talkgroups(include_encrypted=True)
    category_counts = Counter(str(item.get("tag") or "Other") for item in talkgroups)
    return [
        {
            "id": catalog.get("id") or "gatrrs",
            "name": catalog.get("name") or "GATRRS",
            "short_name": catalog.get("short_name") or "GATRRS",
            "location": catalog.get("location"),
            "system_type": catalog.get("system_type"),
            "system_voice": catalog.get("system_voice"),
            "wacn": catalog.get("wacn"),
            "system_id": catalog.get("system_id"),
            "sites": catalog.get("sites") or [],
            "talkgroup_count": len(talkgroups),
            "clear_talkgroup_count": sum(1 for item in talkgroups if not bool(item.get("encrypted"))),
            "locked_talkgroup_count": sum(1 for item in talkgroups if bool(item.get("encrypted"))),
            "category_count": len(category_counts),
            "categories": dict(sorted(category_counts.items())),
            "source": catalog.get("source") or {},
        }
    ]


@router.get("/talkgroups")
def get_trunked_talkgroups(
    include_encrypted: bool = Query(default=False),
    service_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
):
    talkgroups = [
        _talkgroup_payload(item)
        for item in scanner_core.frequency_manager.trunked_talkgroups(include_encrypted=include_encrypted)
    ]
    if service_type:
        normalized_service = service_type.lower().strip()
        talkgroups = [
            item for item in talkgroups
            if str(item.get("service_type") or "").lower() == normalized_service
        ]
    if category:
        normalized_category = category.lower().strip()
        talkgroups = [
            item for item in talkgroups
            if str(item.get("tag") or "").lower() == normalized_category
        ]
    return talkgroups


@router.get("/categories")
def get_trunked_categories(
    include_encrypted: bool = Query(default=True),
    include_talkgroups: bool = Query(default=True),
):
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in scanner_core.frequency_manager.trunked_talkgroups(include_encrypted=include_encrypted):
        payload = _talkgroup_payload(item)
        groups[str(payload.get("tag") or "Other")].append(payload)

    return [
        _category_payload(name, items, include_talkgroups)
        for name, items in sorted(groups.items(), key=lambda pair: pair[0].lower())
    ]


@router.get("/status")
def get_trunking_status():
    status = scanner_core.status(advance=False)
    decoder = status.decoder
    active_channel = status.current_channel or status.active_channel
    return {
        "running": bool(decoder.active) if decoder is not None else False,
        "state": status.state,
        "message": decoder.message if decoder is not None else status.message,
        "active_channel": active_channel,
        "decoder": decoder,
    }
