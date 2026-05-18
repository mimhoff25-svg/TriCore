from __future__ import annotations

from fastapi import APIRouter

from ..core.scanner_actions import ReceiverModePayload
from .shared import scanner_core


router = APIRouter(prefix="/api/receiver", tags=["receiver"])


@router.get("/status")
def receiver_status():
    return scanner_core.receiver_status()


@router.post("/mode")
def set_receiver_mode(payload: ReceiverModePayload):
    return scanner_core.set_receiver_mode(payload.simulated)

