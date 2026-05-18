from __future__ import annotations

from .decoder_runtime import probe_rtl_sdr_device


class SdrDevice:
    def __init__(self) -> None:
        self._snapshot = probe_rtl_sdr_device(force=True)

    @property
    def simulated(self) -> bool:
        return not bool(self._snapshot.get("available"))

    def refresh(self, force: bool = False) -> dict[str, object]:
        self._snapshot = probe_rtl_sdr_device(force=force)
        return dict(self._snapshot)

    def status_message(self) -> str:
        if self._snapshot.get("available"):
            return "RTL-SDR tuner detected. Live RF path available."
        return str(self._snapshot.get("message") or "RTL-SDR tuner not available.")

    def snapshot(self) -> dict[str, object]:
        return dict(self._snapshot)