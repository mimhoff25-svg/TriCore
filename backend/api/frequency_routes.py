from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .shared import scanner_core


router = APIRouter(prefix="/api", tags=["frequencies"])


class ScanSelectionPayload(BaseModel):
    enabled: bool
    channel_ids: list[str] = Field(default_factory=list)
    talkgroup_decimals: list[int] = Field(default_factory=list)


@router.get("/banks")
def get_banks():
    return scanner_core.banks()


@router.post("/banks/{bank_id}/enable")
def enable_bank(bank_id: str):
    before = scanner_core.frequency_manager.get_bank(bank_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Bank not found.")
    scanner_core.set_bank_enabled(bank_id, True)
    return scanner_core.frequency_manager.get_bank(bank_id)


@router.post("/banks/{bank_id}/disable")
def disable_bank(bank_id: str):
    before = scanner_core.frequency_manager.get_bank(bank_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Bank not found.")
    scanner_core.set_bank_enabled(bank_id, False)
    return scanner_core.frequency_manager.get_bank(bank_id)


@router.get("/channels")
def get_channels():
    return scanner_core.channels()


@router.post("/scan-selection")
def set_scan_selection(payload: ScanSelectionPayload):
    return scanner_core.set_scan_selection(payload.channel_ids, payload.talkgroup_decimals, payload.enabled)


@router.get("/bandplans")
def get_bandplans():
    return scanner_core.bandplans()

