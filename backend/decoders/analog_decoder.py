from __future__ import annotations

from ..radio.models import DecoderStatus
from .base_decoder import BaseDecoder


class AnalogNfmDecoder(BaseDecoder):
    id = "analog-nfm"
    label = "Analog NFM"
    modulation = "nfm"

    def status(self) -> DecoderStatus:
        return DecoderStatus(
            id=self.id,
            label=self.label,
            modulation=self.modulation,
            ready=True,
            active=False,
            message="Analog narrow FM decoder placeholder ready.",
        )

