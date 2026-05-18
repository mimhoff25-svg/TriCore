from __future__ import annotations

from ..radio.models import DecoderStatus
from .base_decoder import BaseDecoder


class AirbandDecoder(BaseDecoder):
    id = "airband-am"
    label = "Airband AM"
    modulation = "am"

    def status(self) -> DecoderStatus:
        return DecoderStatus(
            id=self.id,
            label=self.label,
            modulation=self.modulation,
            ready=True,
            active=False,
            message="AM airband decoder placeholder ready.",
        )

