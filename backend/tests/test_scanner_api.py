from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.shared import scanner_core
from backend.app import app
from backend.sdr.rtl_sdr_receiver import RtlSdrReceiver


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_scanner():
    scanner_core.frequency_manager.reload()
    scanner_core.set_receiver_mode(True)
    scanner_core.stop()
    scanner_core.session_skipped_channel_ids.clear()
    for bank in scanner_core.banks():
        scanner_core.set_bank_enabled(bank.id, bank.id != "fm-broadcast")
    yield


def test_scanner_status_shape():
    response = client.get("/api/scanner/status")
    assert response.status_code == 200
    payload = response.json()
    for key in [
        "state",
        "is_scanning",
        "is_paused",
        "is_muted",
        "is_holding",
        "current_channel",
        "current_frequency_hz",
        "signal_level",
        "receiver_mode",
        "simulated",
        "error_message",
    ]:
        assert key in payload
    assert payload["simulated"] is True


def test_scanner_lifecycle_controls_work_without_hardware():
    assert client.post("/api/scanner/start").json()["state"] == "scanning"
    paused = client.post("/api/scanner/pause").json()
    assert paused["state"] == "paused"
    assert paused["is_paused"] is True

    resumed = client.post("/api/scanner/resume").json()
    assert resumed["state"] == "scanning"

    held = client.post("/api/scanner/hold").json()
    assert held["state"] == "holding"
    assert held["is_holding"] is True

    released = client.post("/api/scanner/release").json()
    assert released["state"] == "scanning"
    assert released["is_holding"] is False

    skipped = client.post("/api/scanner/skip").json()
    assert skipped["state"] in {"scanning", "error"}

    next_channel = client.post("/api/scanner/next").json()
    assert next_channel["state"] in {"scanning", "error"}

    stopped = client.post("/api/scanner/stop").json()
    assert stopped["state"] == "stopped"


def test_scanner_settings_and_receiver_mode():
    muted = client.post("/api/scanner/mute", json={"muted": True}).json()
    assert muted["is_muted"] is True

    gain = client.post("/api/scanner/gain", json={"gain_db": 28}).json()
    assert gain["gain_db"] == 28

    auto_gain = client.post("/api/scanner/gain", json={"gain_db": None}).json()
    assert auto_gain["gain_db"] is None

    squelch = client.post("/api/scanner/squelch", json={"squelch_db": -70}).json()
    assert squelch["squelch_db"] == -70

    receiver = client.post("/api/receiver/mode", json={"simulated": True}).json()
    assert receiver["simulated"] is True
    assert receiver["receiver_mode"] == "Demo"


def test_rtl_mode_falls_back_to_demo_when_unavailable(monkeypatch):
    monkeypatch.setattr(RtlSdrReceiver, "_load_rtl_class", lambda self: None)
    requested = client.post("/api/receiver/mode", json={"simulated": False}).json()
    assert requested["simulated"] is True
    assert requested["receiver_mode"] == "Demo"
    assert "RTL-SDR mode is unavailable" in requested["error_message"]

    receiver = client.get("/api/receiver/status").json()
    assert receiver["simulated"] is True
    assert "RTL-SDR mode is unavailable" in receiver["error_message"]


def test_rtl_receiver_missing_hardware_methods_do_not_crash(monkeypatch):
    monkeypatch.setattr(RtlSdrReceiver, "_load_rtl_class", lambda self: None)
    receiver = RtlSdrReceiver()
    assert receiver.available is False
    assert receiver.tune(162_550_000).available is False
    assert receiver.set_gain(28).available is False
    assert receiver.set_gain(None).available is False
    assert receiver.read_signal().level_db == -100.0


def test_rtl_receiver_fake_hardware_tune_gain_and_signal(monkeypatch):
    class FakeRtl:
        def __init__(self, device_index=0):
            self.device_index = device_index
            self.center_freq = None
            self.sample_rate = None
            self.gain = None
            self.closed = False

        def read_samples(self, count):
            return [0.1 + 0.1j for _ in range(count)]

        def close(self):
            self.closed = True

    monkeypatch.setattr(RtlSdrReceiver, "_load_rtl_class", lambda self: FakeRtl)
    receiver = RtlSdrReceiver()
    assert receiver.available is True

    tuned = receiver.tune(162_550_000, "nfm")
    assert tuned.available is True
    assert tuned.tuned_frequency_hz == 162_550_000
    assert receiver._device.center_freq == 162_550_000

    manual_gain = receiver.set_gain(28)
    assert manual_gain.gain_db == 28
    assert receiver._device.gain == 28

    auto_gain = receiver.set_gain(None)
    assert auto_gain.gain_db is None
    assert receiver._device.gain == "auto"

    signal = receiver.read_signal()
    assert signal.frequency_hz == 162_550_000
    assert -100.0 < signal.level_db <= 0.0
    receiver.close()


def test_rtl_receiver_uses_manual_gain_toggle_when_available(monkeypatch):
    class FakeRtl:
        def __init__(self, device_index=0):
            self.device_index = device_index
            self.center_freq = None
            self.sample_rate = None
            self.gain = None
            self.manual_gain_enabled = None

        def set_manual_gain_enabled(self, enabled):
            self.manual_gain_enabled = bool(enabled)

        def read_samples(self, count):
            return [0.05 + 0.05j for _ in range(count)]

        def close(self):
            return None

    monkeypatch.setattr(RtlSdrReceiver, "_load_rtl_class", lambda self: FakeRtl)
    receiver = RtlSdrReceiver()

    receiver.set_gain(28)
    assert receiver._device.manual_gain_enabled is True
    assert receiver._device.gain == 28

    receiver.set_gain(None)
    assert receiver._device.manual_gain_enabled is False
    assert receiver._device.gain == "auto"

    receiver.close()


def test_lockout_priority_manual_tune_and_search():
    started = client.post("/api/scanner/start").json()
    channel = started["current_channel"]
    assert channel is not None

    priority = client.post("/api/scanner/priority", json={"channel_id": channel["id"], "priority": True}).json()
    assert priority["current_channel"] is not None

    locked = client.post("/api/scanner/lockout", json={"channel_id": channel["id"]}).json()
    assert locked["current_channel"] is None or locked["current_channel"]["id"] != channel["id"]

    manual = client.post("/api/scanner/manual-tune", json={"frequency_mhz": 162.55, "modulation": "nfm"}).json()
    assert manual["state"] == "manual_tune"
    assert manual["current_frequency_hz"] == 162550000

    search = client.post("/api/scanner/search/start", json={"range_id": "noaa-weather"}).json()
    assert search["state"] == "searching"
    assert search["search_range"]["id"] == "noaa-weather"

    stopped = client.post("/api/scanner/search/stop").json()
    assert stopped["state"] == "stopped"


def test_banks_channels_bandplans_and_receiver_status():
    banks = client.get("/api/banks").json()
    assert any(bank["id"] == "public-safety" for bank in banks)

    disabled = client.post("/api/banks/public-safety/disable").json()
    assert disabled["enabled"] is False

    enabled = client.post("/api/banks/public-safety/enable").json()
    assert enabled["enabled"] is True

    channels = client.get("/api/channels").json()
    assert channels
    assert all("frequency_mhz" in channel for channel in channels)

    bandplans = client.get("/api/bandplans").json()
    assert any(item["id"] == "fm-broadcast" for item in bandplans)

    receiver = client.get("/api/receiver/status").json()
    assert receiver["simulated"] is True


def test_unavailable_channels_are_not_selected():
    scanner_core.frequency_manager.channels = [
        channel.model_copy(update={"encrypted": True, "unavailable": True})
        if index == 0 else channel
        for index, channel in enumerate(scanner_core.frequency_manager.channels)
    ]
    selected = client.post("/api/scanner/start").json()["current_channel"]
    assert selected is None or selected["encrypted"] is False
    assert selected is None or selected["unavailable"] is False
