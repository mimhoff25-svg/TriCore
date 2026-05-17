"""P25 decoder + trunking metadata service for TriCore.

Owns talkgroup data (previously TrunkingManager) and the SDRTrunk
subprocess lifecycle (previously split across decoder_config.py).
"""

from __future__ import annotations

import json
import math
import re
import csv
from io import StringIO
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from models import Talkgroup, TrunkedSystem
from sdr_runtime import SdrRuntime


_launcher_cache: list[Path] | None = None
_EVENT_FRESH_SECONDS = 180.0


def _find_sdrtrunk_launchers(project_root: Path) -> list[Path]:
    global _launcher_cache
    if _launcher_cache is not None:
        return _launcher_cache

    scanner_root = project_root.parents[1]
    runtime_launcher = SdrRuntime(project_root).find_sdrtrunk_launcher()
    candidates: list[Path] = []
    direct_candidates = [
        runtime_launcher,
        project_root
        / "tools"
        / "sdr-trunk-windows-x86_64-v0.6.1"
        / "sdr-trunk-windows-x86_64-v0.6.1"
        / "bin"
        / "sdr-trunk.bat",
        scanner_root / "SDRTrunk" / "sdr-trunk.bat",
        scanner_root / "SDRTrunk" / "bin" / "sdr-trunk.bat",
    ]
    candidates.extend(p for p in direct_candidates if p and p.exists())
    if candidates:
        _launcher_cache = list(dict.fromkeys(candidates))
        return _launcher_cache

    roots = [
        project_root / "tools",
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path.home() / "SDRTrunk",
        Path("C:/sdrtrunk"),
        Path("C:/SDRTrunk"),
    ]
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("sdr-trunk*.bat", "sdrtrunk*.bat", "sdr-trunk.exe", "sdrtrunk.exe"):
            candidates.extend(root.rglob(pattern))

    _launcher_cache = list(dict.fromkeys(candidates))
    return _launcher_cache


class _VoiceScanner:
    """Energy-scans GATRRS voice frequencies to detect P25 voice traffic.

    Each frequency gets four IQ power readings over a 50 ms window.
    Coefficient of variation (CV) across those readings separates P25 bursts
    (high CV) from thermal noise (near-zero CV), using the same classifier that
    test_listen.py proved works against the Austin-TX site.
    """

    _READINGS = 4
    _SETTLE_S = 0.04
    _READ_GAP_S = 0.01
    _SIGNAL_DB = -35.0
    _P25_CV = 0.08
    _TTL_S = 20.0

    def __init__(self, voice_hz: list[int], gain_db: float | None = None) -> None:
        self.voice_hz = voice_hz
        self.gain_db = gain_db
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._seen: dict[int, dict] = {}
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._sweeps = 0
        self._last_sweep_ms = 0.0
        self.error: str | None = None

    def start(self, timeout: float = 3.0) -> None:
        self._stop.clear()
        self._ready.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=timeout)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        with self._lock:
            self._seen.clear()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def active_channels(self) -> list[dict]:
        cutoff = time.monotonic() - self._TTL_S
        with self._lock:
            stale = [f for f, v in self._seen.items() if v["_mono"] < cutoff]
            for f in stale:
                del self._seen[f]
            return [{k: v for k, v in e.items() if k != "_mono"} for e in self._seen.values()]

    def sweep_stats(self) -> dict:
        return {
            "sweeps": self._sweeps,
            "last_sweep_ms": round(self._last_sweep_ms),
            "channels": len(self.voice_hz),
        }

    def _run(self) -> None:
        try:
            from sdr_device import RtlSdrDevice, SdrSettings
        except ImportError:
            self.error = "pyrtlsdr not installed"
            self._ready.set()
            return

        device = RtlSdrDevice(SdrSettings(gain_db=self.gain_db, sample_count=8192))
        try:
            device.open()
        except Exception as exc:
            self.error = str(exc)
            self._ready.set()
            return

        try:
            self._ready.set()
            while not self._stop.is_set():
                t0 = time.monotonic()
                for freq_hz in self.voice_hz:
                    if self._stop.is_set():
                        break
                    device.tune(freq_hz)
                    time.sleep(self._SETTLE_S)

                    powers: list[float] = []
                    for _ in range(self._READINGS):
                        if self._stop.is_set():
                            break
                        try:
                            powers.append(device.read_power())
                        except Exception:
                            pass
                        time.sleep(self._READ_GAP_S)

                    if len(powers) < 2:
                        continue

                    mean_db = sum(powers) / len(powers)
                    linear = [10.0 ** (p / 20.0) for p in powers]
                    lm = sum(linear) / len(linear)
                    lv = sum((x - lm) ** 2 for x in linear) / len(linear)
                    cv = math.sqrt(lv) / (lm + 1e-12)
                    is_p25 = mean_db >= self._SIGNAL_DB and cv >= self._P25_CV

                    now = time.monotonic()
                    with self._lock:
                        if is_p25:
                            self._seen[freq_hz] = {
                                "frequency_hz": freq_hz,
                                "frequency_mhz": round(freq_hz / 1_000_000, 5),
                                "signal_db": round(mean_db, 1),
                                "cv": round(cv, 3),
                                "detected_at_utc": datetime.now(timezone.utc).isoformat(),
                                "_mono": now,
                            }
                        elif freq_hz in self._seen and now - self._seen[freq_hz]["_mono"] > self._TTL_S:
                            del self._seen[freq_hz]

                self._sweeps += 1
                self._last_sweep_ms = (time.monotonic() - t0) * 1000
        finally:
            device.close()


class P25DecoderService:
    """Trunking metadata + SDRTrunk decoder lifecycle in one place."""

    def __init__(self, config_dir: Path, project_root: Path) -> None:
        self.config_dir = config_dir.resolve()
        self.project_root = project_root.resolve()
        self.runtime = SdrRuntime(self.project_root)
        self.runtime.ensure()
        self.scanner_root = self.project_root.parents[1]
        runtime_root = Path.home() / "SDRTrunk"
        moved_root = self.scanner_root / "SDRTrunk"
        self.sdrtrunk_root = runtime_root if runtime_root.exists() else moved_root
        self.seed_playlist_path = moved_root / "playlist" / "default.xml"
        self.playlist_path = self.sdrtrunk_root / "playlist" / "default.xml"
        self.log_dir = self.sdrtrunk_root / "logs"
        self.event_dir = self.sdrtrunk_root / "event_logs"
        self.recording_dir = self.sdrtrunk_root / "recordings"
        self.jmbe_dir = self.sdrtrunk_root / "jmbe"
        self.systems: list[TrunkedSystem] = self._load_systems()
        self.selected_talkgroup: Talkgroup | None = None
        self.selected_at_utc: str | None = None
        self.message = "P25 decoder is idle"
        self._process: subprocess.Popen | None = None
        self._launched_at: float | None = None  # monotonic time of last SDRTrunk launch
        self._last_event: dict | None = None
        self._voice_scanner: _VoiceScanner | None = None
        self._last_start_error: str | None = None

    # ── Talkgroup data ──────────────────────────────────────────────────────

    def _load_systems(self) -> list[TrunkedSystem]:
        if not self.config_dir.exists():
            return []
        systems = []
        for path in sorted(self.config_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            systems.append(TrunkedSystem(**data))
        return systems

    def list_systems(self) -> list[TrunkedSystem]:
        return self.systems

    def list_talkgroups(self, include_encrypted: bool = False) -> list[dict]:
        rows: list[dict] = []
        for system in self.systems:
            for tg in system.talkgroups:
                if tg.encrypted and not include_encrypted:
                    continue
                rows.append({
                    **tg.model_dump(),
                    "system_id": system.id,
                    "system_name": system.short_name,
                    "system_type": system.system_type,
                    "trunked": True,
                })
        return rows

    def find_talkgroup(self, decimal: int) -> Talkgroup | None:
        for system in self.systems:
            for tg in system.talkgroups:
                if tg.decimal == decimal:
                    return tg
        return None

    # ── Decoder lifecycle ───────────────────────────────────────────────────

    def start(self) -> dict:
        self._stop_rtl_fm_processes()
        self._last_event = None
        sync_result = self.sync_sdrtrunk_playlist()
        self._ensure_jmbe_library()
        launchers = _find_sdrtrunk_launchers(self.project_root)

        if launchers:
            # External decoder mode: run SDRTrunk as TriCore's managed backend.
            existing_processes = self._sdrtrunk_processes()
            if existing_processes and sync_result.get("updated"):
                self._stop_sdrtrunk_processes(existing_processes)
                time.sleep(1.0)
                existing_processes = self._sdrtrunk_processes()
            if existing_processes:
                self._process = None
                self._launched_at = None
                self._last_start_error = None
                self._hide_sdrtrunk_windows()
                self.message = "SDR backend is already running behind TriCore"
                return self.status()
            if self._process and self._process.poll() is None:
                self._last_start_error = None
                self._hide_sdrtrunk_windows()
                self.message = "SDR backend is already running behind TriCore"
                return self.status()
            launcher = launchers[0]
            try:
                self._process = subprocess.Popen(
                    ["cmd.exe", "/c", str(launcher)],
                    cwd=str(launcher.parent),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                self._process = None
                self._launched_at = None
                self._last_start_error = str(exc)
                self.message = f"SDRTrunk launch failed: {exc}"
                return self.status()
            self._launched_at = time.monotonic()
            if self._wait_for_sdrtrunk_start(timeout=8.0):
                self._last_start_error = None
                self._hide_sdrtrunk_windows()
                threading.Thread(target=self._hide_sdrtrunk_windows_delayed, daemon=True).start()
                self.message = "SDR backend started behind TriCore. Audio plays when the selected talkgroup is active."
            else:
                exit_code = self._process.poll() if self._process else None
                self._last_start_error = (
                    f"launcher exited with code {exit_code}"
                    if exit_code is not None
                    else "no SDRTrunk process appeared"
                )
                self._launched_at = None
                self.message = f"SDRTrunk launch did not stay running: {self._last_start_error}"
        else:
            # Native mode: energy-scan GATRRS voice channels with the RTL-SDR dongle
            voice_hz = [
                hz
                for system in self.systems
                for site in system.sites
                for hz in site.voice_channels_hz
            ]
            if not voice_hz:
                self.message = "No GATRRS voice channels configured"
                return self.status()
            self.stop_native_scan()
            self._voice_scanner = _VoiceScanner(voice_hz, gain_db=None)
            self._voice_scanner.start()
            if self._voice_scanner.error:
                self.message = f"GATRRS voice scan error: {self._voice_scanner.error}"
            elif not self._voice_scanner.running:
                self.message = "GATRRS voice scan did not start"
            else:
                self.message = (
                    f"Scanning {len(voice_hz)} GATRRS voice channels for P25 activity"
                )

        return self.status()

    def stop(self) -> dict:
        self._stop_tracked_process()
        external_stopped = self._stop_sdrtrunk_processes()
        self._process = None
        self._launched_at = None
        self._last_start_error = None
        self._last_event = None
        self.stop_native_scan()
        self.message = "SDR backend stopped" if external_stopped else "SDR backend was already stopped"
        return self.status()

    def stop_native_scan(self) -> None:
        """Stop the native RTL-SDR voice scanner without touching SDRTrunk."""
        if self._voice_scanner:
            self._voice_scanner.stop()
            self._voice_scanner = None

    def scan_all(self) -> dict:
        self.selected_talkgroup = None
        self.selected_at_utc = None
        self.message = "GATRRS scan mode. TriCore will show the next active clear talkgroup."
        return self.start()

    def select_talkgroup(self, decimal: int) -> dict:
        tg = self.find_talkgroup(decimal)
        if tg is None:
            self.message = f"Talkgroup {decimal} not found"
            return self.status()

        self.selected_talkgroup = tg
        self.selected_at_utc = datetime.now(timezone.utc).isoformat()

        if tg.encrypted:
            self.message = f"{tg.alpha_tag} is encrypted — cannot be monitored."
            return self.status()

        self.message = (
            f"Front panel selected {tg.alpha_tag}. TriCore is starting the hidden SDR backend; "
            "audio plays when that talkgroup is active."
        )
        return self.start()

    def status(self) -> dict:
        system = self.systems[0] if self.systems else None
        launchers = _find_sdrtrunk_launchers(self.project_root)
        vs = self._voice_scanner
        proc_alive = bool(self._process and self._process.poll() is None)
        external_processes = self._sdrtrunk_processes()
        recently_launched = (
            self._launched_at is not None
            and time.monotonic() - self._launched_at < 120
            and proc_alive
        )
        sdrtrunk_running = proc_alive or bool(external_processes)

        latest_event = self._read_latest_decoder_event()
        if sdrtrunk_running and self._event_is_fresh(latest_event):
            self._last_event = latest_event
        elif not sdrtrunk_running or not self._event_is_fresh(self._last_event):
            self._last_event = None

        active = self._event_for_selected(self._last_event) if sdrtrunk_running else None
        state = "STARTING" if recently_launched and not external_processes else self._state(active)
        if self._last_start_error and not sdrtrunk_running:
            state = "ERROR"
        return {
            "enabled": bool(system),
            "decoder": "sdrtrunk" if launchers else "native",
            "running": sdrtrunk_running,
            "state": state,
            "message": self.message,
            "selected_talkgroup": self.selected_talkgroup.model_dump() if self.selected_talkgroup else None,
            "selected_at_utc": self.selected_at_utc,
            "active_call": active,
            "last_event": self._last_event if sdrtrunk_running else None,
            "control_channels_hz": self._control_channels(system),
            "preferred_control_channel_hz": self._preferred_control_channel(system),
            "playlist_path": str(self.playlist_path),
            "log_path": str(self._latest_file(self.log_dir, "*.log")) if self._latest_file(self.log_dir, "*.log") else None,
            "event_log_dir": str(self.event_dir),
            "recording_dir": str(self.recording_dir),
            "jmbe_path": str(self._jmbe_library_path()) if self._jmbe_library_path() else None,
            "external_decoder": {
                "installed": bool(launchers),
                "launchers": [str(p) for p in launchers],
                "message": "SDRTrunk launcher found." if launchers else "SDRTrunk not found.",
                "processes": external_processes,
                "last_start_error": self._last_start_error,
            },
            # Native GATRRS voice scanner fields
            "voice_scan_active": bool(vs and vs.running),
            "voice_scan_error": vs.error if vs else None,
            "active_voice_channels": vs.active_channels() if vs else [],
            "voice_sweep_stats": vs.sweep_stats() if vs else None,
        }

    # ── SDRTrunk playlist sync ──────────────────────────────────────────────

    def sync_sdrtrunk_playlist(self) -> dict:
        self._ensure_jmbe_library()
        if not self.playlist_path.exists():
            self.playlist_path.parent.mkdir(parents=True, exist_ok=True)
            self.playlist_path.write_text('<playlist version="4" />', encoding="utf-8")

        tree = ET.parse(self.playlist_path)
        root = tree.getroot()
        system = self.systems[0] if self.systems else None
        preferred_cc = self._preferred_control_channel(system)

        updated = False
        updated = self._sync_seed_playlist_channels(root) or updated
        gatrrs_channels = [
            channel
            for channel in root.findall("channel")
            if "GATRRS" in (channel.get("system") or "")
        ]
        if not gatrrs_channels:
            root.insert(0, self._build_gatrrs_channel(preferred_cc))
            updated = True
            gatrrs_channels = [
                channel
                for channel in root.findall("channel")
                if "GATRRS" in (channel.get("system") or "")
            ]
        if len(gatrrs_channels) > 1:
            keep = gatrrs_channels[0]
            for channel in gatrrs_channels[1:]:
                root.remove(channel)
                updated = True
            gatrrs_channels = [keep]

        for channel in root.findall("channel"):
            if "GATRRS" in (channel.get("system") or ""):
                channel.set("enabled", "true")
                updated = self._ensure_gatrrs_decode_configuration(channel) or updated
                updated = self._ensure_gatrrs_event_logging(channel) or updated
                updated = self._ensure_gatrrs_multi_frequency_source(channel, system) or updated

        existing_aliases = {}
        for alias in root.findall("alias"):
            for ident in alias.findall("id"):
                if ident.get("type") == "talkgroup" and ident.get("protocol") == "APCO25":
                    existing_aliases[ident.get("value")] = alias

        for tg in self.list_talkgroups(include_encrypted=True):
            value = str(tg["decimal"])
            group = tg.get("tag") or tg.get("service_type") or "GATRRS"
            name = tg["alpha_tag"]
            if value in existing_aliases:
                alias = existing_aliases[value]
                if alias.get("group") != group:
                    alias.set("group", group)
                    updated = True
                if alias.get("list") != "Austin":
                    alias.set("list", "Austin")
                    updated = True
                if alias.get("name") != name:
                    alias.set("name", name)
                    updated = True
                continue
            alias = ET.SubElement(root, "alias", {
                "group": group,
                "color": "0",
                "list": "Austin",
                "name": name,
            })
            ET.SubElement(alias, "id", {
                "type": "talkgroup",
                "protocol": "APCO25",
                "value": value,
            })
            updated = True

        if updated:
            self._indent_xml(root)
            tree.write(self.playlist_path, encoding="unicode", xml_declaration=False)
        return {
            "updated": updated,
            "playlist_path": str(self.playlist_path),
            "seed_playlist_path": str(self.seed_playlist_path),
        }

    # ── Internal helpers ────────────────────────────────────────────────────

    def _state(self, active: dict | None) -> str:
        if self.selected_talkgroup and self.selected_talkgroup.encrypted:
            return "LOCKED"
        if active:
            return "RECEIVING_CALL"
        if self.selected_talkgroup:
            return "WAITING_FOR_TALKGROUP"
        return "READY"

    def _control_channels(self, system: TrunkedSystem | None) -> list[int]:
        if not system:
            return []
        channels: list[int] = []
        for site in system.sites:
            channels.extend(site.control_channels_hz)
        return channels

    def _preferred_control_channel(self, system: TrunkedSystem | None) -> int | None:
        channels = self._control_channels(system)
        # Local RF captures showed this GATRRS control channel carrying live data.
        if 851_387_500 in channels:
            return 851_387_500
        return channels[0] if channels else None

    def _latest_file(self, directory: Path, pattern: str) -> Path | None:
        if not directory.exists():
            return None
        files = [p for p in directory.glob(pattern) if p.is_file()]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def _read_latest_decoder_event(self) -> dict | None:
        for path in filter(None, [
            self._latest_file(self.event_dir, "*call_events.log"),
            self._latest_file(self.event_dir, "*decoded_messages.log"),
            self._latest_file(self.event_dir, "*.csv"),
            self._latest_file(self.log_dir, "*.log"),
        ]):
            event = self._parse_file_tail(path)
            if event:
                return event
        return None

    def _event_is_fresh(self, event: dict | None) -> bool:
        if not event:
            return False
        source_file = event.get("source_file")
        if not source_file:
            return False
        try:
            return time.time() - Path(source_file).stat().st_mtime <= _EVENT_FRESH_SECONDS
        except OSError:
            return False

    def _parse_file_tail(self, path: Path) -> dict | None:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[-80_000:]
        except OSError:
            return None
        for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
            event = self._parse_event_line(line, path)
            if event:
                return event
        return None

    def _parse_event_line(self, line: str, path: Path) -> dict | None:
        csv_event = self._parse_call_event_csv(line, path)
        if csv_event:
            return csv_event

        lower = line.lower()
        if not any(token in lower for token in ("talkgroup", "tg", " to:", " from:", "radio")):
            return None

        tg_decimal = self._first_int(r"(?:talkgroup|tgid|tg|to|group address|group a|group b)\D{0,18}(\d{2,8})", line)
        source_radio = self._first_int(r"(?:from|source|radio|src)\D{0,12}(\d{2,9})", line)
        target_radio = self._first_int(r"(?:target|to)\D{0,12}(\d{2,9})", line)
        freq = self._first_float(r"(?<!\d)((?:1\d{2}|7\d{2}|8\d{2})\.\d{3,6})(?!\d)", line)

        talkgroup = self.find_talkgroup(tg_decimal) if tg_decimal is not None else None
        if tg_decimal is None and source_radio is None and target_radio is None:
            return None

        return {
            "talkgroup_decimal": tg_decimal,
            "talkgroup": talkgroup.model_dump() if talkgroup else None,
            "source_radio_id": source_radio,
            "target_radio_id": target_radio,
            "voice_frequency_hz": int(freq * 1_000_000) if freq else None,
            "raw": line,
            "source_file": str(path),
            "time_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _parse_call_event_csv(self, line: str, path: Path) -> dict | None:
        if not line.startswith('"') or "," not in line:
            return None
        try:
            row = next(csv.reader(StringIO(line)))
        except (csv.Error, StopIteration):
            return None
        if len(row) < 9 or row[2] != "APCO-25":
            return None

        event_type = row[3]
        source = row[4].strip()
        target = row[5].strip()
        frequency = row[7].strip()
        details = row[9].strip() if len(row) > 9 else ""

        tg_decimal = self._first_int(r"\((\d{2,8})\)", target)
        if tg_decimal is None:
            tg_decimal = self._first_int(r"(?:GROUP|TO)\D{0,18}(\d{2,8})", details)

        source_radio = int(source) if source.isdigit() else None
        target_radio = None
        bare_target = target.strip(" ()")
        if bare_target.isdigit() and tg_decimal is None:
            target_radio = int(bare_target)

        freq_hz = None
        try:
            if frequency:
                parsed_frequency = float(frequency)
                if parsed_frequency > 0:
                    freq_hz = int(parsed_frequency * 1_000_000)
        except ValueError:
            freq_hz = None

        talkgroup = self.find_talkgroup(tg_decimal) if tg_decimal is not None else None
        if tg_decimal is None and source_radio is None and target_radio is None and not freq_hz:
            return None

        return {
            "talkgroup_decimal": tg_decimal,
            "talkgroup": talkgroup.model_dump() if talkgroup else None,
            "source_radio_id": source_radio,
            "target_radio_id": target_radio,
            "voice_frequency_hz": freq_hz,
            "event_type": event_type,
            "details": details,
            "raw": line,
            "source_file": str(path),
            "time_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _event_for_selected(self, event: dict | None) -> dict | None:
        if not event:
            return None
        if not self.selected_talkgroup:
            return event
        if event.get("talkgroup_decimal") == self.selected_talkgroup.decimal:
            return event
        return None

    def _first_int(self, pattern: str, text: str) -> int | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _first_float(self, pattern: str, text: str) -> float | None:
        match = re.search(pattern, text)
        return float(match.group(1)) if match else None

    def _wait_for_sdrtrunk_start(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process and self._process.poll() is None:
                return True
            if self._sdrtrunk_processes():
                return True
            time.sleep(0.25)
        return bool(self._sdrtrunk_processes())

    def _hide_sdrtrunk_windows_delayed(self) -> None:
        for delay in (2.0, 5.0, 10.0):
            time.sleep(delay)
            self._hide_sdrtrunk_windows()

    def _hide_sdrtrunk_windows(self) -> None:
        script = r"""
Add-Type -Name NativeWindow -Namespace TriCore -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool ShowWindowAsync(System.IntPtr hWnd, int nCmdShow);
'@
$targets = Get-Process java,javaw,cmd -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowHandle -ne 0 -and (
        $_.MainWindowTitle -match 'sdrtrunk|sdr-trunk|SDRTrunk' -or
        $_.Path -match 'sdr-trunk|sdrtrunk'
    )
}
foreach ($proc in $targets) {
    [TriCore.NativeWindow]::ShowWindowAsync($proc.MainWindowHandle, 0) | Out-Null
}
"""
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=6,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _stop_tracked_process(self) -> bool:
        if not (self._process and self._process.poll() is None):
            return False
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
        return True

    def _stop_sdrtrunk_processes(self, processes: list[dict] | None = None) -> bool:
        processes = processes if processes is not None else self._sdrtrunk_processes()
        stopped = False
        for proc in processes:
            pid = proc.get("pid")
            if not isinstance(pid, int):
                continue
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=10,
                )
                stopped = True
            except (OSError, subprocess.TimeoutExpired):
                pass
        return stopped

    def _stop_rtl_fm_processes(self) -> bool:
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'rtl_fm.exe' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False

        stopped = False
        for raw_pid in completed.stdout.split():
            try:
                pid = int(raw_pid)
            except ValueError:
                continue
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=10,
                )
                stopped = True
            except (OSError, subprocess.TimeoutExpired):
                pass
        if stopped:
            time.sleep(1.0)
        return stopped

    def _sdrtrunk_processes(self) -> list[dict]:
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.CommandLine -match 'sdr-trunk\\.(bat|exe)' -or "
            "$_.CommandLine -match 'sdrtrunk\\.(bat|exe)' -or "
            "$_.CommandLine -match 'io\\.github\\.dsheirer\\.gui\\.SDRTrunk' "
            "} | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []

        raw = completed.stdout.strip()
        if not raw:
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        rows = data if isinstance(data, list) else [data]

        current_pid = None
        try:
            import os
            current_pid = os.getpid()
        except OSError:
            pass

        processes = []
        for row in rows:
            try:
                pid = int(row.get("ProcessId"))
            except (TypeError, ValueError):
                continue
            command = row.get("CommandLine") or ""
            name = row.get("Name") or ""
            if current_pid is not None and pid == current_pid:
                continue
            if "powershell.exe" in name.lower() and "Get-CimInstance Win32_Process" in command:
                continue
            processes.append({
                "pid": pid,
                "name": name,
                "command": command,
            })
        return processes

    def _jmbe_library_path(self) -> Path | None:
        for root in [self.jmbe_dir, self.runtime.jmbe_dir, self.scanner_root / "SDRTrunk" / "jmbe"]:
            if not root.exists():
                continue
            jars = sorted(root.glob("jmbe-*.jar"))
            if jars:
                return jars[-1]
        return None

    def _ensure_jmbe_library(self) -> None:
        source = self._jmbe_library_path()
        if not source:
            return
        self.jmbe_dir.mkdir(parents=True, exist_ok=True)
        target = self.jmbe_dir / source.name
        if target.resolve() == source.resolve():
            return
        try:
            target.write_bytes(source.read_bytes())
        except OSError:
            pass

    def _sync_seed_playlist_channels(self, root: ET.Element) -> bool:
        if not self.seed_playlist_path.exists():
            return False
        try:
            seed_root = ET.parse(self.seed_playlist_path).getroot()
        except ET.ParseError:
            return False

        existing = {
            (
                channel.get("system") or "",
                channel.get("site") or "",
                channel.get("name") or "",
            )
            for channel in root.findall("channel")
        }

        updated = False
        insert_at = 0
        for channel in seed_root.findall("channel"):
            key = (
                channel.get("system") or "",
                channel.get("site") or "",
                channel.get("name") or "",
            )
            if key in existing:
                continue
            root.insert(insert_at, ET.fromstring(ET.tostring(channel, encoding="unicode")))
            insert_at += 1
            existing.add(key)
            updated = True
        return updated

    def _build_gatrrs_channel(self, preferred_cc: int | None) -> ET.Element:
        frequency = str(preferred_cc or 851_387_500)
        channel = ET.Element("channel", {
            "system": "GATRRS",
            "site": "Austin/Travis County TX",
            "enabled": "true",
            "order": "0",
            "name": f"GATRRS Austin Travis CC {int(frequency) / 1_000_000:.4f} MHz",
        })
        ET.SubElement(channel, "alias_list_name").text = "Austin"
        ET.SubElement(channel, "decode_configuration", {
            "type": "decodeConfigP25Phase1",
            "modulation": "CQPSK",
            "traffic_channel_pool_size": "1",
            "ignore_data_calls": "false",
        })
        ET.SubElement(channel, "aux_decode_configuration")
        self._build_event_log_configuration(channel)
        ET.SubElement(channel, "record_configuration")
        ET.SubElement(channel, "source_configuration", {
            "type": "sourceConfigTuner",
            "frequency": frequency,
            "source_type": "TUNER",
        })
        return channel

    def _ensure_gatrrs_decode_configuration(self, channel: ET.Element) -> bool:
        decode = channel.find("decode_configuration")
        if decode is None:
            decode = ET.SubElement(channel, "decode_configuration")
            updated = True
        else:
            updated = False

        wanted = {
            "type": "decodeConfigP25Phase1",
            "modulation": "CQPSK",
            "traffic_channel_pool_size": "1",
            "ignore_data_calls": "false",
        }
        for key, value in wanted.items():
            if decode.get(key) != value:
                decode.set(key, value)
                updated = True
        return updated

    def _ensure_gatrrs_event_logging(self, channel: ET.Element) -> bool:
        event_config = channel.find("event_log_configuration")
        if event_config is None:
            self._build_event_log_configuration(channel)
            return True

        wanted = [
            "CALL_EVENT",
            "TRAFFIC_CALL_EVENT",
            "DECODED_MESSAGE",
            "TRAFFIC_DECODED_MESSAGE",
        ]
        existing = [logger.text for logger in event_config.findall("logger")]
        updated = False
        for logger_name in wanted:
            if logger_name in existing:
                continue
            logger = ET.SubElement(event_config, "logger")
            logger.text = logger_name
            updated = True
        return updated

    def _build_event_log_configuration(self, channel: ET.Element) -> ET.Element:
        event_config = ET.SubElement(channel, "event_log_configuration")
        for logger_name in [
            "CALL_EVENT",
            "TRAFFIC_CALL_EVENT",
            "DECODED_MESSAGE",
            "TRAFFIC_DECODED_MESSAGE",
        ]:
            logger = ET.SubElement(event_config, "logger")
            logger.text = logger_name
        return event_config

    def _ensure_gatrrs_multi_frequency_source(
        self,
        channel: ET.Element,
        system: TrunkedSystem | None,
    ) -> bool:
        control_channels = self._control_channels(system)
        if not control_channels:
            return False

        source = channel.find("source_configuration")
        if source is None:
            source = ET.SubElement(channel, "source_configuration")

        updated = False
        if source.get("type") != "sourceConfigTunerMultipleFrequency":
            source.set("type", "sourceConfigTunerMultipleFrequency")
            updated = True
        if source.get("source_type") != "TUNER_MULTIPLE_FREQUENCIES":
            source.set("source_type", "TUNER_MULTIPLE_FREQUENCIES")
            updated = True
        if source.get("frequency_rotation_delay") != "400":
            source.set("frequency_rotation_delay", "400")
            updated = True
        if "frequency" in source.attrib:
            del source.attrib["frequency"]
            updated = True

        existing = [child.text for child in source.findall("frequency")]
        wanted = [str(freq) for freq in control_channels]
        if existing != wanted:
            for child in list(source.findall("frequency")):
                source.remove(child)
            for freq in wanted:
                child = ET.SubElement(source, "frequency")
                child.text = freq
            updated = True

        name = "GATRRS Austin Travis CC Rotate"
        if channel.get("name") != name:
            channel.set("name", name)
            updated = True

        return updated

    def _indent_xml(self, elem: ET.Element, level: int = 0) -> None:
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            for child in elem:
                self._indent_xml(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
        elif level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
