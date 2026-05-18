from __future__ import annotations

from ..radio.models import DecoderStatus
from .base_decoder import BaseDecoder


class FmBroadcastDecoder(BaseDecoder):
    id = "fm-broadcast"
    label = "FM Broadcast"
    modulation = "wfm"

    def status(self) -> DecoderStatus:
        return DecoderStatus(
            id=self.id,
            label=self.label,
            modulation=self.modulation,
            ready=True,
            active=False,
            message="Wide FM broadcast decoder placeholder ready.",
        )

