from __future__ import annotations

from array import array
import csv
from datetime import datetime, timedelta
import queue
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.api import audio_routes
from backend.api import transcriber_routes
from backend.api.shared import scanner_core
from backend.app import app
from backend.core.scanner_state import ScannerState
from backend.decoder_runtime import SdrTrunkRuntime
from backend.decoders.p25_decoder import ManagedP25Decoder
from backend.headless_p25_runtime import HeadlessP25Runtime
from backend.radio.models import Channel, DecoderStatus, ReceiverStatus, SignalReading
from backend.transcriber import RadioTranscriber, TranscriptEntry
from backend.sdr.rtl_sdr_receiver import RtlSdrReceiver


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_scanner():
    scanner_core.frequency_manager.reload()
    scanner_core.frequency_manager._talkgroup_scan_overrides.clear()
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
    # RTL-SDR mode, not simulated
    assert payload["simulated"] is False


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

    # Always uses RTL-SDR mode now
    receiver = client.post("/api/receiver/mode", json={"simulated": False}).json()
    assert receiver["simulated"] is False


def test_system_shutdown_stops_runtime_services(monkeypatch):
    events: list[str] = []

    monkeypatch.setattr(app_module, "stop_live_audio_process", lambda: events.append("stop_audio"))
    monkeypatch.setattr(app_module.transcriber, "stop", lambda: events.append("stop_transcriber"))
    monkeypatch.setattr(app_module.scanner_core, "stop", lambda: events.append("stop_scanner"))
    monkeypatch.setattr(app_module.scanner_core, "stop_p25_decoder", lambda: events.append("stop_p25"))
    monkeypatch.setattr(app_module.scanner_core.receiver, "close", lambda: events.append("close_receiver"))
    monkeypatch.setattr(app_module, "_schedule_process_exit", lambda delay_seconds=0.1: events.append("schedule_exit"))

    response = client.post("/api/system/shutdown")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert events == [
        "stop_audio",
        "stop_transcriber",
        "stop_scanner",
        "stop_p25",
        "close_receiver",
        "schedule_exit",
    ]

    demo = client.post("/api/receiver/mode", json={"simulated": True}).json()
    assert demo["simulated"] is True

    receiver = client.post("/api/receiver/mode", json={"simulated": False}).json()
    assert receiver["simulated"] is False



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
    assert any(bank["id"] == "p25-control" for bank in banks)
    assert any(bank["id"] == "tcso-p25" for bank in banks)

    disabled = client.post("/api/banks/public-safety/disable").json()
    assert disabled["enabled"] is False
    channels_after_disable = client.get("/api/channels").json()
    assert all(channel["scan_enabled"] is False for channel in channels_after_disable if channel["bank_id"] == "public-safety")

    enabled = client.post("/api/banks/public-safety/enable").json()
    assert enabled["enabled"] is True

    channels = client.get("/api/channels").json()
    assert channels
    assert all("frequency_mhz" in channel for channel in channels)
    assert all("category" in channel and "delay_seconds" in channel and "scan_enabled" in channel for channel in channels)
    assert any(channel["bank_id"] == "p25-control" for channel in channels)
    assert any(channel["bank_id"] == "tcso-p25" for channel in channels)
    assert any(channel["name"] == "TCSO DAVID" for channel in channels)

    bandplans = client.get("/api/bandplans").json()
    assert any(item["id"] == "fm-broadcast" for item in bandplans)

    receiver = client.get("/api/receiver/status").json()
    # RTL-SDR mode, not simulated
    assert receiver["simulated"] is False


def test_p25_control_channels_are_selectable_but_not_scan_candidates():
    p25_channels = [
        channel for channel in scanner_core.frequency_manager.list_channels()
        if channel.bank_id == "p25-control"
    ]

    assert p25_channels
    assert all(channel.modulation == "p25_placeholder" for channel in p25_channels)
    assert all(channel.unavailable is False for channel in p25_channels)

    scan_candidate_ids = {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}
    assert scan_candidate_ids.isdisjoint({channel.id for channel in p25_channels})


def test_p25_classification_wins_over_generic_public_safety():
    bank_id, service_type = scanner_core.frequency_manager._classify_channel(
        "public_safety",
        "trunked",
        "p25",
        851_387_500,
    )

    assert bank_id == "p25-control"
    assert service_type == "public_safety"


def test_tcso_p25_channels_are_selectable_but_not_scan_candidates():
    tcso_channels = [
        channel for channel in scanner_core.frequency_manager.list_channels()
        if channel.bank_id == "tcso-p25"
    ]

    assert [channel.name for channel in tcso_channels] == [
        "TCSO BAKER-EAST",
        "TCSO CHARLIE",
        "TCSO ADAM-WEST",
        "TCSO DAVID",
    ]
    assert all(channel.modulation == "p25_placeholder" for channel in tcso_channels)
    assert all(channel.unavailable is False for channel in tcso_channels)
    assert all(channel.p25_talkgroup_decimal for channel in tcso_channels)

    scan_candidate_ids = {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}
    assert scan_candidate_ids.isdisjoint({channel.id for channel in tcso_channels})


def test_trunked_routes_expose_gatrrs_talkgroups_and_categories():
    talkgroups = client.get("/api/trunked/talkgroups?include_encrypted=true").json()
    assert len(talkgroups) > 700
    assert any(talkgroup["alpha_tag"] == "TCSO DAVID" for talkgroup in talkgroups)
    assert any(talkgroup["encrypted"] for talkgroup in talkgroups)
    assert all("monitorable" in talkgroup for talkgroup in talkgroups)
    assert all("scan_enabled" in talkgroup for talkgroup in talkgroups)

    categories = client.get("/api/trunked/categories?include_talkgroups=false").json()
    assert len(categories) > 50
    assert any(category["name"] == "Travis County Law Enforcement / Law Dispatch" for category in categories)
    assert all("clear_count" in category and "locked_count" in category for category in categories)

    systems = client.get("/api/trunked/systems").json()
    assert systems[0]["short_name"] == "GATRRS Travis County"
    assert systems[0]["category_count"] == len(categories)


def test_default_gatrrs_scan_targets_focus_on_baker_and_adam():
    enabled_targets = dict(scanner_core.frequency_manager.enabled_trunked_talkgroup_targets())

    assert enabled_targets == {
        2403: "TCSO BAKER-EAST",
        2405: "TCSO ADAM-WEST",
    }
    assert enabled_targets[2403] == "TCSO BAKER-EAST"
    assert "trunked-scan-gatrrs" in {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}


def test_hold_targets_follow_only_selected_talkgroup():
    adam_targets = dict(scanner_core.frequency_manager.hold_trunked_talkgroup_targets(2405))
    david_targets = dict(scanner_core.frequency_manager.hold_trunked_talkgroup_targets(2406))

    assert adam_targets == {
        2405: "TCSO ADAM-WEST",
    }
    assert david_targets == {
        2406: "TCSO DAVID",
    }


def test_transcript_entry_includes_p25_radio_metadata():
    entry = TranscriptEntry(
        channel_name="TCSO ADAM-WEST",
        frequency_hz=851_387_500,
        text="unit clear",
        call_type="routine",
        priority=2,
        confidence=0.82,
        tags=["police"],
        summary="Routine on TCSO ADAM-WEST",
        metadata={
            "talkgroup_decimal": 2405,
            "selected_talkgroup_decimal": 2405,
            "source_radio_id": "1204512",
            "target_radio_id": "2405",
            "radio_id": "1204512",
            "voice_frequency_hz": 852_012_500,
            "system_name": "GATRRS Travis County",
            "category": "Law Dispatch",
        },
    )

    payload = entry.to_dict()

    assert payload["talkgroup_decimal"] == 2405
    assert payload["selected_talkgroup_decimal"] == 2405
    assert payload["source_radio_id"] == "1204512"
    assert payload["target_radio_id"] == "2405"
    assert payload["radio_id"] == "1204512"
    assert payload["voice_frequency_hz"] == 852_012_500
    assert payload["timestamp"]


def test_scan_selection_endpoint_updates_channel_and_talkgroup_state():
    channels = client.get("/api/channels").json()
    conventional_channel = next(
        channel
        for channel in channels
        if channel["modulation"] != "p25_placeholder" and not channel["unavailable"] and not channel["encrypted"]
    )

    response = client.post(
        "/api/scan-selection",
        json={
            "enabled": False,
            "channel_ids": [conventional_channel["id"]],
            "talkgroup_decimals": [2406],
        },
    )

    assert response.status_code == 200

    updated_channels = client.get("/api/channels").json()
    updated_channel = next(channel for channel in updated_channels if channel["id"] == conventional_channel["id"])
    assert updated_channel["scan_enabled"] is False

    updated_talkgroups = client.get("/api/trunked/talkgroups?include_encrypted=true").json()
    tcso_david = next(talkgroup for talkgroup in updated_talkgroups if int(talkgroup["decimal"]) == 2406)
    assert tcso_david["scan_enabled"] is False

    scan_candidate_ids = {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}
    assert conventional_channel["id"] not in scan_candidate_ids


def test_scan_selection_endpoint_updates_tcso_channel_scan_as_talkgroup_target():
    channels = client.get("/api/channels").json()
    tcso_channel = next(
        channel
        for channel in channels
        if channel["bank_id"] == "tcso-p25" and int(channel.get("p25_talkgroup_decimal") or 0) == 2406
    )

    reset_response = client.post("/api/banks/tcso-p25/disable")
    assert reset_response.status_code == 200

    enable_response = client.post(
        "/api/scan-selection",
        json={
            "enabled": True,
            "channel_ids": [tcso_channel["id"]],
            "talkgroup_decimals": [],
        },
    )

    assert enable_response.status_code == 200
    enabled_targets = dict(scanner_core.frequency_manager.enabled_trunked_talkgroup_targets())
    assert enabled_targets == {2406: "TCSO DAVID"}
    assert "trunked-scan-gatrrs" in {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}

    disable_response = client.post(
        "/api/scan-selection",
        json={
            "enabled": False,
            "channel_ids": [tcso_channel["id"]],
            "talkgroup_decimals": [],
        },
    )

    assert disable_response.status_code == 200
    enabled_targets = dict(scanner_core.frequency_manager.enabled_trunked_talkgroup_targets())
    assert enabled_targets == {}
    assert "trunked-scan-gatrrs" not in {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}


def test_tcso_bank_toggle_controls_trunked_scan_targets():
    enable_response = client.post("/api/banks/tcso-p25/enable")

    assert enable_response.status_code == 200
    enabled_targets = dict(scanner_core.frequency_manager.enabled_trunked_talkgroup_targets())
    assert {2403, 2404, 2405, 2406}.issubset(enabled_targets)
    assert "trunked-scan-gatrrs" in {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}

    disable_response = client.post("/api/banks/tcso-p25/disable")

    assert disable_response.status_code == 200
    enabled_targets = dict(scanner_core.frequency_manager.enabled_trunked_talkgroup_targets())
    assert {2403, 2404, 2405, 2406}.isdisjoint(enabled_targets)
    assert enabled_targets == {}
    assert "trunked-scan-gatrrs" not in {channel.id for channel in scanner_core.frequency_manager.scan_candidates()}


def test_p25_talkgroup_switch_reuses_running_runtime(monkeypatch):
    start_calls: list[tuple[int, ...]] = []
    monitored_calls: list[list[tuple[int, str]]] = []
    runtime_running = {"value": False}

    def fake_start(self, force_probe=False):
        runtime_running["value"] = True
        start_calls.append(tuple(self.control_channels_hz))
        return {
            "installed": True,
            "running": True,
            "health": "ready",
            "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
            "control_channel_hz": 851387500,
            "control_channels_hz": list(self.control_channels_hz),
            "activity": {},
        }

    def fake_status(self, force_probe=False):
        return {
            "installed": True,
            "running": runtime_running["value"],
            "health": "ready" if runtime_running["value"] else "stopped",
            "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
            "control_channel_hz": 851387500,
            "control_channels_hz": list(self.control_channels_hz),
            "activity": {},
        }

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append([(int(decimal), str(alias)) for decimal, alias in talkgroups])

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", fake_start)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.status", fake_status)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.is_running", lambda self: runtime_running["value"])
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    first = client.post("/api/p25/select-talkgroup", json={"decimal": 1147})
    second = client.post("/api/p25/select-talkgroup", json={"decimal": 2403})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(start_calls) == 1
    assert monitored_calls[-1] == [(2403, "TCSO BAKER-EAST")]


def test_scan_candidates_include_trunked_scan_channel_when_talkgroup_enabled():
    response = client.post(
        "/api/scan-selection",
        json={
            "enabled": True,
            "channel_ids": [],
            "talkgroup_decimals": [2406],
        },
    )

    assert response.status_code == 200

    scan_candidates = scanner_core.frequency_manager.scan_candidates()
    trunked_scan_channel = next((channel for channel in scan_candidates if channel.id == "trunked-scan-gatrrs"), None)

    assert trunked_scan_channel is not None
    assert trunked_scan_channel.modulation == "p25_placeholder"
    assert trunked_scan_channel.p25_control_channels_hz


def test_scanner_gain_updates_managed_p25_decoder(monkeypatch):
    gain_calls: list[float | None] = []

    def fake_set_rf_gain(self, gain_db):
        gain_calls.append(gain_db)

    monkeypatch.setattr("backend.decoders.p25_decoder.ManagedP25Decoder.set_rf_gain", fake_set_rf_gain)

    response = client.post("/api/scanner/gain", json={"gain_db": 18.0})

    assert response.status_code == 200
    assert gain_calls[-1] == 18.0


def test_scanner_start_uses_trunked_scan_channel_when_only_talkgroups_enabled(monkeypatch):
    start_calls: list[tuple[int, ...]] = []
    monitored_calls: list[list[tuple[int, str]]] = []
    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 0,
        "activity": {},
    }

    for bank in list(scanner_core.banks()):
        scanner_core.set_bank_enabled(bank.id, False)

    def fake_start(self, force_probe=False):
        start_calls.append(tuple(self.control_channels_hz))
        return dict(runtime_snapshot)

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append([(int(decimal), str(alias)) for decimal, alias in talkgroups])

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", fake_start)
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    enable_response = client.post(
        "/api/scan-selection",
        json={
            "enabled": True,
            "channel_ids": [],
            "talkgroup_decimals": [2406],
        },
    )

    assert enable_response.status_code == 200

    response = client.post("/api/scanner/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "scanning"
    assert payload["current_channel"]["id"] == "trunked-scan-gatrrs"
    assert payload["current_channel"]["modulation"] == "p25_placeholder"
    assert payload["decoder"]["sync_state"] == "control_lock"
    assert start_calls[-1] == (851387500, 851137500, 851287500, 851312500)
    assert monitored_calls[-1] == [(2406, "TCSO DAVID")]


def test_scanner_advances_away_from_trunked_scan_when_voice_follow_is_stale():
    enable_response = client.post(
        "/api/scan-selection",
        json={
            "enabled": True,
            "channel_ids": [],
            "talkgroup_decimals": [2406],
        },
    )

    assert enable_response.status_code == 200

    candidates = scanner_core.frequency_manager.scan_candidates()
    trunked_scan_channel = next(channel for channel in candidates if channel.id == "trunked-scan-gatrrs")
    next_index = next(index for index, channel in enumerate(candidates) if channel.id != "trunked-scan-gatrrs")
    expected_next = candidates[next_index]

    scanner_core.current_channel = trunked_scan_channel
    scanner_core.current_decoder = DecoderStatus(
        id="p25-managed",
        label="Managed P25 Runtime",
        modulation="p25_placeholder",
        ready=True,
        active=False,
        message="Voice lock 853.8250 MHz TG 1051 RID 10620002",
        sync_state="voice_follow",
        control_channel_hz=851387500,
        control_channels_hz=[851387500, 851137500, 851287500, 851312500],
        voice_frequency_hz=853825000,
        talkgroup_decimal=1051,
        source_radio_id="10620002",
        runtime={"health": "ready"},
    )
    scanner_core.state = ScannerState.SCANNING
    scanner_core.scan_index = next_index
    scanner_core.error_message = None
    scanner_core._scan_hold_until = 0.0

    advanced = scanner_core._advance_scan()

    assert advanced is True
    assert scanner_core.current_channel is not None
    assert scanner_core.current_channel.id == expected_next.id
    assert scanner_core.current_channel.id != trunked_scan_channel.id


def test_scanner_holds_on_trunked_scan_when_recent_voice_event_is_fresh():
    enable_response = client.post(
        "/api/scan-selection",
        json={
            "enabled": True,
            "channel_ids": [],
            "talkgroup_decimals": [2406],
        },
    )

    assert enable_response.status_code == 200

    candidates = scanner_core.frequency_manager.scan_candidates()
    trunked_scan_channel = next(channel for channel in candidates if channel.id == "trunked-scan-gatrrs")
    next_index = next(index for index, channel in enumerate(candidates) if channel.id != "trunked-scan-gatrrs")

    scanner_core.current_channel = trunked_scan_channel
    scanner_core.current_decoder = DecoderStatus(
        id="p25-managed",
        label="Managed P25 Runtime",
        modulation="p25_placeholder",
        ready=True,
        active=False,
        message="Tracking GATRRS Travis County Scan.",
        sync_state="control_lock",
        control_channel_hz=851387500,
        control_channels_hz=[851387500, 851137500, 851287500, 851312500],
        talkgroup_decimal=2406,
        activity={
            "recent_events": [
                {
                    "voice_event": True,
                    "voice_frequency_hz": 852012500,
                    "talkgroup_decimal": 2406,
                    "source_radio_id": "1204512",
                },
            ],
        },
        runtime={"health": "ready"},
    )
    scanner_core.state = ScannerState.SCANNING
    scanner_core.scan_index = next_index
    scanner_core.error_message = None
    scanner_core._scan_hold_until = 0.0

    advanced = scanner_core._advance_scan()

    assert advanced is False
    assert scanner_core.current_channel is not None
    assert scanner_core.current_channel.id == trunked_scan_channel.id
    assert scanner_core._scan_hold_until > 0.0


def test_switching_between_same_frequency_p25_channels_restarts_managed_decoder(monkeypatch):
    direct_channel = scanner_core.frequency_manager.p25_talkgroup_channel(2406)
    trunked_scan_channel = scanner_core.frequency_manager.trunked_scan_channel()

    assert direct_channel is not None
    assert trunked_scan_channel is not None
    assert direct_channel.frequency_hz == trunked_scan_channel.frequency_hz

    decoder = scanner_core.decoders["p25_placeholder"]
    stop_calls: list[str] = []
    scan_calls: list[list[tuple[int, str]]] = []

    scanner_core.current_channel = direct_channel
    scanner_core.current_decoder = DecoderStatus(
        id="p25-managed",
        label="Managed P25 Runtime",
        modulation="p25_placeholder",
        ready=True,
        active=True,
        message="Tracking TCSO DAVID.",
        sync_state="control_lock",
        control_channel_hz=851387500,
        control_channels_hz=[851387500, 851137500, 851287500, 851312500],
        talkgroup_decimal=2406,
        selected_talkgroup_decimal=2406,
        runtime={"health": "ready", "engine": "dsdplus"},
    )

    monkeypatch.setattr(decoder, "stop", lambda: stop_calls.append("stop"))
    monkeypatch.setattr(decoder, "set_known_talkgroups", lambda talkgroups: None)
    monkeypatch.setattr(scanner_core, "release_rtl_receiver_for_external_audio", lambda: None)

    def fake_scan_talkgroups(control_channels_hz, talkgroups, label="P25 Scan"):
        scan_calls.append([(int(decimal), str(alias)) for decimal, alias in talkgroups])
        return DecoderStatus(
            id="p25-managed",
            label="Managed P25 Runtime",
            modulation="p25_placeholder",
            ready=True,
            active=True,
            message="Tracking GATRRS Travis County Scan.",
            sync_state="control_lock",
            control_channel_hz=851387500,
            control_channels_hz=list(control_channels_hz),
            runtime={"health": "ready", "engine": "dsdplus"},
        )

    monkeypatch.setattr(
        decoder,
        "scan_talkgroups",
        fake_scan_talkgroups,
    )

    scanner_core._tune_channel(trunked_scan_channel)

    assert stop_calls == ["stop"]
    assert scanner_core.current_channel is not None
    assert scanner_core.current_channel.id == "trunked-scan-gatrrs"
    assert scan_calls


def test_advance_scan_without_candidates_stops_active_p25_decoder(monkeypatch):
    decoder = scanner_core.decoders["p25_placeholder"]
    stop_calls: list[str] = []
    current_channel = scanner_core.frequency_manager.p25_talkgroup_channel(2406)

    assert current_channel is not None

    scanner_core.current_channel = current_channel
    scanner_core.current_decoder = DecoderStatus(
        id="p25-managed",
        label="Managed P25 Runtime",
        modulation="p25_placeholder",
        ready=True,
        active=True,
        message="Tracking TCSO DAVID.",
        sync_state="control_lock",
        control_channel_hz=851387500,
        control_channels_hz=[851387500, 851137500, 851287500, 851312500],
        talkgroup_decimal=2406,
        selected_talkgroup_decimal=2406,
        runtime={"health": "ready", "engine": "dsdplus"},
    )
    scanner_core.state = ScannerState.SCANNING

    monkeypatch.setattr(decoder, "stop", lambda: stop_calls.append("stop"))
    monkeypatch.setattr(scanner_core.frequency_manager, "scan_candidates", lambda: [])

    advanced = scanner_core._advance_scan()

    assert advanced is False
    assert stop_calls == ["stop"]
    assert scanner_core.current_channel is None
    assert scanner_core.current_decoder is None
    assert scanner_core.state == ScannerState.ERROR
    assert scanner_core.error_message == "No available channels in enabled banks."


def test_scanner_holds_on_current_channel_when_signal_is_open(monkeypatch):
    candidates = scanner_core.frequency_manager.scan_candidates()
    assert len(candidates) > 1

    first_channel = candidates[0]
    scanner_core.current_channel = first_channel
    scanner_core.current_decoder = scanner_core.decoders[first_channel.modulation].tune(first_channel)
    scanner_core.state = ScannerState.SCANNING
    scanner_core.scan_index = 1
    scanner_core.error_message = None

    monkeypatch.setattr(
        scanner_core.receiver,
        "status",
        lambda: ReceiverStatus(
            mode="rtl_sdr",
            label="RTL-SDR",
            simulated=False,
            available=True,
            demo_available=True,
            rtl_sdr_available=True,
            tuned_frequency_hz=first_channel.frequency_hz,
            squelch_db=-65.0,
            signal_level=-18.0,
            message="RTL-SDR receiver connected.",
        ),
    )
    monkeypatch.setattr(
        scanner_core.receiver,
        "read_signal",
        lambda: SignalReading(
            frequency_hz=first_channel.frequency_hz,
            level_db=-18.0,
            squelch_open=True,
            simulated=False,
        ),
    )

    status = scanner_core.status(advance=True)

    assert status.current_channel is not None
    assert status.current_channel.id == first_channel.id
    assert scanner_core.current_channel is not None
    assert scanner_core.current_channel.id == first_channel.id
    assert scanner_core.scan_index == 1
    assert status.signal_level == -18.0


def test_p25_control_lock_reports_signal_level_above_squelch(monkeypatch):
    current_channel = scanner_core.frequency_manager.p25_talkgroup_channel(2406)

    assert current_channel is not None

    scanner_core.current_channel = current_channel
    scanner_core.state = ScannerState.HOLDING
    scanner_core.settings.squelch_db = -65.0

    monkeypatch.setattr(
        scanner_core.receiver,
        "status",
        lambda: ReceiverStatus(
            mode="rtl_sdr",
            label="RTL-SDR",
            simulated=False,
            available=True,
            demo_available=True,
            rtl_sdr_available=True,
            tuned_frequency_hz=current_channel.frequency_hz,
            squelch_db=-65.0,
            signal_level=-100.0,
            message="RTL-SDR receiver connected.",
        ),
    )
    monkeypatch.setattr(
        scanner_core.decoders["p25_placeholder"],
        "status",
        lambda: DecoderStatus(
            id="p25-managed",
            label="Managed P25 Runtime",
            modulation="p25_placeholder",
            ready=True,
            active=True,
            message="Tracking TCSO DAVID.",
            sync_state="control_lock",
            control_channel_hz=851387500,
            control_channels_hz=[851387500, 851137500, 851287500, 851312500],
            talkgroup_decimal=2406,
            selected_talkgroup_decimal=2406,
            runtime={"health": "ready", "engine": "dsdplus"},
        ),
    )

    status = scanner_core.status(advance=False)
    receiver_status = scanner_core.receiver_status()

    assert status.signal_level > status.squelch_db
    assert receiver_status.signal_level > scanner_core.settings.squelch_db
    assert status.signal_level == receiver_status.signal_level


def test_p25_select_talkgroup_endpoint_tunes_managed_decoder(monkeypatch):
    start_calls: list[tuple[int, ...]] = []
    monitored_calls: list[list[tuple[int, str]]] = []
    current_timestamp = time.strftime("%Y/%m/%d  %H:%M:%S", time.localtime())
    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 3,
        "activity": {
            "voice_event": True,
            "voice_frequency_hz": 852012500,
            "talkgroup_decimal": 2406,
            "source_radio_id": "1204512",
            "target_radio_id": "2406",
            "nac": "293",
            "phase": "P25 Phase I",
            "recent_radios": [{"group": 2406, "radio": 1204512, "alias": "Car 512", "timestamp": current_timestamp}],
        },
    }

    def fake_start(self, force_probe=False):
        start_calls.append(tuple(self.control_channels_hz))
        return dict(runtime_snapshot)

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append([(int(decimal), str(alias)) for decimal, alias in talkgroups])

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", fake_start)
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    response = client.post("/api/p25/select-talkgroup", json={"decimal": 2406})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_talkgroup"]["decimal"] == 2406
    assert payload["selected_talkgroup"]["alpha_tag"] == "TCSO DAVID"
    assert payload["running"] is True
    assert payload["current_frequency_hz"] == 852012500
    assert payload["voice_frequency_hz"] == 852012500
    assert payload["talkgroup_decimal"] == 2406
    assert payload["source_radio_id"] == "1204512"
    assert payload["phase"] == "P25 Phase I"
    assert payload["recent_radios"][0]["radio"] == 1204512
    assert start_calls[-1] == (851387500, 851137500, 851287500, 851312500)
    assert monitored_calls[-1] == [(2406, "TCSO DAVID")]

    status = client.get("/api/scanner/status").json()
    assert status["current_channel"]["p25_talkgroup_decimal"] == 2406
    assert status["current_channel"]["modulation"] == "p25_placeholder"
    assert status["current_frequency_hz"] == 852012500
    assert status["active_channel"]["frequency_hz"] == 852012500
    assert status["decoder"]["voice_frequency_hz"] == 852012500
    assert status["decoder"]["source_radio_id"] == "1204512"


def test_p25_select_talkgroup_endpoint_accepts_talkgroup_decimal_alias(monkeypatch):
    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 0,
        "activity": {},
    }

    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.start",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)

    response = client.post("/api/p25/select-talkgroup", json={"talkgroup_decimal": 1147})

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_talkgroup"]["decimal"] == 1147
    assert payload["selected_talkgroup"]["alpha_tag"] == "AFD LOCUTION"


def test_managed_p25_status_hides_stale_and_off_talkgroup_activity():
    decoder = ManagedP25Decoder([851387500])
    decoder._selected_talkgroup_decimal = 2406
    decoder._selected_label = "TCSO DAVID"

    status = decoder._status_from_snapshot({
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500],
        "activity": {
            "raw": "2026/05/21  08:46:27  Freq=851.387500  NAC=137  Group call; TG=966 [APD George DT]  Ch=851.8125 Pri0",
            "voice_event": True,
            "voice_frequency_hz": 851812500,
            "talkgroup_decimal": 966,
            "source_radio_id": "10635919",
            "recent_events": [
                {
                    "raw": "2000/01/01  08:46:27  Freq=851.387500  NAC=137  Group call; TG=2406 [TCSO DAVID]  RID=1204512  Ch=852.0125 Pri0",
                    "voice_event": True,
                    "voice_frequency_hz": 852012500,
                    "talkgroup_decimal": 2406,
                    "source_radio_id": "1204512",
                },
                {
                    "raw": "2026/05/21  08:46:27  Freq=851.387500  NAC=137  Group call; TG=966 [APD George DT]  RID=10635919  Ch=851.8125 Pri0",
                    "voice_event": True,
                    "voice_frequency_hz": 851812500,
                    "talkgroup_decimal": 966,
                    "source_radio_id": "10635919",
                },
            ],
            "recent_radios": [
                {"group": 2406, "radio": 1204512, "timestamp": "2000/01/01  8:46"},
                {"group": 966, "radio": 10635919, "timestamp": "2026/05/21  8:46"},
            ],
        },
    })

    assert status.sync_state == "control_lock"
    assert status.voice_frequency_hz is None
    assert status.source_radio_id is None
    assert status.recent_radios == []
    assert status.activity["recent_events"] == []


def test_managed_p25_status_keeps_recent_selected_radio_ids_between_bursts():
    decoder = ManagedP25Decoder([851387500])
    decoder._selected_talkgroup_decimal = 2405
    decoder._selected_label = "TCSO ADAM-WEST"
    recent_timestamp = (datetime.now() - timedelta(minutes=7)).strftime("%Y/%m/%d  %H:%M:%S")

    status = decoder._status_from_snapshot({
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500],
        "activity": {
            "raw": "2026/05/21  11:37:00  Freq=851.387500  NAC=137  Group call; TG=966 [APD George DT]  Ch=851.8125 Pri0",
            "voice_event": True,
            "voice_frequency_hz": 851812500,
            "talkgroup_decimal": 966,
            "source_radio_id": "10635919",
            "recent_events": [],
            "recent_radios": [
                {"group": 2405, "radio": 10641806, "timestamp": recent_timestamp, "alias": "Adam Unit"},
                {"group": 966, "radio": 10635919, "timestamp": recent_timestamp, "alias": "Off TG"},
            ],
        },
    })

    assert status.sync_state == "control_lock"
    assert status.source_radio_id is None
    assert len(status.recent_radios) == 1
    assert status.recent_radios[0]["radio"] == 10641806


def test_p25_select_talkgroup_reuses_managed_runtime_between_talkgroups(monkeypatch):
    start_calls: list[tuple[int, ...]] = []
    stop_calls: list[tuple[int, ...]] = []
    monitored_calls: list[list[tuple[int, str]]] = []
    runtime_running = False
    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 1,
        "activity": {},
    }

    def fake_start(self, force_probe=False):
        nonlocal runtime_running
        runtime_running = True
        start_calls.append(tuple(self.control_channels_hz))
        return dict(runtime_snapshot)

    def fake_stop(self):
        nonlocal runtime_running
        runtime_running = False
        stop_calls.append(tuple(self.control_channels_hz))

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append([(int(decimal), str(alias)) for decimal, alias in talkgroups])

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", fake_start)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.is_running", lambda self: runtime_running)
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", fake_stop)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    first_response = client.post("/api/p25/select-talkgroup", json={"decimal": 2406})
    second_response = client.post("/api/p25/select-talkgroup", json={"decimal": 2455})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["selected_talkgroup"]["decimal"] == 2406
    assert second_response.json()["selected_talkgroup"]["decimal"] == 2455
    assert monitored_calls[0] == [(2406, "TCSO DAVID")]
    assert monitored_calls[-1] == [(2455, "TCSO JAIL 6")]
    assert stop_calls == []
    assert len(start_calls) == 1
    assert start_calls[-1] == (851387500, 851137500, 851287500, 851312500)


def test_managed_p25_decoder_serializes_concurrent_talkgroup_start(monkeypatch):
    decoder = ManagedP25Decoder()
    runtime_running = False
    start_calls: list[tuple[int, ...]] = []
    monitored_calls: list[list[tuple[int, str]]] = []

    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 1,
        "activity": {},
    }

    def fake_start(self, force_probe=False):
        nonlocal runtime_running
        start_calls.append(tuple(self.control_channels_hz))
        time.sleep(0.05)
        runtime_running = True
        return dict(runtime_snapshot)

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append([(int(decimal), str(alias)) for decimal, alias in talkgroups])

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", fake_start)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.is_running", lambda self: runtime_running)
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    channel = Channel(
        id="gatrrs-talkgroup-2406",
        name="TCSO DAVID",
        frequency_hz=851387500,
        modulation="p25_placeholder",
        system_name="GATRRS Travis County",
        p25_talkgroup_decimal=2406,
        p25_control_channels_hz=[851387500, 851137500, 851287500, 851312500],
    )
    threads = [threading.Thread(target=lambda: decoder.tune(channel)) for _ in range(2)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(start_calls) == 1
    assert monitored_calls[-1] == [(2406, "TCSO DAVID")]


def test_managed_p25_status_reapplies_single_talkgroup_lockout(monkeypatch):
    monitored_calls: list[list[tuple[int, str]]] = []
    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 1,
        "activity": {},
    }

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append([(int(decimal), str(alias)) for decimal, alias in talkgroups])

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", lambda self, force_probe=False: dict(runtime_snapshot))
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.is_running", lambda self: True)
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    decoder = ManagedP25Decoder()
    channel = Channel(
        id="gatrrs-talkgroup-1147",
        name="AFD LOCUTION",
        frequency_hz=851387500,
        modulation="p25_placeholder",
        system_name="GATRRS Travis County",
        p25_talkgroup_decimal=1147,
        p25_control_channels_hz=[851387500, 851137500, 851287500, 851312500],
    )

    decoder.tune(channel)
    decoder._last_monitored_apply_at = 0.0
    decoder.status()

    assert monitored_calls[-1] == [(1147, "AFD LOCUTION")]
    assert len(monitored_calls) >= 3


def test_managed_p25_status_hides_receiver_access_denied_when_runtime_is_healthy(monkeypatch):
    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 2,
        "activity": {
            "voice_event": True,
            "voice_frequency_hz": 851812500,
            "talkgroup_decimal": 1147,
            "source_radio_id": "1204512",
        },
    }

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", lambda self, force_probe=False: dict(runtime_snapshot))
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr(
        scanner_core.receiver,
        "status",
        lambda: ReceiverStatus(
            mode="rtl-sdr",
            label="RTL-SDR",
            simulated=False,
            available=False,
            demo_available=True,
            rtl_sdr_available=False,
            tuned_frequency_hz=None,
            message="RTL-SDR unavailable. Access denied.",
            error_message="RTL-SDR unavailable. Access denied.",
            last_rtl_error="RTL-SDR unavailable. Access denied.",
        ),
    )

    response = client.post("/api/p25/select-talkgroup", json={"decimal": 1147})

    assert response.status_code == 200
    scanner_status = client.get("/api/scanner/status").json()
    receiver_status = client.get("/api/receiver/status").json()

    assert scanner_status["error_message"] is None
    assert scanner_status["receiver_mode"] == "Managed P25 Runtime"
    assert scanner_status["current_frequency_hz"] == 851812500
    assert receiver_status["error_message"] is None
    assert receiver_status["last_rtl_error"] is None
    assert receiver_status["label"] == "Managed P25 Runtime"
    assert receiver_status["rtl_sdr_available"] is True
    assert receiver_status["tuned_frequency_hz"] == 851812500


def test_unavailable_channels_are_not_selected():
    scanner_core.frequency_manager.channels = [
        channel.model_copy(update={"encrypted": True, "unavailable": True})
        if index == 0 else channel
        for index, channel in enumerate(scanner_core.frequency_manager.channels)
    ]
    selected = client.post("/api/scanner/start").json()["current_channel"]
    assert selected is None or selected["encrypted"] is False
    assert selected is None or selected["unavailable"] is False


def test_rtl_mode_skips_channels_below_tuner_range(monkeypatch):
    class FakeRtl:
        def __init__(self, device_index=0):
            self.center_freq = None
            self.sample_rate = None
            self.gain = None

        def close(self):
            return None

    monkeypatch.setattr(RtlSdrReceiver, "_load_rtl_class", lambda self: FakeRtl)
    monkeypatch.setattr(
        "backend.sdr.rtl_sdr_receiver.probe_rtl_sdr_device",
        lambda force=False: {"available": True, "message": "RTL-SDR test device."},
    )
    client.post("/api/receiver/mode", json={"simulated": False})

    unsupported = client.post("/api/scanner/manual-tune", json={"frequency_mhz": 10.0, "modulation": "am"}).json()
    assert unsupported["state"] != "error"
    assert "outside the RTL-SDR tuner range" in unsupported["error_message"]

    started = client.post("/api/scanner/start").json()
    assert started["current_channel"] is None or started["current_frequency_hz"] >= 24_000_000


def test_live_audio_streams_wav_and_cleans_up_rtl_fm(monkeypatch):
    events: list[str] = []
    processes = []

    class FakeStdout:
        def __init__(self):
            self.chunks = [b"\x01\x02\x03\x04", b""]

        def read(self, count):
            return self.chunks.pop(0)

    class FakeProcess:
        returncode = None

        def __init__(self, *args, **kwargs):
            self.stdout = FakeStdout()
            self.stderr = None
            self.terminated = False
            self.killed = False
            processes.append(self)

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    monkeypatch.setattr(audio_routes, "find_runtime_tool", lambda name: Path("C:/rtl-sdr/rtl_fm.exe"))
    monkeypatch.setattr(audio_routes.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(audio_routes.scanner_core, "release_rtl_receiver_for_external_audio", lambda: events.append("release"))
    monkeypatch.setattr(audio_routes.scanner_core, "restore_rtl_receiver_after_external_audio", lambda: events.append("restore"))
    monkeypatch.setattr(audio_routes.time, "sleep", lambda seconds: None)

    response = client.get("/api/audio/live?frequency_hz=162550000&modulation=nfm")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert len(response.content[44:]) == 4
    assert events == ["release", "restore"]
    assert processes[0].terminated is True
    assert processes[0].killed is False


def test_live_audio_opens_squelch_for_nfm(monkeypatch):
    commands = []

    class FakeStdout:
        def __init__(self):
            self.reads = [b"\x00\x01" * 2048, b""]

        def read(self, size=-1):
            return self.reads.pop(0) if self.reads else b""

    class QuietProcess:
        returncode = None
        stdout = None
        stderr = None

        def __init__(self, command, *args, **kwargs):
            commands.append(command)
            self.stdout = FakeStdout()
            self.terminated = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminated = True

    monkeypatch.setattr(audio_routes, "find_runtime_tool", lambda name: Path("C:/rtl-sdr/rtl_fm.exe"))
    monkeypatch.setattr(audio_routes.subprocess, "Popen", QuietProcess)
    monkeypatch.setattr(audio_routes.scanner_core, "release_rtl_receiver_for_external_audio", lambda: None)
    monkeypatch.setattr(audio_routes.scanner_core, "restore_rtl_receiver_after_external_audio", lambda: None)
    monkeypatch.setattr(audio_routes.time, "sleep", lambda seconds: None)

    response = client.get("/api/audio/live?frequency_hz=162550000&modulation=nfm&squelch_db=-65")

    assert response.status_code == 200
    assert response.content.startswith(b"RIFF")
    assert "-l" in commands[0]
    assert commands[0][commands[0].index("-l") + 1] == "0"


def test_live_audio_applies_squelch_for_airband_am(monkeypatch):
    command, output_rate, squelch_level = audio_routes._rtl_fm_args(
        124_400_000,
        "am",
        gain_db=None,
        squelch_db=-65,
    )

    assert output_rate == 24000
    assert squelch_level == 18
    assert command[command.index("-M") + 1] == "am"
    assert command[command.index("-l") + 1] == "18"


def test_live_audio_applies_squelch_for_non_noaa_nfm(monkeypatch):
    command, output_rate, squelch_level = audio_routes._rtl_fm_args(
        464_675_000,
        "nfm",
        gain_db=None,
        squelch_db=-65,
    )

    assert output_rate == 24000
    assert squelch_level == 18
    assert command[command.index("-M") + 1] == "fm"
    assert command[command.index("-l") + 1] == "18"


def test_live_audio_reports_rtl_fm_startup_failure(monkeypatch):
    class FakeStderr:
        def read(self):
            return b"usb_open error -3"

    class FailedProcess:
        returncode = 1
        stdout = None
        stderr = FakeStderr()

        def poll(self):
            return self.returncode

    events: list[str] = []
    monkeypatch.setattr(audio_routes, "find_runtime_tool", lambda name: Path("C:/rtl-sdr/rtl_fm.exe"))
    monkeypatch.setattr(audio_routes.subprocess, "Popen", lambda *args, **kwargs: FailedProcess())
    monkeypatch.setattr(audio_routes.scanner_core, "release_rtl_receiver_for_external_audio", lambda: events.append("release"))
    monkeypatch.setattr(audio_routes.scanner_core, "restore_rtl_receiver_after_external_audio", lambda: events.append("restore"))
    monkeypatch.setattr(audio_routes.time, "sleep", lambda seconds: None)

    response = client.get("/api/audio/live?frequency_hz=104900000&modulation=wfm")

    assert response.status_code == 503
    assert "rtl_fm could not start live FM audio" in response.json()["detail"]
    assert "usb_open error -3" in response.json()["detail"]
    assert events == ["release", "restore"]


def test_live_audio_stop_endpoint_terminates_active_process():
    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.killed = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    process = FakeProcess()
    audio_routes._replace_active_process(process)

    response = client.post("/api/audio/stop")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert process.terminated is True
    assert process.killed is False


def test_live_audio_shares_transcriber_stream_when_running(monkeypatch):
    subscriber: queue.Queue[bytes] = queue.Queue()
    subscriber.put(b"\x00\x01" * 2048)

    monkeypatch.setattr("backend.transcriber.transcriber.running", True)
    monkeypatch.setattr("backend.transcriber.transcriber.subscribe_audio", lambda: subscriber)
    monkeypatch.setattr("backend.transcriber.transcriber.unsubscribe_audio", lambda subscribed: None)

    response = audio_routes.live_audio(frequency_hz=162550000, modulation="nfm")

    assert response.status_code == 200
    assert response.headers["X-TriCore-Audio"] == "transcriber"


def test_live_audio_shares_transcriber_stream_for_p25_when_running(monkeypatch):
    subscriber: queue.Queue[bytes] = queue.Queue()
    subscriber.put(b"\x00\x01" * 2048)

    monkeypatch.setattr("backend.transcriber.transcriber.running", True)
    monkeypatch.setattr("backend.transcriber.transcriber.subscribe_audio", lambda: subscriber)
    monkeypatch.setattr("backend.transcriber.transcriber.unsubscribe_audio", lambda subscribed: None)

    response = audio_routes.live_audio(frequency_hz=851387500, modulation="p25_placeholder")

    assert response.status_code == 200
    assert response.headers["X-TriCore-Audio"] == "transcriber"


def test_transcriber_start_failure_restores_receiver(monkeypatch):
    events: list[str] = []

    monkeypatch.setattr(transcriber_routes, "stop_live_audio_process", lambda: events.append("stop_audio"))
    monkeypatch.setattr(
        transcriber_routes.scanner_core,
        "release_rtl_receiver_for_external_audio",
        lambda: events.append("release"),
    )
    monkeypatch.setattr(
        transcriber_routes.scanner_core,
        "restore_rtl_receiver_after_external_audio",
        lambda: events.append("restore"),
    )
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "status",
        lambda: {"running": False, "error": None, "transcript_count": 0, "current_channel": None},
    )
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "start",
        lambda channels: {"ok": False, "error": "rtl_fm.exe not found. Check runtime tools."},
    )
    monkeypatch.setattr(transcriber_routes.transcriber, "get_transcripts", lambda: [])

    response = client.post("/api/transcriber/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "runtime tools" in payload["error"]
    assert events == ["stop_audio", "release", "restore"]


def test_transcriber_start_supports_active_p25_channel(monkeypatch):
    events: list[str] = []
    captured: dict[str, object] = {}
    p25_channel = Channel(
        id="p25-afd-1147",
        name="AFD LOCUTION",
        frequency_hz=851_387_500,
        modulation="p25_placeholder",
        service_type="fire_ems",
        bank_id="p25-control",
        p25_talkgroup_decimal=1147,
    )

    monkeypatch.setattr(transcriber_routes, "stop_live_audio_process", lambda: events.append("stop_audio"))
    monkeypatch.setattr(
        transcriber_routes.scanner_core,
        "receiver_status",
        lambda: type("ReceiverStatus", (), {
            "available": False,
            "error_message": "RTL-SDR unavailable.",
            "message": "RTL-SDR unavailable.",
        })(),
    )
    monkeypatch.setattr(transcriber_routes.scanner_core, "current_channel", p25_channel, raising=False)
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "status",
        lambda: {"running": False, "error": None, "transcript_count": 0, "current_channel": p25_channel.name, "current_modulation": p25_channel.modulation},
    )
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "start",
        lambda channels, p25_audio_path=None, metadata_provider=None: captured.update({
            "channels": channels,
            "p25_audio_path": p25_audio_path,
            "metadata_provider": metadata_provider,
        }) or {"ok": True, "channels": len(channels)},
    )
    monkeypatch.setattr(transcriber_routes.transcriber, "get_transcripts", lambda: [])
    monkeypatch.setattr(
        scanner_core.decoders["p25_placeholder"],
        "audio_wav_path",
        lambda: Path("C:/runtime/dsdplus-profile/1R-DSDPlus.wav"),
        raising=False,
    )

    response = client.post("/api/transcriber/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert captured["channels"] == [p25_channel]
    assert captured["p25_audio_path"] == Path("C:/runtime/dsdplus-profile/1R-DSDPlus.wav")
    assert callable(captured["metadata_provider"])
    assert events == ["stop_audio"]


def test_transcriber_status_merges_live_p25_radio_metadata_for_any_talkgroup(monkeypatch):
    p25_channel = Channel(
        id="p25-afd-1147",
        name="AFD LOCUTION",
        frequency_hz=851_387_500,
        modulation="p25_placeholder",
        service_type="fire_ems",
        bank_id="gatrrs-p25",
        category="Fire Dispatch",
        p25_talkgroup_decimal=1147,
    )
    monkeypatch.setattr(transcriber_routes.scanner_core, "current_channel", p25_channel, raising=False)
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "status",
        lambda: {
            "running": True,
            "error": None,
            "transcript_count": 0,
            "current_channel": p25_channel.name,
            "current_modulation": p25_channel.modulation,
        },
    )
    monkeypatch.setattr(transcriber_routes.transcriber, "get_transcripts", lambda: [])
    monkeypatch.setattr(
        scanner_core.decoders["p25_placeholder"],
        "status",
        lambda: DecoderStatus(
            id="p25-managed",
            label="Managed P25 Runtime",
            modulation="p25_placeholder",
            ready=True,
            active=True,
            talkgroup_decimal=1147,
            selected_talkgroup_decimal=1147,
            source_radio_id="773311",
            target_radio_id="1147",
            voice_frequency_hz=852_012_500,
            runtime={"engine": "dsdplus", "health": "ready"},
        ),
    )

    response = client.get("/api/transcriber/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_talkgroup_decimal"] == 1147
    assert payload["current_radio_id"] == "773311"
    assert payload["current_source_radio_id"] == "773311"
    assert payload["current_voice_frequency_hz"] == 852_012_500


def test_transcriber_stop_restores_receiver(monkeypatch):
    events: list[str] = []

    monkeypatch.setattr(transcriber_routes.transcriber, "stop", lambda: events.append("stop"))
    monkeypatch.setattr(
        transcriber_routes.scanner_core,
        "restore_rtl_receiver_after_external_audio",
        lambda: events.append("restore"),
    )
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "status",
        lambda: {"running": False, "error": None, "transcript_count": 0, "current_channel": None},
    )
    monkeypatch.setattr(transcriber_routes.transcriber, "get_transcripts", lambda: [])

    response = client.post("/api/transcriber/stop")

    assert response.status_code == 200
    assert events == ["stop", "restore"]


def test_transcriber_uses_fm_for_noaa_nfm(monkeypatch):
    recorded: list[list[str]] = []

    class FakeStdout:
        def __init__(self):
            self.chunks = [b"\x00\x00" * 2000, b""]

        def read(self, count):
            return self.chunks.pop(0)

    class FakeProcess:
        def __init__(self, command, *args, **kwargs):
            recorded.append(command)
            self.stdout = FakeStdout()
            self.returncode = None
            self._terminated = False

        def poll(self):
            return None if not self._terminated else 0

        def terminate(self):
            self._terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self._terminated = True

    monkeypatch.setattr("backend.transcriber.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("backend.transcriber.runtime_subprocess_env", lambda *args: {})

    service = RadioTranscriber(model_size="base")
    channel = Channel(
        id="noaa-1",
        name="NOAA Weather 1",
        frequency_hz=162_550_000,
        modulation="nfm",
        service_type="noaa_weather",
        bank_id="noaa-weather",
    )

    service._listen_channel(channel, "C:/rtl-sdr/rtl_fm.exe")

    assert recorded
    command = recorded[0]
    assert command[command.index("-M") + 1] == "fm"
    assert command.count("-E") >= 2
    assert command[command.index("offset") - 1] == "-E"
    assert command[command.index("deemp") - 1] == "-E"


def test_transcriber_start_accepts_p25_audio_source(monkeypatch):
    launched_threads: list[tuple[object, tuple[object, ...]]] = []

    class FakeThread:
        def __init__(self, target=None, args=(), kwargs=None, **_):
            launched_threads.append((target, args))

        def start(self):
            return None

    monkeypatch.setattr("backend.transcriber.find_runtime_tool", lambda name: None)
    monkeypatch.setattr("backend.transcriber.threading.Thread", FakeThread)

    service = RadioTranscriber(model_size="base")
    channel = Channel(
        id="p25-afd-1147",
        name="AFD LOCUTION",
        frequency_hz=851_387_500,
        modulation="p25_placeholder",
        service_type="fire_ems",
        p25_talkgroup_decimal=1147,
    )

    payload = service.start([channel], p25_audio_path=Path("C:/runtime/dsdplus-profile/1R-DSDPlus.wav"))

    assert payload["ok"] is True
    assert payload["channels"] == 1
    assert service.running is True
    assert service._p25_audio_path == Path("C:/runtime/dsdplus-profile/1R-DSDPlus.wav")
    assert len(launched_threads) == 2
    service.stop()


def test_transcriber_queue_preserves_p25_metadata_seen_during_audio_chunk(monkeypatch):
    service = RadioTranscriber(model_size="base")
    channel = Channel(
        id="gatrrs-talkgroup-2405",
        name="TCSO ADAM-WEST",
        frequency_hz=851_387_500,
        modulation="p25_placeholder",
        service_type="police",
        p25_talkgroup_decimal=2405,
    )
    monkeypatch.setattr(
        service,
        "_metadata_for_channel",
        lambda _channel: {
            "talkgroup_decimal": 2405,
            "selected_talkgroup_decimal": 2405,
        },
    )

    service._queue_transcribe_chunk(
        b"\x01\x00" * 160,
        channel,
        metadata={
            "talkgroup_decimal": 2405,
            "source_radio_id": "10550070",
            "voice_frequency_hz": 853_050_000,
        },
    )

    raw, queued_channel, metadata = service._transcription_queue.get_nowait()

    assert raw
    assert queued_channel is channel
    assert metadata["talkgroup_decimal"] == 2405
    assert metadata["source_radio_id"] == "10550070"
    assert metadata["radio_id"] == "10550070"
    assert metadata["voice_frequency_hz"] == 853_050_000


def test_transcriber_scan_loop_treats_missing_p25_wav_as_transient(monkeypatch):
    service = RadioTranscriber(model_size="base")
    channel = Channel(
        id="p25-afd-1147",
        name="AFD LOCUTION",
        frequency_hz=851_387_500,
        modulation="p25_placeholder",
        service_type="fire_ems",
        p25_talkgroup_decimal=1147,
    )
    sleep_calls: list[float] = []

    def fake_listen_p25_channel(_channel, _audio_path):
        raise RuntimeError("Managed P25 audio WAV is not available.")

    def fake_sleep(seconds):
        sleep_calls.append(float(seconds))
        service._stop_event.set()

    monkeypatch.setattr(service, "_listen_p25_channel", fake_listen_p25_channel)
    monkeypatch.setattr("backend.transcriber.time.sleep", fake_sleep)

    service.running = True
    service._scan_loop([channel], None, Path("C:/runtime/dsdplus-profile/1R-DSDPlus.wav"))

    assert sleep_calls == [0.5]
    assert service.error is None
    assert service.running is False


def test_transcriber_normalizes_p25_audio_to_mono_16k():
    service = RadioTranscriber(model_size="base")
    raw_samples = array("h", [1000, 1000, -1000, -1000])

    normalized, remainder = service._normalize_audio_samples(raw_samples.tobytes() + b"\x00", channel_count=2, sample_rate=8000)

    output_samples = array("h")
    output_samples.frombytes(normalized)
    assert remainder == b"\x00"
    assert output_samples.tolist() == [1000, 1000, -1000, -1000]


def test_transcriber_start_fails_when_receiver_unavailable(monkeypatch):
    monkeypatch.setattr(
        transcriber_routes.scanner_core,
        "receiver_status",
        lambda: type("ReceiverStatus", (), {
            "available": False,
            "error_message": "RTL-SDR unavailable. Access denied.",
            "message": "RTL-SDR unavailable. Access denied.",
        })(),
    )
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "status",
        lambda: {"running": False, "error": None, "transcript_count": 0, "current_channel": None},
    )
    monkeypatch.setattr(transcriber_routes.transcriber, "get_transcripts", lambda: [])

    response = client.post("/api/transcriber/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "Access denied" in payload["error"]


def test_manual_tune_p25_starts_managed_decoder(monkeypatch):
    start_calls: list[tuple[int, ...]] = []

    def fake_start(self, force_probe=False):
        start_calls.append(tuple(self.control_channels_hz))
        return {
            "installed": True,
            "running": True,
            "health": "ready",
            "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        }

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", fake_start)
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: {
            "installed": True,
            "running": True,
            "health": "ready",
            "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        },
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)

    response = client.post(
        "/api/scanner/manual-tune",
        json={"frequency_mhz": 851.3875, "modulation": "p25", "name": "GATRRS Control"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert start_calls[-1] == (851387500,)
    assert payload["current_channel"]["modulation"] == "p25_placeholder"
    assert payload["decoder"]["label"] == "Managed P25 Runtime"
    assert payload["decoder"]["active"] is True
    assert "Headless DSDPlus" in payload["decoder"]["message"]


def test_tuning_tcso_channel_prioritizes_talkgroup(monkeypatch):
    start_calls: list[tuple[int, ...]] = []
    monitored_calls: list[tuple[list[tuple[int, str]], tuple[int, ...]]] = []
    runtime_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 4,
        "activity": {
            "voice_event": True,
            "voice_frequency_hz": 852012500,
            "talkgroup_decimal": 2406,
            "source_radio_id": "1204512",
            "target_radio_id": "2406",
            "phase": "P25 Phase I",
            "nac": "293",
        },
    }

    def fake_start(self, force_probe=False):
        start_calls.append(tuple(self.control_channels_hz))
        return dict(runtime_snapshot)

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append(([(int(decimal), str(alias)) for decimal, alias in talkgroups], tuple(self.control_channels_hz)))

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.start", fake_start)
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(runtime_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    response = client.post("/api/scanner/tune", json={"channel_id": "p25-tcso-2406"})

    assert response.status_code == 200
    payload = response.json()
    expected_control_channels = (851387500, 851137500, 851287500, 851312500)
    assert start_calls[-1] == expected_control_channels
    assert monitored_calls[-1] == ([(2406, "TCSO DAVID")], expected_control_channels)
    assert payload["current_channel"]["name"] == "TCSO DAVID"
    assert payload["current_channel"]["p25_talkgroup_decimal"] == 2406
    assert payload["current_frequency_hz"] == 852012500
    assert payload["active_channel"]["frequency_hz"] == 852012500
    assert payload["decoder"]["voice_frequency_hz"] == 852012500
    assert payload["decoder"]["talkgroup_decimal"] == 2406
    assert payload["decoder"]["source_radio_id"] == "1204512"
    assert payload["decoder"]["sync_state"] == "voice_follow"
    assert "Tracking TCSO DAVID" in payload["decoder"]["message"]


def test_tuning_tcso_channel_filters_unselected_runtime_activity(monkeypatch):
    monitored_calls: list[tuple[list[tuple[int, str]], tuple[int, ...]]] = []
    start_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 4,
        "activity": {
            "voice_event": True,
            "voice_frequency_hz": 852012500,
            "talkgroup_decimal": 2406,
            "source_radio_id": "1204512",
        },
    }
    status_snapshot = {
        "installed": True,
        "running": True,
        "health": "ready",
        "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        "control_channel_hz": 851387500,
        "control_channels_hz": [851387500, 851137500, 851287500, 851312500],
        "p25data_records": 5,
        "activity": {
            "voice_event": True,
            "voice_frequency_hz": 853050000,
            "talkgroup_decimal": 2453,
            "source_radio_id": "1001222",
            "target_radio_id": "2453",
            "recent_events": [
                {
                    "voice_event": True,
                    "voice_frequency_hz": 853050000,
                    "talkgroup_decimal": 2453,
                    "source_radio_id": "1001222",
                },
            ],
        },
    }

    def fake_set_monitored(self, talkgroups, network_id="BEE09.13E"):
        monitored_calls.append(([(int(decimal), str(alias)) for decimal, alias in talkgroups], tuple(self.control_channels_hz)))

    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.start",
        lambda self, force_probe=False: dict(start_snapshot),
    )
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: dict(status_snapshot),
    )
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_monitored_talkgroups", fake_set_monitored)

    response = client.post("/api/scanner/tune", json={"channel_id": "p25-tcso-2406"})

    assert response.status_code == 200
    payload = response.json()
    expected_control_channels = (851387500, 851137500, 851287500, 851312500)
    assert monitored_calls[-1] == ([(2406, "TCSO DAVID")], expected_control_channels)
    assert payload["current_frequency_hz"] == 851387500
    assert payload["decoder"]["voice_frequency_hz"] is None
    assert payload["decoder"]["talkgroup_decimal"] == 2406
    assert payload["decoder"]["sync_state"] == "control_lock"
    assert "2453" not in payload["decoder"]["message"]


def test_runtime_set_monitored_talkgroups_demotes_stale_priority_entries(tmp_path, monkeypatch):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    monkeypatch.setattr(runtime, "_ensure_profile", lambda: None)

    groups_path = tmp_path / "DSDPlus.groups"
    groups_path.write_text(
        "\n".join([
            "; DSD+ groups",
            'P25,       BEE09.13E, 2406,       1,   Normal,       0,  0000/00/00  0:00,  "TCSO DAVID"',
            'P25,       BEE09.13E, 2455,       1,   Normal,       0,  0000/00/00  0:00,  "TCSO JAIL 6"',
            '',
        ]),
        encoding="utf-8",
    )

    runtime.set_monitored_talkgroups([(2406, "TCSO DAVID")])

    lines = groups_path.read_text(encoding="utf-8").splitlines()
    locked_line = next(line for line in lines if "2406" in line and "BEE09.13E" in line)
    stale_line = next(line for line in lines if "2455" in line and "BEE09.13E" in line)
    locked_fields = next(csv.reader([locked_line], skipinitialspace=True))
    stale_fields = next(csv.reader([stale_line], skipinitialspace=True))
    assert locked_fields[3].strip() == "1"
    assert locked_fields[4].strip() == "High"
    assert "TCSO DAVID" in locked_line
    assert stale_fields[3].strip() == "99"
    assert stale_fields[4].strip() == "L/O"


def test_runtime_set_monitored_talkgroups_updates_wildcard_network_entries(tmp_path, monkeypatch):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    monkeypatch.setattr(runtime, "_ensure_profile", lambda: None)

    groups_path = tmp_path / "DSDPlus.groups"
    groups_path.write_text(
        "\n".join([
            "; DSD+ groups",
            'P25,       0, 1147,       50,  Normal,       0,  0000/00/00  0:00,  "AFD LOCUTION"',
            'P25,       0, 2651,       50,  Normal,       0,  0000/00/00  0:00,  "TCCN PCT5"',
            '',
        ]),
        encoding="utf-8",
    )

    runtime.set_monitored_talkgroups([(1147, "AFD LOCUTION")])

    lines = groups_path.read_text(encoding="utf-8").splitlines()
    wildcard_locked_line = next(line for line in lines if 'P25,       0,' in line and '1147' in line)
    wildcard_stale_line = next(line for line in lines if 'P25,       0,' in line and '2651' in line)
    explicit_locked_line = next(line for line in lines if 'BEE09.13E' in line and '1147' in line)
    wildcard_locked_fields = next(csv.reader([wildcard_locked_line], skipinitialspace=True))
    wildcard_stale_fields = next(csv.reader([wildcard_stale_line], skipinitialspace=True))
    explicit_locked_fields = next(csv.reader([explicit_locked_line], skipinitialspace=True))

    assert wildcard_locked_fields[3].strip() == "1"
    assert wildcard_locked_fields[4].strip() == "High"
    assert wildcard_stale_fields[3].strip() == "99"
    assert wildcard_stale_fields[4].strip() == "L/O"
    assert explicit_locked_fields[3].strip() == "1"
    assert explicit_locked_fields[4].strip() == "High"


def test_runtime_set_monitored_talkgroups_seeds_known_lockouts(tmp_path, monkeypatch):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    monkeypatch.setattr(runtime, "_ensure_profile", lambda: None)

    groups_path = tmp_path / "DSDPlus.groups"
    groups_path.write_text("; DSD+ groups\n", encoding="utf-8")

    runtime.set_known_talkgroups([(2406, "TCSO DAVID"), (2455, "TCSO JAIL 6")])
    runtime.set_monitored_talkgroups([(2406, "TCSO DAVID")])

    lines = groups_path.read_text(encoding="utf-8").splitlines()
    selected_line = next(line for line in lines if "BEE09.13E" in line and "2406" in line)
    locked_line = next(line for line in lines if "BEE09.13E" in line and "2455" in line)
    selected_fields = next(csv.reader([selected_line], skipinitialspace=True))
    locked_fields = next(csv.reader([locked_line], skipinitialspace=True))

    assert selected_fields[3].strip() == "1"
    assert selected_fields[4].strip() == "High"
    assert locked_fields[3].strip() == "99"
    assert locked_fields[4].strip() == "L/O"


def test_runtime_recent_radios_keeps_more_than_last_ten_records(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    radios_path = tmp_path / "DSDPlus.radios"
    current_timestamp = time.strftime("%Y/%m/%d  %H:%M", time.localtime())

    lines = ["; DSD+ radios"]
    lines.append(f'P25,       BEE09.13E, 2405,       10641806,   50,  Normal,       3,  {current_timestamp},  ""')
    for offset in range(150):
        lines.append(
            f'P25,       BEE09.13E, {5000 + offset},       {11000000 + offset},   50,  Normal,       1,  {current_timestamp},  ""'
        )
    radios_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recent_radios = runtime._recent_radios()

    assert any(item["group"] == 2405 and item["radio"] == 10641806 for item in recent_radios)
    assert len(recent_radios) == 151


def test_runtime_log_snapshot_surfaces_busy_device_details(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)

    (runtime.log_root / "fmp24-control.log").write_text(
        "\n".join([
            "FMP24 2.86",
            "SDR device count = 2",
            "SDR device #1 is in use",
            "SDR device #2 serial string = '00000001'",
            "Serial string = '00000001'",
            "Error - remove/reinsert dongle with serial string '00000001'",
        ]),
        encoding="utf-8",
    )

    snapshot = runtime._log_snapshot()

    assert snapshot["error_health"] == "no_tuner"
    assert "RTL device #1 was already in use" in snapshot["error_message"]
    assert "It attempted RTL device #2" in snapshot["error_message"]
    assert "serial 00000001" in snapshot["error_message"]
    assert snapshot["error_detail"] is not None
    assert snapshot["tuner_log"]["device_count"] == 2
    assert snapshot["tuner_log"]["busy_device_numbers"] == [1]
    assert snapshot["tuner_log"]["selected_device_number"] == 2
    assert snapshot["tuner_log"]["selected_serial"] == "00000001"
    assert snapshot["tuner_log"]["failing_serial"] == "00000001"


def test_runtime_log_snapshot_surfaces_no_available_device_details(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)

    (runtime.log_root / "fmp24-control.log").write_text(
        "\n".join([
            "FMP24 2.86",
            "SDR device count = 2",
            "SDR device #1 is in use",
            "SDR device #2 is in use",
            "No available RTL SDR devices found",
        ]),
        encoding="utf-8",
    )

    snapshot = runtime._log_snapshot()

    assert snapshot["error_health"] == "no_tuner"
    assert snapshot["error_message"] is not None
    assert "could not find an available RTL-SDR tuner" in snapshot["error_message"]
    assert "FMP24 saw 2 RTL devices" in snapshot["error_message"]
    assert "RTL devices #1, #2 were already in use" in snapshot["error_message"]
    assert snapshot["tuner_log"]["device_count"] == 2
    assert snapshot["tuner_log"]["busy_device_numbers"] == [1, 2]


def test_runtime_status_includes_tuner_error_details(monkeypatch):
    runtime = HeadlessP25Runtime([851387500])

    monkeypatch.setattr(runtime, "_refresh_processes", lambda: None)
    monkeypatch.setattr(runtime, "_tool_paths", lambda: {"fmp24": Path("C:/fmp24.exe"), "dsdplus": Path("C:/DSDPlus.exe")})
    monkeypatch.setattr(runtime, "_maybe_failover", lambda tool_paths: False)
    monkeypatch.setattr(
        runtime,
        "_log_snapshot",
        lambda: {
            "last_line": "Error - remove/reinsert dongle with serial string '00000001'",
            "error_message": "FMP24 opened the RTL-SDR but the receiver reported a hardware error.",
            "error_health": "no_tuner",
            "error_detail": "FMP24 saw 2 RTL devices. RTL device #1 was already in use.",
            "event_log_path": None,
            "tuner_log": {
                "device_count": 2,
                "busy_device_numbers": [1],
                "selected_device_number": 2,
                "selected_serial": "00000001",
                "failing_serial": "00000001",
            },
        },
    )
    monkeypatch.setattr(runtime, "_p25data_snapshot", lambda: {"path": None, "record_count": 0, "last_line": None})
    monkeypatch.setattr(runtime, "_activity_snapshot", lambda: {})
    monkeypatch.setattr(runtime, "_control_activity_detected", lambda: False)
    monkeypatch.setattr(
        "backend.headless_p25_runtime.probe_rtl_sdr_device",
        lambda force=False: {"available": False, "message": "No tuner"},
    )

    snapshot = runtime.status()

    assert snapshot["health"] == "driver_conflict"
    assert "FMP24 opened the RTL-SDR but the receiver reported a hardware error." in snapshot["message"]
    assert "Fix-RtlP25Conflict.ps1" in snapshot["message"]
    assert snapshot["error_detail"] == "FMP24 saw 2 RTL devices. RTL device #1 was already in use."
    assert snapshot["tuner_log"]["device_count"] == 2
    assert snapshot["tuner_log"]["busy_device_numbers"] == [1]


def test_runtime_status_stops_failed_processes_after_tuner_error(monkeypatch):
    runtime = HeadlessP25Runtime([851387500])
    runtime._started_at = 1.0
    runtime._processes = {
        "fmp24-control": type("FakeProcess", (), {"pid": 1234})(),
        "dsdplus-1r": type("FakeProcess", (), {"pid": 5678})(),
    }

    stop_calls: list[bool] = []

    monkeypatch.setattr(runtime, "_refresh_processes", lambda: None)
    monkeypatch.setattr(runtime, "_tool_paths", lambda: {"fmp24": Path("C:/fmp24.exe"), "dsdplus": Path("C:/DSDPlus.exe")})
    monkeypatch.setattr(runtime, "_maybe_failover", lambda tool_paths: False)
    monkeypatch.setattr(
        runtime,
        "_log_snapshot",
        lambda: {
            "last_line": "Error - remove/reinsert dongle with serial string '00000001'",
            "error_message": "FMP24 opened the RTL-SDR but the receiver reported a hardware error.",
            "error_health": "no_tuner",
            "error_detail": "FMP24 saw 2 RTL devices. RTL device #1 was already in use.",
            "event_log_path": None,
            "tuner_log": {
                "device_count": 2,
                "busy_device_numbers": [1],
            },
        },
    )
    monkeypatch.setattr(runtime, "_p25data_snapshot", lambda: {"path": None, "record_count": 0, "last_line": None})
    monkeypatch.setattr(runtime, "_activity_snapshot", lambda: {})
    monkeypatch.setattr(runtime, "_control_activity_detected", lambda: False)
    monkeypatch.setattr(
        runtime,
        "_stop_processes",
        lambda reset_hunt: (stop_calls.append(reset_hunt), runtime._processes.clear(), setattr(runtime, "_started_at", None)),
    )
    monkeypatch.setattr(
        "backend.headless_p25_runtime.probe_rtl_sdr_device",
        lambda force=False: {"available": True, "message": "RTL-SDR tuner detected."},
    )

    snapshot = runtime.status()

    assert stop_calls == [False]
    assert snapshot["health"] == "driver_conflict"
    assert snapshot["running"] is False
    assert snapshot["processes"] == {}
    assert snapshot["error_detail"] == "FMP24 saw 2 RTL devices. RTL device #1 was already in use."
    assert "DSDPlus/FMP24 RTL driver stack cannot" in snapshot["message"]
    assert "Fix-RtlP25Conflict.ps1" in snapshot["message"]


def test_runtime_status_treats_all_busy_fmp_devices_as_driver_conflict(monkeypatch):
    runtime = HeadlessP25Runtime([851387500])

    monkeypatch.setattr(runtime, "_refresh_processes", lambda: None)
    monkeypatch.setattr(runtime, "_tool_paths", lambda: {"fmp24": Path("C:/fmp24.exe"), "dsdplus": Path("C:/DSDPlus.exe")})
    monkeypatch.setattr(runtime, "_maybe_failover", lambda tool_paths: False)
    monkeypatch.setattr(
        runtime,
        "_log_snapshot",
        lambda: {
            "last_line": "No available RTL SDR devices found",
            "error_message": "The headless P25 runtime could not find an available RTL-SDR tuner. FMP24 saw 2 RTL devices. RTL devices #1, #2 were already in use.",
            "error_health": "no_tuner",
            "error_detail": "FMP24 saw 2 RTL devices. RTL devices #1, #2 were already in use.",
            "event_log_path": None,
            "tuner_log": {
                "device_count": 2,
                "busy_device_numbers": [1, 2],
            },
        },
    )
    monkeypatch.setattr(runtime, "_p25data_snapshot", lambda: {"path": None, "record_count": 0, "last_line": None})
    monkeypatch.setattr(runtime, "_activity_snapshot", lambda: {})
    monkeypatch.setattr(runtime, "_control_activity_detected", lambda: False)
    monkeypatch.setattr(
        "backend.headless_p25_runtime.probe_rtl_sdr_device",
        lambda force=False: {"available": False, "message": "RTL-SDR access denied."},
    )

    snapshot = runtime.status()

    assert snapshot["health"] == "driver_conflict"
    assert snapshot["error_detail"] == "FMP24 saw 2 RTL devices. RTL devices #1, #2 were already in use."
    assert "Fix-RtlP25Conflict.ps1" in snapshot["message"]


def test_runtime_ensure_profile_uses_selected_bundle_and_refreshes_stale_files(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path / "profile"
    runtime.log_root = runtime.profile_root / "logs"
    runtime.profile_root.mkdir(parents=True, exist_ok=True)

    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    (bundle_root / "FMP24.exe").write_bytes(b"bundle-fmp24")
    (bundle_root / "DSDPlus.exe").write_bytes(b"bundle-dsd")
    (bundle_root / "rtlsdr.dll").write_bytes(b"bundle-rtlsdr")
    (bundle_root / "libusb-1.0.dll").write_bytes(b"bundle-libusb")
    (bundle_root / "FMP24.cfg").write_text("bundle cfg\n", encoding="utf-8")

    (runtime.profile_root / "FMP24.exe").write_bytes(b"stale-fmp24")
    (runtime.profile_root / "rtlsdr.dll").write_bytes(b"stale-rtlsdr")
    (runtime.profile_root / "FMP24.cfg").write_text("stale cfg\n", encoding="utf-8")

    runtime.tool_root = tmp_path / "missing-bundle"

    runtime._ensure_profile({
        "fmp24": bundle_root / "FMP24.exe",
        "dsdplus": bundle_root / "DSDPlus.exe",
    })

    assert runtime.tool_root == bundle_root
    assert (runtime.profile_root / "FMP24.exe").read_bytes() == b"bundle-fmp24"
    assert (runtime.profile_root / "rtlsdr.dll").read_bytes() == b"bundle-rtlsdr"
    assert (runtime.profile_root / "libusb-1.0.dll").read_bytes() == b"bundle-libusb"
    assert (runtime.profile_root / "FMP24.cfg").read_text(encoding="utf-8") == "bundle cfg\n"


def test_runtime_clear_run_outputs_removes_fmp24_temp_files(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)

    temp_path = runtime.profile_root / "FMP24.tmp12345"
    temp_path.write_text("temp", encoding="utf-8")

    runtime._clear_run_outputs()

    assert not temp_path.exists()


def test_runtime_prefers_physical_speaker_audio_output_from_fmp_log(tmp_path, monkeypatch):
    monkeypatch.delenv("TRICORE_DSDPLUS_AUDIO_OUTPUT_DEVICE", raising=False)
    monkeypatch.delenv("TRICORE_DSDPLUS_AUDIO_OUTPUT_NAME", raising=False)
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)
    (runtime.log_root / "fmp24-control.log").write_text(
        "\n".join([
            "Audio output device #1 = 'ROKU TV (NVIDIA High Definition'",
            "Audio output device #2 = 'Speakers (M-Audio M-Track Solo '",
            "Audio output device #3 = 'Speakers (Steam Streaming Micro'",
            "Audio output device #5 = 'CABLE Input (VB-Audio Virtual C'",
        ]),
        encoding="utf-8",
    )

    runtime._refresh_audio_output_from_log()

    assert runtime._audio_output_device == 2
    assert runtime._audio_output_name == "Speakers (M-Audio M-Track Solo"


def test_runtime_locks_encrypted_known_talkgroups_when_holding_one(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)
    (tmp_path / "DSDPlus.groups").write_text(
        'P25,       BEE09.13E, 963,        50,  Normal,       7,  2026/05/20 17:41,  "APD David SW"\n',
        encoding="utf-8",
    )

    runtime.set_known_talkgroups([(963, "APD David SW"), (1147, "AFD LOCUTION")])
    runtime.set_monitored_talkgroups([(1147, "AFD LOCUTION")])

    groups_text = (tmp_path / "DSDPlus.groups").read_text(encoding="utf-8")
    assert 'P25,       BEE09.13E, 963' in groups_text
    assert 'P25,       BEE09.13E, 1147' in groups_text
    assert any("963" in line and "L/O" in line for line in groups_text.splitlines())
    assert any("1147" in line and "High" in line for line in groups_text.splitlines())


def test_runtime_locks_encrypted_talkgroups_during_open_scan(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)

    runtime.set_known_talkgroups([(963, "APD David SW"), (1147, "AFD LOCUTION")])
    runtime.set_locked_talkgroups([963])
    runtime.set_monitored_talkgroups([])

    groups_text = (tmp_path / "DSDPlus.groups").read_text(encoding="utf-8")
    assert any("963" in line and "L/O" in line for line in groups_text.splitlines())
    assert any("1147" in line and "Normal" in line for line in groups_text.splitlines())


def test_runtime_clear_run_outputs_preserves_p25data(tmp_path):
    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)

    p25data_path = tmp_path / "DSDPlus.P25data"
    p25data_text = "".join([
        "; DSD+ 2.547; P25 data\n",
        "\n",
        "  Network: BEE09.13E\n",
        "\n",
        "    Site: 1.7    NAC=137\n",
        "\n",
        "    Channel 0-61:     851.3875     CC\n",
    ])
    p25data_path.write_text(p25data_text, encoding="utf-8")

    runtime._clear_run_outputs()

    assert p25data_path.read_text(encoding="utf-8") == p25data_text


def test_runtime_start_pipeline_uses_p25_tuning_options(tmp_path, monkeypatch):
    monkeypatch.setenv("TRICORE_DSDPLUS_FREQUENCY_CORRECTION_PPM", "1.8")
    monkeypatch.setenv("TRICORE_DSDPLUS_RF_BANDWIDTH_KHZ", "12.5")

    runtime = HeadlessP25Runtime([851387500])
    runtime.profile_root = tmp_path
    runtime.log_root = tmp_path / "logs"
    runtime.log_root.mkdir(parents=True, exist_ok=True)
    runtime.set_rf_gain(18.0)

    launched_commands: dict[str, list[str]] = {}

    monkeypatch.setattr(runtime, "_ensure_profile", lambda tool_paths=None: None)
    monkeypatch.setattr(runtime, "_clear_run_outputs", lambda: None)
    monkeypatch.setattr(runtime, "_profile_runtime_tool", lambda source: Path(str(source)))
    monkeypatch.setattr(runtime, "_wait_for_fmp_link_server", lambda: None)
    monkeypatch.setattr(runtime, "_refresh_audio_output_from_log", lambda: None)
    monkeypatch.setattr(runtime, "_launch", lambda name, command: launched_commands.setdefault(name, list(command)))

    runtime._start_pipeline({"fmp24": Path("FMP24.exe"), "dsdplus": Path("DSDPlus.exe")})

    fmp24_command = launched_commands["fmp24-control"]
    assert "-P1.8" in fmp24_command
    assert "-b12.5" in fmp24_command
    assert "-g18" in fmp24_command


def test_managed_decoder_replays_locked_talkgroups_after_runtime_rebuild(monkeypatch):
    locked_calls: list[list[int]] = []

    def fake_set_locked(self, talkgroups):
        locked_calls.append([int(decimal) for decimal in talkgroups])

    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_known_talkgroups", lambda self, talkgroups: None)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.set_locked_talkgroups", fake_set_locked)
    monkeypatch.setattr("backend.decoders.p25_decoder.HeadlessP25Runtime.stop", lambda self: None)

    decoder = ManagedP25Decoder([851387500])
    decoder.set_locked_talkgroups([963])
    decoder._set_control_channels([851137500])

    assert locked_calls[-1] == [963]


def test_frequency_manager_known_talkgroups_include_encrypted_for_lockout():
    known = dict(scanner_core.frequency_manager.known_trunked_talkgroup_targets())
    monitorable = dict(scanner_core.frequency_manager.monitorable_trunked_talkgroup_targets())

    assert known[963] == "APD David SW"
    assert 963 not in monitorable
    assert monitorable[1147] == "AFD LOCUTION"
    assert 963 in scanner_core.frequency_manager.encrypted_trunked_talkgroup_decimals()


def test_runtime_start_falls_back_to_sdrtrunk_on_driver_conflict(monkeypatch):
    runtime = HeadlessP25Runtime([851387500])
    fake_process = type("FakeProcess", (), {"pid": 1234, "poll": lambda self: None})()
    sdrtrunk_status = {
        "installed": True,
        "engine": "sdrtrunk",
        "running": True,
        "health": "ready",
        "message": "Bundled SDRTrunk decoder is running with the workspace playlist.",
        "pid": 4321,
        "profile_root": "C:/Users/example/SDRTrunk",
        "playlist_path": "C:/Users/example/SDRTrunk/playlist/default.xml",
        "tuner_available": True,
        "tuner_probe": {"available": True, "message": "RTL-SDR tuner detected."},
        "log_path": "C:/Users/example/SDRTrunk/logs/sdrtrunk_app.log",
        "log_message": "starting main application gui",
        "log_raw": "starting main application gui",
    }

    monkeypatch.setattr(runtime, "_tool_paths", lambda: {"fmp24": Path("C:/fmp24.exe"), "dsdplus": Path("C:/DSDPlus.exe")})
    monkeypatch.setattr(runtime, "_stop_profile_orphans", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_start_pipeline",
        lambda tool_paths: (runtime._processes.update({"fmp24-control": fake_process, "dsdplus-1r": fake_process}), setattr(runtime, "_started_at", 1.0)),
    )
    monkeypatch.setattr(runtime, "_refresh_processes", lambda: None)
    monkeypatch.setattr(runtime, "_maybe_failover", lambda tool_paths: False)
    monkeypatch.setattr(
        runtime,
        "_log_snapshot",
        lambda: {
            "last_line": "Error - remove/reinsert dongle with serial string '00000001'",
            "error_message": "FMP24 opened the RTL-SDR but the receiver reported a hardware error.",
            "error_health": "no_tuner",
            "error_detail": "FMP24 saw 2 RTL devices. RTL device #1 was already in use.",
            "event_log_path": None,
            "tuner_log": {
                "device_count": 2,
                "busy_device_numbers": [1],
                "selected_device_number": 2,
                "selected_serial": "00000001",
                "failing_serial": "00000001",
            },
        },
    )
    monkeypatch.setattr(runtime, "_p25data_snapshot", lambda: {"path": None, "record_count": 0, "last_line": None})
    monkeypatch.setattr(runtime, "_activity_snapshot", lambda: {})
    monkeypatch.setattr(runtime, "_control_activity_detected", lambda: False)
    monkeypatch.setattr(
        runtime,
        "_stop_processes",
        lambda reset_hunt: (runtime._processes.clear(), setattr(runtime, "_started_at", None)),
    )
    monkeypatch.setattr(
        "backend.headless_p25_runtime.probe_rtl_sdr_device",
        lambda force=False: {"available": True, "message": "RTL-SDR tuner detected."},
    )
    monkeypatch.setattr(runtime._sdrtrunk_runtime, "start", lambda force_probe=False: dict(sdrtrunk_status))
    monkeypatch.setattr(runtime._sdrtrunk_runtime, "status", lambda force_probe=False: dict(sdrtrunk_status))

    snapshot = runtime.start()

    assert snapshot["engine"] == "sdrtrunk"
    assert snapshot["health"] == "ready"
    assert snapshot["processes"] == {"sdrtrunk": 4321}
    assert snapshot["playlist_path"] == "C:/Users/example/SDRTrunk/playlist/default.xml"
    assert runtime._fallback_engine == "sdrtrunk"


def test_sdrtrunk_runtime_prefers_current_undated_log(tmp_path):
    runtime = SdrTrunkRuntime()
    runtime.profile_root = tmp_path
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)

    dated_log = log_dir / "20260518_sdrtrunk_app.log"
    current_log = log_dir / "sdrtrunk_app.log"
    dated_log.write_text("old\n", encoding="utf-8")
    current_log.write_text("current\n", encoding="utf-8")

    assert runtime._latest_log_path() == current_log

def test_runtime_start_relaunches_selected_sdrtrunk_fallback_when_stopped(monkeypatch):
    runtime = HeadlessP25Runtime([851387500])
    runtime._fallback_engine = "sdrtrunk"
    state = {"running": False}

    stopped_status = {
        "installed": True,
        "engine": "sdrtrunk",
        "running": False,
        "health": "stopped",
        "message": "RTL-SDR tuner detected. Bundled SDRTrunk decoder is ready to launch.",
        "pid": None,
        "profile_root": "C:/Users/example/SDRTrunk",
        "playlist_path": "C:/Users/example/SDRTrunk/playlist/default.xml",
        "tuner_available": True,
        "tuner_probe": {"available": True, "message": "RTL-SDR tuner detected."},
        "log_path": "C:/Users/example/SDRTrunk/logs/sdrtrunk_app.log",
        "log_message": "No SDRTrunk log file found yet.",
        "log_raw": None,
    }
    ready_status = {
        **stopped_status,
        "running": True,
        "health": "ready",
        "message": "Bundled SDRTrunk decoder is running with the workspace playlist.",
        "pid": 4321,
        "log_message": "starting main application gui",
        "log_raw": "starting main application gui",
    }

    monkeypatch.setattr(runtime, "_stop_processes", lambda reset_hunt: None)
    monkeypatch.setattr(
        runtime._sdrtrunk_runtime,
        "status",
        lambda force_probe=False: dict(ready_status if state["running"] else stopped_status),
    )

    def fake_start(force_probe=False):
        state["running"] = True
        return dict(ready_status)

    monkeypatch.setattr(runtime._sdrtrunk_runtime, "start", fake_start)

    snapshot = runtime.start()

    assert snapshot["engine"] == "sdrtrunk"
    assert snapshot["health"] == "ready"
    assert snapshot["processes"] == {"sdrtrunk": 4321}
    assert state["running"] is True


def test_transcriber_start_reports_sdrtrunk_fallback_for_p25(monkeypatch):
    decoder = scanner_core.decoders["p25_placeholder"]
    scanner_core.current_channel = Channel(
        id="tcso-david-p25",
        name="TCSO DAVID",
        frequency_hz=851387500,
        modulation="p25_placeholder",
        system="GATRRS",
        p25_control_channels_hz=[851387500, 851137500, 851287500, 851312500],
        p25_talkgroup_decimal=2406,
    )

    monkeypatch.setattr(decoder, "audio_wav_path", lambda: None)
    monkeypatch.setattr(
        decoder,
        "status",
        lambda: DecoderStatus(
            id="p25-managed",
            label="Managed P25 Runtime",
            modulation="p25_placeholder",
            ready=True,
            active=True,
            message="Bundled SDRTrunk decoder is running with the workspace playlist.",
            sync_state="control_lock",
            selected_talkgroup_decimal=2406,
            runtime={"engine": "sdrtrunk", "health": "ready"},
        ),
    )
    monkeypatch.setattr(
        transcriber_routes.transcriber,
        "status",
        lambda: {"running": False, "error": None, "transcript_count": 0, "current_channel": None},
    )
    monkeypatch.setattr(transcriber_routes.transcriber, "get_transcripts", lambda: [])

    response = client.post("/api/transcriber/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "SDRTrunk fallback" in payload["error"]


def test_manual_tune_away_from_p25_stops_managed_decoder(monkeypatch):
    stop_calls: list[tuple[int, ...]] = []

    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.start",
        lambda self, force_probe=False: {
            "installed": True,
            "running": True,
            "health": "ready",
            "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        },
    )
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.status",
        lambda self, force_probe=False: {
            "installed": True,
            "running": True,
            "health": "ready",
            "message": "Headless DSDPlus control and voice pipeline running on 851.387500 MHz.",
        },
    )
    monkeypatch.setattr(
        "backend.decoders.p25_decoder.HeadlessP25Runtime.stop",
        lambda self: stop_calls.append(tuple(self.control_channels_hz)),
    )

    first = client.post(
        "/api/scanner/manual-tune",
        json={"frequency_mhz": 851.3875, "modulation": "p25", "name": "GATRRS Control"},
    )

    assert first.status_code == 200
    stop_calls.clear()

    second = client.post(
        "/api/scanner/manual-tune",
        json={"frequency_mhz": 162.55, "modulation": "nfm", "name": "NOAA Weather 7"},
    )

    assert second.status_code == 200
    assert stop_calls == [(851387500,)]


def test_p25_status_falls_back_to_managed_decoder_when_scanner_not_on_p25(monkeypatch):
    managed_decoder = scanner_core.decoders["p25_placeholder"]
    fallback_decoder = DecoderStatus(
        id="p25-managed",
        label="Managed P25 Runtime",
        modulation="p25_placeholder",
        ready=False,
        active=False,
        message=(
            "FMP24 opened the RTL-SDR but the receiver reported a hardware error. "
            "Run Fix-RtlP25Conflict.ps1 as Administrator, then retry P25."
        ),
        sync_state="driver_conflict",
        selected_talkgroup_decimal=2406,
        runtime={"health": "driver_conflict"},
    )

    scanner_status = type(
        "ScannerStatusStub",
        (),
        {
            "current_channel": None,
            "active_channel": None,
            "decoder": None,
            "state": "stopped",
            "message": "Scanner stopped.",
            "current_frequency_hz": None,
        },
    )()

    monkeypatch.setattr(scanner_core, "status", lambda advance=False: scanner_status)
    monkeypatch.setattr(managed_decoder, "status", lambda: fallback_decoder)

    response = client.get("/api/p25/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "stopped"
    assert payload["message"] == fallback_decoder.message
    assert payload["selected_talkgroup"]["decimal"] == 2406
    assert payload["tracking_label"] == "TCSO DAVID"
    assert payload["decoder"]["runtime"]["health"] == "driver_conflict"
