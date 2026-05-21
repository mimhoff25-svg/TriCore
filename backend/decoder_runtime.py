from __future__ import annotations

import atexit
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from .windows_rtlsdr_tools import WORKSPACE_ROOT, find_runtime_tool


LOG_TAIL_BYTES = 32 * 1024
PROBE_TTL_SECONDS = 30.0

_PROBE_CACHE: dict[str, object] | None = None
_PROBE_CACHE_AT = 0.0


def runtime_subprocess_env(*extra_paths: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    candidate_paths = [
        find_runtime_tool("rtl_test").parent if find_runtime_tool("rtl_test") else None,
        find_runtime_tool("rtl_fm").parent if find_runtime_tool("rtl_fm") else None,
        find_runtime_tool("fmp24").parent if find_runtime_tool("fmp24") else None,
        find_runtime_tool("dsdplus").parent if find_runtime_tool("dsdplus") else None,
        WORKSPACE_ROOT / "sdrpp_windows_x64",
        WORKSPACE_ROOT / "sdrpp_windows_x64" / "DSDPlus",
        WORKSPACE_ROOT / "sdrpp_windows_x64" / "sdrpp_windows_x64",
        Path("C:/rtl-sdr"),
        *extra_paths,
    ]

    existing = [item for item in env.get("PATH", "").split(os.pathsep) if item]
    seen = {item.lower() for item in existing}
    prepend: list[str] = []
    for path in candidate_paths:
        if path is None or not path.exists():
            continue
        value = str(path)
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        prepend.append(value)

    env["PATH"] = os.pathsep.join([*prepend, *existing])
    return env


def _hidden_startupinfo() -> Optional[subprocess.STARTUPINFO]:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _cleanup_rtl_test_processes() -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["taskkill", "/IM", "rtl_test.exe", "/T", "/F"],
            capture_output=True,
            timeout=5,
            startupinfo=_hidden_startupinfo(),
            creationflags=_creation_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _tail_text(path: Path, byte_limit: int = LOG_TAIL_BYTES) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(size - byte_limit, 0))
        return handle.read().decode("utf-8", errors="replace")


def probe_rtl_sdr_device(force: bool = False) -> dict[str, object]:
    global _PROBE_CACHE, _PROBE_CACHE_AT

    now = time.monotonic()
    if not force and _PROBE_CACHE is not None and (now - _PROBE_CACHE_AT) < PROBE_TTL_SECONDS:
        return dict(_PROBE_CACHE)

    rtl_test = find_runtime_tool("rtl_test")
    snapshot: dict[str, object] = {
        "available": False,
        "path": str(rtl_test) if rtl_test else None,
        "exit_code": None,
        "output": "",
        "message": "RTL-SDR probe tool not found.",
    }

    if rtl_test is not None:
        try:
            completed = subprocess.run(
                [str(rtl_test), "-t"],
                cwd=str(rtl_test.parent),
                env=runtime_subprocess_env(rtl_test.parent),
                capture_output=True,
                text=True,
                timeout=8,
                startupinfo=_hidden_startupinfo(),
                creationflags=_creation_flags(),
            )
            output = "\n".join(
                part.strip()
                for part in (completed.stdout, completed.stderr)
                if part and part.strip()
            ).strip()

            snapshot["exit_code"] = completed.returncode
            snapshot["output"] = output

            lowered_output = output.lower()
            detected_supported_tuner = "found rafael micro" in lowered_output or "found fitipower" in lowered_output
            if "access denied" in lowered_output or "usb_open" in lowered_output:
                snapshot["message"] = "RTL-SDR access denied. Install the WinUSB driver with Zadig or close the process holding the tuner."
            elif "no supported devices found" in lowered_output:
                snapshot["message"] = "No RTL-SDR tuner detected by the bundled probe."
            elif "found" in lowered_output and "device" in lowered_output and (
                completed.returncode == 0 or detected_supported_tuner
            ):
                snapshot["available"] = True
                snapshot["message"] = output.splitlines()[0]
            elif output:
                snapshot["message"] = output.splitlines()[-1]
            else:
                snapshot["message"] = "RTL-SDR probe failed. The driver may be missing, the device may be busy, or the dongle could not be opened."
        except subprocess.TimeoutExpired:
            _cleanup_rtl_test_processes()
            snapshot["message"] = "RTL-SDR probe timed out while opening the tuner."
        except OSError as exc:
            snapshot["message"] = f"RTL-SDR probe failed: {exc}"

    _PROBE_CACHE = dict(snapshot)
    _PROBE_CACHE_AT = now
    return snapshot


class SdrTrunkRuntime:
    def __init__(self) -> None:
        default_profile_root = WORKSPACE_ROOT / "SDRTrunk"
        self.profile_root = WORKSPACE_ROOT if (WORKSPACE_ROOT / "playlist").exists() else default_profile_root
        self.profile_home = self.profile_root.parent
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._last_error: Optional[str] = None
        self._started_at: Optional[float] = None
        atexit.register(self.stop)

    def playlist_path(self) -> Path:
        return self.profile_root / "playlist" / "default.xml"

    def log_dir(self) -> Path:
        return self.profile_root / "logs"

    def _refresh_process(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            self._process = None

    def _managed_process_ids(self) -> list[int]:
        if os.name != "nt":
            return []

        launcher = find_runtime_tool("sdrtrunk_launcher")
        launcher_root = str(launcher.parents[1]).replace("'", "''").lower() if launcher is not None else ""
        profile_home = str(self.profile_home).replace("'", "''").lower()
        script = (
            f"$launcherRoot = '{launcher_root}';"
            f"$profileHome = '{profile_home}';"
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'java.exe' -or $_.Name -eq 'javaw.exe' -or $_.Name -eq 'cmd.exe' } | "
            "ForEach-Object { "
            "$cmdLine = if ($_.CommandLine) { $_.CommandLine.ToLowerInvariant() } else { '' };"
            "if (($launcherRoot -and $cmdLine.Contains($launcherRoot)) -or "
            "($cmdLine.Contains('io.github.dsheirer.gui.sdrtrunk') -and $cmdLine.Contains($profileHome))) { $_.ProcessId }"
            "}"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                startupinfo=_hidden_startupinfo(),
                creationflags=_creation_flags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if completed.returncode != 0:
            return []

        process_ids: list[int] = []
        for line in completed.stdout.splitlines():
            try:
                process_ids.append(int(line.strip()))
            except ValueError:
                pass
        return sorted(set(process_ids))

    def _latest_log_path(self) -> Optional[Path]:
        log_dir = self.log_dir()
        if not log_dir.exists():
            return None
        current_log = log_dir / "sdrtrunk_app.log"
        if current_log.exists():
            return current_log
        logs = list(log_dir.glob("*_sdrtrunk_app.log"))
        logs = sorted(set(logs), key=lambda path: path.stat().st_mtime)
        return logs[-1] if logs else None

    def _log_snapshot(self) -> dict[str, Optional[str]]:
        log_path = self._latest_log_path()
        if log_path is None:
            return {
                "path": None,
                "health": None,
                "message": "No SDRTrunk log file found yet.",
                "raw": None,
            }

        lines = [line.strip() for line in _tail_text(log_path).splitlines() if line.strip()]
        patterns = [
            ("No Tuner Available", "no_tuner", "No tuner is available for the requested P25 control channel."),
            ("access denied", "no_tuner", "RTL-SDR access denied. Install the WinUSB driver with Zadig or close the process holding the tuner."),
            ("Unable to start tuner", "no_tuner", "SDRTrunk could not start the RTL-SDR tuner."),
            ("JMBE audio conversion library IMBE CODEC successfully loaded", "ready", "JMBE audio codec loaded for P25 audio."),
            ("starting main application gui", "starting", "Bundled SDRTrunk runtime launched."),
        ]

        for line in reversed(lines):
            lowered = line.lower()
            for token, health, message in patterns:
                if token.lower() in lowered:
                    return {
                        "path": str(log_path),
                        "health": health,
                        "message": message,
                        "raw": line,
                    }

        return {
            "path": str(log_path),
            "health": None,
            "message": lines[-1] if lines else "Awaiting SDRTrunk log output.",
            "raw": lines[-1] if lines else None,
        }

    def status(self, force_probe: bool = False) -> dict[str, object]:
        self._refresh_process()

        launcher = find_runtime_tool("sdrtrunk_launcher")
        probe = probe_rtl_sdr_device(force=force_probe)
        log_snapshot = self._log_snapshot()
        managed_process_ids = self._managed_process_ids()
        running = self._process is not None or bool(managed_process_ids)
        process_id = self._process.pid if self._process is not None else (managed_process_ids[0] if managed_process_ids else None)

        health = "stopped"
        message = "Bundled SDRTrunk decoder is stopped."

        if launcher is None:
            health = "missing_runtime"
            message = "Bundled SDRTrunk runtime is missing."
        elif self._last_error:
            health = "error"
            message = self._last_error
        elif running:
            if log_snapshot["health"] == "no_tuner":
                health = "no_tuner"
                message = str(log_snapshot["message"])
            elif log_snapshot["health"] == "ready":
                health = "ready"
                message = "Bundled SDRTrunk decoder is running with the workspace playlist."
            elif self._started_at is not None and (time.monotonic() - self._started_at) >= 8:
                health = "waiting_for_channel_start"
                message = "Bundled SDRTrunk loaded the workspace profile, but the GATRRS channel has not started yet."
            else:
                health = "starting"
                message = "Bundled SDRTrunk decoder launched. Waiting for SDRTrunk status."
        elif log_snapshot["health"] == "no_tuner":
            health = "no_tuner"
            message = str(log_snapshot["message"])
        elif probe.get("available"):
            health = "stopped"
            message = "RTL-SDR tuner detected. Bundled SDRTrunk decoder is ready to launch."
        else:
            health = "no_tuner"
            message = str(probe.get("message") or "RTL-SDR tuner not available.")

        return {
            "installed": launcher is not None,
            "managed": True,
            "headless": False,
            "engine": "sdrtrunk",
            "running": running,
            "health": health,
            "message": message,
            "pid": process_id,
            "processes": {"sdrtrunk": managed_process_ids} if managed_process_ids else {},
            "launcher_path": str(launcher) if launcher is not None else None,
            "profile_root": str(self.profile_root),
            "playlist_path": str(self.playlist_path()) if self.playlist_path().exists() else None,
            "tuner_available": bool(probe.get("available")),
            "tuner_probe": probe,
            "log_path": log_snapshot["path"],
            "log_message": log_snapshot["message"],
            "log_raw": log_snapshot["raw"],
        }

    def start(self, force_probe: bool = False) -> dict[str, object]:
        self._refresh_process()
        launcher = find_runtime_tool("sdrtrunk_launcher")
        if launcher is None:
            self._last_error = "Bundled SDRTrunk launcher not found."
            return self.status(force_probe=force_probe)

        if self._process is not None:
            return self.status(force_probe=False)

        self.profile_root.mkdir(parents=True, exist_ok=True)
        probe_rtl_sdr_device(force=force_probe)

        env = os.environ.copy()
        env.update(runtime_subprocess_env(launcher.parent))
        user_home_opt = f'"-Duser.home={self.profile_home}"'
        java_opts = env.get("JAVA_OPTS", "").strip()
        if user_home_opt not in java_opts:
            env["JAVA_OPTS"] = " ".join(part for part in (java_opts, user_home_opt) if part)

        try:
            self._process = subprocess.Popen(
                ["cmd.exe", "/c", str(launcher)],
                cwd=str(launcher.parent),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=_hidden_startupinfo(),
                creationflags=_creation_flags(),
            )
            self._last_error = None
            self._started_at = time.monotonic()
            time.sleep(0.5)
            self._refresh_process()
            if self._process is None:
                self._last_error = "Bundled SDRTrunk exited immediately after launch."
                self._started_at = None
        except OSError as exc:
            self._process = None
            self._last_error = f"Bundled SDRTrunk launch failed: {exc}"
            self._started_at = None

        return self.status(force_probe=False)

    def stop(self) -> dict[str, object]:
        self._refresh_process()
        process_ids = set(self._managed_process_ids())
        if self._process is not None:
            process_ids.add(self._process.pid)
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=5,
                        startupinfo=_hidden_startupinfo(),
                        creationflags=_creation_flags(),
                    )
                else:
                    self._process.terminate()
                    self._process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._process.kill()
                except OSError:
                    pass
            finally:
                self._process = None
        if os.name == "nt":
            for process_id in process_ids:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(process_id), "/T", "/F"],
                        capture_output=True,
                        timeout=5,
                        startupinfo=_hidden_startupinfo(),
                        creationflags=_creation_flags(),
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self._last_error = None
        self._started_at = None
        return self.status(force_probe=False)
