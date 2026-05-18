from __future__ import annotations

from ..radio.models import Channel, DecoderStatus
from .base_decoder import BaseDecoder


class P25DecoderPlaceholder(BaseDecoder):
    id = "p25-placeholder"
    label = "P25 Placeholder"
    modulation = "p25_placeholder"

    def status(self) -> DecoderStatus:
        return DecoderStatus(
            id=self.id,
            label=self.label,
            modulation=self.modulation,
            ready=False,
            active=False,
            message="P25 decoding is planned later and is not active in this build.",
        )

    def tune(self, channel: Channel) -> DecoderStatus:
        return self.status().model_copy(update={
            "message": f"{channel.name} is Unavailable until the internal P25 decoder is implemented.",
        })

