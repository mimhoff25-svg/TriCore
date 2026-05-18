from __future__ import annotations

from pydantic import BaseModel


class TrunkingControllerStatus(BaseModel):
    ready: bool = False
    active: bool = False
    message: str = "Trunking control is planned later and is not active in this build."


class TrunkingControllerPlaceholder:
    def status(self) -> TrunkingControllerStatus:
        return TrunkingControllerStatus()

