from __future__ import annotations

from .decoder_runtime import probe_rtl_sdr_device


DEMO_SNAPSHOT: dict[str, object] = {
    "available": False,
    "path": None,
    "exit_code": None,
    "output": "",
    "message": "Demo receiver mode active. No RTL-SDR hardware required.",
}


class SdrDevice:
    def __init__(self) -> None:
        self._receiver_mode = "demo"
        self._snapshot = dict(DEMO_SNAPSHOT)
        self._last_error: str | None = None

    @property
    def simulated(self) -> bool:
        return self._receiver_mode == "demo"

    @property
    def receiver_mode(self) -> str:
        return "demo" if self.simulated else "rtl_sdr"

    @property
    def receiver_label(self) -> str:
        return "Demo" if self.simulated else "RTL-SDR"

    @property
    def error_message(self) -> str | None:
        return self._last_error

    def refresh(self, force: bool = False) -> dict[str, object]:
        if self.simulated:
            self._snapshot = dict(DEMO_SNAPSHOT)
            return dict(self._snapshot)

        self._snapshot = probe_rtl_sdr_device(force=force)
        if not self._snapshot.get("available"):
            self._last_error = self._rtl_error_message(self._snapshot)
        return dict(self._snapshot)

    def set_simulated(self, simulated: bool) -> dict[str, object]:
        if simulated:
            self._receiver_mode = "demo"
            self._snapshot = dict(DEMO_SNAPSHOT)
            self._last_error = None
            return dict(self._snapshot)

        snapshot = probe_rtl_sdr_device(force=True)
        if snapshot.get("available"):
            self._receiver_mode = "rtl_sdr"
            self._snapshot = snapshot
            self._last_error = None
            return dict(self._snapshot)

        self._receiver_mode = "demo"
        self._snapshot = dict(DEMO_SNAPSHOT)
        self._last_error = self._rtl_error_message(snapshot)
        return dict(self._snapshot)

    def status_message(self) -> str:
        if self.simulated:
            return str(self._snapshot.get("message") or DEMO_SNAPSHOT["message"])
        if self._snapshot.get("available"):
            return "RTL-SDR tuner detected. Live RF path available."
        return str(self._snapshot.get("message") or "RTL-SDR tuner not available.")

    def snapshot(self) -> dict[str, object]:
        return dict(self._snapshot)

    def _rtl_error_message(self, snapshot: dict[str, object]) -> str:
        detail = str(snapshot.get("message") or "RTL-SDR tuner not available.")
        return f"RTL-SDR mode is unavailable. {detail} Staying in Demo mode."
