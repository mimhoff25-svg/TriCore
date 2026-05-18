from __future__ import annotations

from abc import ABC, abstractmethod

from ..radio.models import Channel, DecoderStatus


class BaseDecoder(ABC):
    id: str = "decoder"
    label: str = "Decoder"
    modulation: str = "nfm"

    @abstractmethod
    def status(self) -> DecoderStatus:
        raise NotImplementedError

    def tune(self, channel: Channel) -> DecoderStatus:
        status = self.status()
        return status.model_copy(update={
            "active": True,
            "message": f"{self.label} ready for {channel.name}.",
        })

