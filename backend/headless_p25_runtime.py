from __future__ import annotations

import atexit
import csv
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .decoder_runtime import _creation_flags, _hidden_startupinfo, _tail_text, probe_rtl_sdr_device, runtime_subprocess_env
from .windows_rtlsdr_tools import PROJECT_ROOT, WORKSPACE_ROOT, find_runtime_tool


LOG_TAIL_BYTES = 16 * 1024
STARTUP_GRACE_SECONDS = 2.0
CONTROL_CHANNEL_HUNT_SECONDS = 90.0
SUPPORT_FILE_NAMES = {
    "DSDPlus.bin",
    "DSDPlus.exe",
    "FMP24.exe",
    "FMP24.cfg",
    "FMPA.cfg",
    "FMPP.cfg",
    "FMP-Map.exe",
    "FMP-Map.cfg",
    "LRRP.exe",
    "Survey.exe",
}
LOG_SKIP_TOKENS = (
    "current working directory",
    "audio output device",
    "appending synthesized audio",
    "assuming fmp",
    "program role is",
    "fusion decoding enabled",
    "d-star decoding enabled",
    "dmr/mototrbo decoding enabled",
    "x2-tdma decoding enabled",
    "dsd+ 2.",
    "p25 data loaded",
    "sdr sampling rate",
    "spectrum window width",
    "fft size",
    "spectrum update rate",
    "step size table",
    "dsd+ path is",
    "database search distance",
    "base latitude/longitude",
    "role is control/rest channel monitor",
    "role is voice channel monitor",
    "using rtl sdr device",
    "using first available rtl sdr device",
    "using dsd+ link id",
    "sdr device count",
    "sdr device #",
    "rtl sdr device #",
    "tuner type",
    "serial string",
    "sampling rate set",
    "frequency correction factor",
    "waiting for dsd+ link",
    "accepted dsd+ link",
    "no frequency data files found",
    "trunk control/rest channel following active",
    "trunk voice following active",
    "ppm correction set",
    "initial frequency set",
    "optimizing fft calculations",
    "auto-starting control/rest channel following mode",
    "following enabled",
    "file not found in working folder",
    "fmpx link established",
    "initiating fmpx link",
    "fmpx link error",
    "server is not listening",
    "affiliation",
    "registration",
    "deregistration",
    "patch supergroup",
    "patch subgroup",
    "current site",
    "current network",
    "neighbor:",
    "alias server",
    "talker alias",
    "sending alias update",
    "connected to alias server",
    "connecting to alias server",
    "byte response received",
    "testing base files",
    "files checked",
    "files passed",
    "files not found",
    "file:",
    "use [dsd+ misc menu]",
    "mono audio decoding initiated",
    "records saved",
    "aliases saved",
)
TIMESTAMP_ONLY_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2}$")


def _hide_windows_for_pid(pid: int) -> None:
    if os.name != "nt":
        return

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        process_id = wintypes.DWORD()
        hwnds: list[int] = []

        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_proc(hwnd: int, _: int) -> bool:
            user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(process_id))
            if int(process_id.value) == int(pid) and user32.IsWindowVisible(wintypes.HWND(hwnd)):
                hwnds.append(hwnd)
            return True

        user32.EnumWindows(enum_proc_type(_enum_proc), 0)
        for hwnd in hwnds:
            user32.ShowWindow(wintypes.HWND(hwnd), 0)  # SW_HIDE
    except Exception:
        # Best-effort hide only; do not break pipeline startup if window API calls fail.
        return


class HeadlessP25Runtime:
    def __init__(self, control_channels_hz: list[int]) -> None:
        self.tool_root = WORKSPACE_ROOT / "sdrpp_windows_x64" / "DSDPlus"
        self.profile_root = PROJECT_ROOT / "runtime" / "dsdplus-profile"
        self.log_root = self.profile_root / "logs"
        self.control_channels_hz = [int(channel) for channel in control_channels_hz if channel]
        self._control_channel_index = 0
        self._control_channel_hz: Optional[int] = self.control_channels_hz[0] if self.control_channels_hz else None
        self._sdr_device_index = 0
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._log_handles: dict[str, object] = {}
        self._last_error: Optional[str] = None
        self._started_at: Optional[float] = None
        self._failover_count = 0
        self._last_failover_at: Optional[float] = None
        self._last_failover_reason: Optional[str] = None
        atexit.register(self.stop)

    def config_path(self) -> Path:
        return self.profile_root

    def control_channel_hz(self) -> Optional[int]:
        return self._control_channel_hz

    def _tool_paths(self) -> dict[str, Optional[Path]]:
        return {
            "fmp24": find_runtime_tool("fmp24"),
            "dsdplus": find_runtime_tool("dsdplus"),
        }

    def _refresh_processes(self) -> None:
        stopped: list[str] = []
        for name, process in self._processes.items():
            if process.poll() is not None:
                stopped.append(name)
        for name in stopped:
            self._processes.pop(name, None)
            handle = self._log_handles.pop(name, None)
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass

    def _ensure_profile(self) -> None:
        self.log_root.mkdir(parents=True, exist_ok=True)
        templates = {
            "DSDPlus.P25data": "; Managed by TriCore headless runtime\n",
            "DSDPlus.networks": "; Managed by TriCore headless runtime\n",
            "DSDPlus.sites": "; Managed by TriCore headless runtime\n",
            "DSDPlus.siteLoader": "; Managed by TriCore headless runtime\n",
            "DSDPlus.frequencies": "; Managed by TriCore headless runtime\n",
            "DSDPlus.groups": "; Managed by TriCore headless runtime\n",
            "DSDPlus.radios": "; Managed by TriCore headless runtime\n",
        }
        for file_name, content in templates.items():
            path = self.profile_root / file_name
            if not path.exists():
                path.write_text(content, encoding="utf-8")

        for source in sorted(self.tool_root.glob("*.dll")):
            target = self.profile_root / source.name
            if (
                not target.exists()
                or target.stat().st_size != source.stat().st_size
                or target.stat().st_mtime < source.stat().st_mtime
            ):
                shutil.copy2(source, target)

        for file_name in SUPPORT_FILE_NAMES:
            source = self.tool_root / file_name
            target = self.profile_root / file_name
            if source.exists() and not target.exists():
                shutil.copy2(source, target)

    def _profile_runtime_tool(self, source: Optional[Path]) -> Path:
        if source is None:
            raise FileNotFoundError("Runtime tool path is not available.")

        self.profile_root.mkdir(parents=True, exist_ok=True)
        target = self.profile_root / source.name
        if (
            not target.exists()
            or target.stat().st_size != source.stat().st_size
            or target.stat().st_mtime < source.stat().st_mtime
        ):
            shutil.copy2(source, target)
        return target

    def _log_path(self, name: str) -> Path:
        return self.log_root / f"{name}.log"

    def _p25data_path(self) -> Path:
        return self.profile_root / "DSDPlus.P25data"

    def _radios_path(self) -> Path:
        return self.profile_root / "DSDPlus.radios"

    def _groups_path(self) -> Path:
        return self.profile_root / "DSDPlus.groups"

    def prioritize_talkgroup(self, decimal: int, alias: str, network_id: str = "BEE09.13E") -> None:
        self._ensure_profile()
        path = self._groups_path()
        existing_lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
        safe_alias = alias.replace('"', "'")
        priority_line = (
            f'P25,       {network_id}, {int(decimal):<10}, 1,  Normal,       0,  '
            f'0000/00/00  0:00,  "{safe_alias}"'
        )
        updated_lines: list[str] = []
        replaced = False
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                updated_lines.append(line)
                continue
            try:
                fields = next(csv.reader([line], skipinitialspace=True))
            except (csv.Error, StopIteration):
                updated_lines.append(line)
                continue
            if len(fields) >= 3 and fields[0].strip().upper() == "P25" and fields[2].strip() == str(int(decimal)):
                updated_lines.append(priority_line)
                replaced = True
            else:
                updated_lines.append(line)

        if not replaced:
            if updated_lines and updated_lines[-1].strip():
                updated_lines.append("")
            updated_lines.append(priority_line)

        path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")

    def _event_log_path(self) -> Optional[Path]:
        if not self.profile_root.exists():
            return None
        event_logs = sorted(self.profile_root.glob("*DSDPlus.event"), key=lambda path: path.stat().st_mtime)
        return event_logs[-1] if event_logs else None

    def _data_lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]

    def _p25data_snapshot(self) -> dict[str, object]:
        path = self._p25data_path()
        lines = self._data_lines(path)
        return {
            "path": str(path),
            "record_count": len(lines),
            "last_line": lines[-1] if lines else None,
            "mtime": path.stat().st_mtime if path.exists() else None,
        }

    def _recent_radios(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for line in self._data_lines(self._radios_path()):
            try:
                fields = next(csv.reader([line], skipinitialspace=True))
            except (csv.Error, StopIteration):
                continue
            if len(fields) < 8:
                continue
            if str(fields[0]).strip().upper() != "P25":
                continue
            try:
                group_value = int(str(fields[2]).strip())
                radio_value = int(str(fields[3]).strip())
            except ValueError:
                continue
            records.append({
                "protocol": "P25",
                "network_id": str(fields[1]).strip(),
                "group": group_value,
                "radio": radio_value,
                "hits": int(str(fields[6]).strip() or "0") if str(fields[6]).strip().isdigit() else 0,
                "timestamp": str(fields[7]).strip() if len(fields) > 7 else None,
                "alias": str(fields[8]).strip().strip('"') if len(fields) > 8 else None,
            })
        return records[-10:]

    def _interesting_log_lines(self, paths: list[Path], limit: int = 25) -> list[str]:
        interesting: list[str] = []
        for path in paths:
            if not path.exists():
                continue
            lines = [line.strip() for line in _tail_text(path, byte_limit=LOG_TAIL_BYTES).splitlines() if line.strip()]
            for line in reversed(lines):
                lowered = line.lower()
                if TIMESTAMP_ONLY_RE.match(line):
                    continue
                if any(token in lowered for token in LOG_SKIP_TOKENS):
                    continue
                interesting.append(line)
                if len(interesting) >= limit:
                    return interesting
        return interesting

    def _interesting_log_line(self, paths: list[Path]) -> Optional[str]:
        lines = self._interesting_log_lines(paths, limit=1)
        return lines[0] if lines else None

    def _parse_activity_line(self, raw_line: Optional[str]) -> dict[str, object]:
        if not raw_line:
            return {}

        activity: dict[str, object] = {"raw": raw_line}
        lowered = raw_line.lower()

        is_voice_event = (
            "group call" in lowered
            or "lc_grp_v_ch_usr" in lowered
            or ("grp_v_ch_grant" in lowered and "updt" not in lowered)
            or "hdu:" in lowered
        )
        if is_voice_event:
            activity["voice_event"] = True

        frequency_match = re.search(r"\b(?:ch|channel)\s*=\s*(\d{3}\.\d{1,6})\b", raw_line, flags=re.IGNORECASE)
        if not frequency_match:
            frequency_match = re.search(r"(\d{3}\.\d{4,6})\s*mhz", raw_line, flags=re.IGNORECASE)
        if frequency_match:
            activity["voice_frequency_hz"] = int(float(frequency_match.group(1)) * 1_000_000)

        control_frequency_match = re.search(r"\bFreq=(\d{3}\.\d{4,6})\b", raw_line, flags=re.IGNORECASE)
        if control_frequency_match:
            activity["control_frequency_hz"] = int(float(control_frequency_match.group(1)) * 1_000_000)

        nac_match = re.search(r"\bNAC[:=]([0-9A-F]{1,4})\b", raw_line, flags=re.IGNORECASE)
        if nac_match:
            activity["nac"] = nac_match.group(1).upper()

        talkgroup_match = re.search(r"\bTG\s*[:=]\s*(\d{1,7})\b", raw_line, flags=re.IGNORECASE)
        if not talkgroup_match and "grp" in lowered:
            talkgroup_match = re.search(r"\bTgt\s*=\s*(\d{1,7})\b", raw_line, flags=re.IGNORECASE)
        if not talkgroup_match:
            talkgroup_match = re.search(r"\b(?:tgid|group)\D{0,6}(\d{1,7})\b", raw_line, flags=re.IGNORECASE)
        if talkgroup_match:
            activity["talkgroup_decimal"] = int(talkgroup_match.group(1))

        source_match = re.search(r"\b(?:rid|src|source|from|radio)\D{0,8}(\d{3,})\b", raw_line, flags=re.IGNORECASE)
        if source_match:
            activity["source_radio_id"] = source_match.group(1)

        target_match = re.search(r"\b(?:tgt|target|to)\D{0,8}(\d{3,})\b", raw_line, flags=re.IGNORECASE)
        if target_match:
            activity["target_radio_id"] = target_match.group(1)

        if "phase ii" in lowered or "tdma" in lowered:
            activity["phase"] = "P25 Phase II"
        elif "phase i" in lowered or "fdma" in lowered:
            activity["phase"] = "P25 Phase I"
        elif "p25p1" in lowered:
            activity["phase"] = "P25 Phase I"

        if " enc " in f" {lowered} " or "encrypted" in lowered:
            activity["encrypted"] = True

        return activity

    def _activity_snapshot(self) -> dict[str, object]:
        event_log = self._event_log_path()
        paths = [
            event_log if event_log is not None else self._log_path("missing-event-log"),
            self._log_path("dsdplus-1r"),
            self._log_path("fmp24-control"),
        ]
        raw_lines = self._interesting_log_lines(paths)
        raw_line = raw_lines[0] if raw_lines else None
        activity = self._parse_activity_line(raw_line)
        activity["recent_events"] = [self._parse_activity_line(line) for line in raw_lines]
        recent_radios = self._recent_radios()
        activity["recent_radios"] = recent_radios
        return activity

    def _start_pipeline(self, tool_paths: dict[str, Optional[Path]]) -> None:
        self._ensure_profile()
        self._clear_run_outputs()
        fmp24_path = self._profile_runtime_tool(tool_paths["fmp24"])
        dsdplus_path = self._profile_runtime_tool(tool_paths["dsdplus"])
        self._launch(
            "fmp24-control",
            [
                str(fmp24_path),
                "-z0",
                "-rc",
                f"-i{self._sdr_device_index}",
                "-o20001",
                "-P1.371",
                f"-f{self._format_frequency(self._control_channel_hz or 0)}",
            ],
        )
        time.sleep(0.25)
        self._launch(
            "dsdplus-1r",
            [
                str(dsdplus_path),
                "-r1",
                "-i20001",
            ],
        )
        self._started_at = time.monotonic()
        self._last_error = None

    def _stop_processes(self, reset_hunt: bool) -> None:
        self._refresh_processes()
        for name, process in list(self._processes.items()):
            try:
                process.terminate()
                process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                except OSError:
                    pass
            finally:
                self._processes.pop(name, None)
                handle = self._log_handles.pop(name, None)
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
        self._last_error = None
        self._started_at = None
        if reset_hunt:
            self._control_channel_index = 0
            self._control_channel_hz = self.control_channels_hz[0] if self.control_channels_hz else None
            self._failover_count = 0
            self._last_failover_at = None
            self._last_failover_reason = None

    def _rotate_control_channel(self, reason: str) -> None:
        if len(self.control_channels_hz) < 2:
            return
        self._control_channel_index = (self._control_channel_index + 1) % len(self.control_channels_hz)
        self._control_channel_hz = self.control_channels_hz[self._control_channel_index]
        self._failover_count += 1
        self._last_failover_reason = reason
        self._last_failover_at = time.monotonic()

    def _maybe_failover(self, tool_paths: dict[str, Optional[Path]]) -> bool:
        if len(self.control_channels_hz) < 2 or len(self._processes) != 2 or self._started_at is None:
            return False

        now = time.monotonic()
        if (now - self._started_at) < CONTROL_CHANNEL_HUNT_SECONDS:
            return False
        if self._last_failover_at is not None and (now - self._last_failover_at) < CONTROL_CHANNEL_HUNT_SECONDS:
            return False

        if int(self._p25data_snapshot().get("record_count") or 0) > 0:
            return False

        if self._control_activity_detected():
            return False

        self._rotate_control_channel("No P25 control data was recorded on the current control channel.")
        self._stop_processes(reset_hunt=False)
        self._start_pipeline(tool_paths)
        time.sleep(0.5)
        self._refresh_processes()
        return True

    def _control_activity_detected(self) -> bool:
        paths = [self._log_path("dsdplus-1r")]
        event_log = self._event_log_path()
        if event_log is not None:
            paths.append(event_log)
        tokens = ("p25p1", "nac=", "current site", "group call", "grp_v_ch_grant", "lc_grp_v_ch_usr")
        for path in paths:
            if not path.exists():
                continue
            text = _tail_text(path, byte_limit=LOG_TAIL_BYTES).lower()
            if any(token in text for token in tokens):
                return True
        return False

    def _log_snapshot(self) -> dict[str, object]:
        paths = [self._log_path(name) for name in ("fmp24-control", "dsdplus-1r")]
        event_log = self._event_log_path()
        if event_log is not None:
            paths.append(event_log)

        last_line = None
        error_message = None
        error_health = None
        for path in paths:
            if not path.exists():
                continue
            lines = [line.strip() for line in _tail_text(path, byte_limit=LOG_TAIL_BYTES).splitlines() if line.strip()]
            if not lines:
                continue
            tail_text = "\n".join(lines).lower()
            last_line = lines[-1]
            if "invalid command line parameter" in tail_text:
                error_message = "FMP24/DSDPlus was launched with an unsupported command-line argument."
                error_health = "error"
                break
            if "failed checksum test" in tail_text:
                error_message = "FMP24 rejected one of the staged DSDPlus support files."
                error_health = "error"
                break
            if "receiver hardware error detected" in tail_text or "remove/reinsert dongle" in tail_text:
                error_message = "FMP24 opened the RTL-SDR but the receiver reported a hardware error. Reinsert the dongle or stop the process holding it."
                error_health = "no_tuner"
                break
            if (
                ("fmpx link error" in tail_text or "server is not listening on selected link id" in tail_text)
                and "fmpx link established" not in tail_text
                and "accepted dsd+ link" not in tail_text
            ):
                error_message = "DSDPlus cannot connect to FMP24 on link ID 20001."
                error_health = "error"
                break
            for line in reversed(lines):
                lowered = line.lower()
                if "access denied" in lowered or "usb_open" in lowered or "device busy" in lowered:
                    error_message = "RTL-SDR access denied. Install the WinUSB driver with Zadig or close the process holding the tuner."
                    error_health = "no_tuner"
                    break
                if "no supported devices found" in lowered or "unable to open" in lowered:
                    error_message = "The headless P25 runtime could not open the RTL-SDR tuner."
                    error_health = "no_tuner"
                    break
                if "base files test" in lowered or "phase 1 and phase 2 decoding enabled" in lowered:
                    break
            if error_message:
                break

        return {
            "last_line": last_line,
            "error_message": error_message,
            "error_health": error_health,
            "event_log_path": str(event_log) if event_log is not None else None,
        }

    def _clear_run_outputs(self) -> None:
        for name in ("fmp24-control", "dsdplus-1r", "fmp24-voice", "dsdplus-control", "dsdplus-voice"):
            path = self._log_path(name)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

        for path in self.profile_root.glob("*DSDPlus.event"):
            try:
                path.unlink()
            except OSError:
                pass

        try:
            self._p25data_path().write_text("; Managed by TriCore headless runtime\n", encoding="utf-8")
        except OSError:
            pass

    def _format_frequency(self, frequency_hz: int) -> str:
        return f"{frequency_hz / 1_000_000:.4f}".rstrip("0").rstrip(".")

    def _launch(self, name: str, command: list[str]) -> None:
        log_path = self._log_path(name)
        log_handle = log_path.open("ab")
        process = subprocess.Popen(
            command,
            cwd=str(self.profile_root),
            env=runtime_subprocess_env(self.profile_root, self.tool_root),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            startupinfo=_hidden_startupinfo(),
            creationflags=_creation_flags(),
        )
        self._processes[name] = process
        self._log_handles[name] = log_handle
        self._hide_process_windows(name, process.pid)

    def _hide_process_windows(self, name: str, pid: int) -> None:
        _hide_windows_for_pid(pid)

        def _delayed_hide() -> None:
            # Some decoder windows are created shortly after process start.
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                process = self._processes.get(name)
                if process is None or process.poll() is not None:
                    break
                _hide_windows_for_pid(pid)
                time.sleep(0.25)

        if os.name == "nt":
            threading.Thread(target=_delayed_hide, daemon=True).start()

    def status(self, force_probe: bool = False) -> dict[str, object]:
        self._refresh_processes()
        tool_paths = self._tool_paths()
        self._maybe_failover(tool_paths)
        log_snapshot = self._log_snapshot()
        p25data_snapshot = self._p25data_snapshot()
        activity_snapshot = self._activity_snapshot()
        control_activity = self._control_activity_detected()
        missing_tools = [name for name, path in tool_paths.items() if path is None]
        running_processes = {name: process.pid for name, process in self._processes.items()}
        running = bool(running_processes)
        all_running = len(running_processes) == 2
        if running:
            probe = {
                "available": True,
                "path": str(find_runtime_tool("rtl_test") or ""),
                "exit_code": None,
                "output": "",
                "message": "RTL-SDR tuner is in use by the managed DSDPlus pipeline.",
            }
        else:
            probe = probe_rtl_sdr_device(force=force_probe)

        health = "stopped"
        message = "Headless P25 runtime is stopped."

        if missing_tools:
            health = "missing_runtime"
            message = f"Headless DSDPlus runtime is missing required tools: {', '.join(missing_tools)}."
        elif self._last_error:
            health = "error"
            message = self._last_error
        elif log_snapshot.get("error_message") and (running or self._started_at is not None):
            health = str(log_snapshot.get("error_health") or "error")
            message = str(log_snapshot["error_message"])
        elif running and all_running:
            if self._started_at is not None and (time.monotonic() - self._started_at) < STARTUP_GRACE_SECONDS:
                health = "starting"
                message = "Headless DSDPlus pipeline launched. Waiting for all receivers and decoders."
            elif int(p25data_snapshot.get("record_count") or 0) == 0 and len(self.control_channels_hz) > 1 and not control_activity:
                health = "starting"
                message = (
                    "Headless DSDPlus pipeline is hunting GATRRS control channels on "
                    f"{self._format_frequency(self._control_channel_hz or 0)} MHz."
                )
            else:
                health = "ready"
                if self._control_channel_hz is not None:
                    message = (
                        "Headless DSDPlus control and voice pipeline running on "
                        f"{self._format_frequency(self._control_channel_hz)} MHz."
                    )
                else:
                    message = "Headless DSDPlus control and voice pipeline running."
        elif running:
            health = "starting"
            if self._started_at is not None and (time.monotonic() - self._started_at) >= STARTUP_GRACE_SECONDS:
                message = "Headless DSDPlus pipeline launched, but one or more decoder processes exited early."
            else:
                message = "Headless DSDPlus pipeline launched. Waiting for all receivers and decoders."
        elif probe.get("available"):
            health = "stopped"
            message = "RTL-SDR tuner detected. Headless DSDPlus runtime is ready to launch."
        else:
            health = "no_tuner"
            message = str(probe.get("message") or "RTL-SDR tuner not available.")

        return {
            "installed": not missing_tools,
            "managed": True,
            "headless": True,
            "engine": "dsdplus",
            "running": running,
            "health": health,
            "message": message,
            "control_channel_hz": self._control_channel_hz,
            "control_channel_index": self._control_channel_index,
            "control_channels_hz": self.control_channels_hz,
            "sdr_device_index": self._sdr_device_index,
            "failover_count": self._failover_count,
            "last_failover_reason": self._last_failover_reason,
            "tool_root": str(self.tool_root),
            "profile_root": str(self.profile_root),
            "config_path": str(self.config_path()),
            "processes": running_processes,
            "log_root": str(self.log_root),
            "event_log_path": log_snapshot.get("event_log_path"),
            "log_message": log_snapshot.get("last_line"),
            "p25data_path": p25data_snapshot.get("path"),
            "p25data_records": p25data_snapshot.get("record_count"),
            "p25data_last_line": p25data_snapshot.get("last_line"),
            "activity": activity_snapshot,
            "tuner_available": bool(probe.get("available")),
            "tuner_probe": probe,
        }

    def start(self, force_probe: bool = False) -> dict[str, object]:
        self._refresh_processes()
        tool_paths = self._tool_paths()
        missing_tools = [name for name, path in tool_paths.items() if path is None]
        if missing_tools:
            self._last_error = f"Headless DSDPlus runtime is missing required tools: {', '.join(missing_tools)}."
            return self.status(force_probe=force_probe)

        if self._control_channel_hz is None:
            self._last_error = "No control channel is configured for the headless P25 runtime."
            return self.status(force_probe=force_probe)

        if self._processes:
            return self.status(force_probe=False)

        try:
            self._start_pipeline(tool_paths)
            time.sleep(0.5)
            self._refresh_processes()
            if not self._processes:
                self._last_error = "Headless DSDPlus runtime exited immediately after launch."
                self._started_at = None
        except OSError as exc:
            self._last_error = f"Headless DSDPlus runtime failed to launch: {exc}"
            self._stop_processes(reset_hunt=False)

        return self.status(force_probe=False)

    def stop(self) -> dict[str, object]:
        self._stop_processes(reset_hunt=True)
        return self.status(force_probe=False)
