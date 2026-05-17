"""Helpers for finding and running Windows RTL-SDR command-line tools.

Phase 1 uses these helpers for friendly diagnostics. The actual scanner can use
pyrtlsdr when available, but rtl_test.exe is still the simplest first check that
Windows, Zadig, WinUSB, and the dongle are working together.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


COMMON_RTLSDR_PATHS = [
    Path(__file__).resolve().parents[1] / "tools" / "tricore-sdr" / "rtl-sdr" / "rtl_test.exe",
    Path(__file__).resolve().parents[1] / "tools" / "tricore-sdr" / "dsdplus" / "rtl_test.exe",
    Path(__file__).resolve().parents[3] / "sdrpp_windows_x64" / "rtl_test.exe",
    Path(__file__).resolve().parents[3] / "sdrpp_windows_x64" / "sdrpp_windows_x64" / "rtl_test.exe",
    Path(__file__).resolve().parents[3] / "sdrpp_windows_x64" / "DSDPlus" / "rtl_test.exe",
    Path(r"C:\rtl-sdr\rtl_test.exe"),
    Path(r"C:\Program Files\PothosSDR\bin\rtl_test.exe"),
    Path(r"C:\Users\mimho\Downloads\SDRPlusPlus\sdrpp_windows_x64\rtl_test.exe"),
    Path(r"C:\Program Files\rtl-sdr\rtl_test.exe"),
    Path(r"C:\Program Files (x86)\rtl-sdr\rtl_test.exe"),
]


def find_tool(exe_name: str) -> Path | None:
    """Return the path to an RTL-SDR tool if it exists on PATH or common paths."""

    for path in COMMON_RTLSDR_PATHS:
        candidate = path.with_name(exe_name)
        if candidate.exists():
            return candidate

    found = shutil.which(exe_name)
    if found:
        return Path(found)

    return None


def run_rtl_test(seconds: int = 10) -> tuple[bool, str]:
    """Run rtl_test.exe briefly and return (success, output).

    rtl_test keeps running until stopped, so we start it and let subprocess kill
    it after the timeout. Seeing tuner/device lines usually means the driver is
    correct even if the command times out.
    """

    rtl_test = find_tool("rtl_test.exe")
    if rtl_test is None:
        return False, "rtl_test.exe was not found on PATH, in C:\\rtl-sdr, or in PothosSDR."

    try:
        completed = subprocess.run(
            [str(rtl_test), "-t"],
            capture_output=True,
            text=True,
            timeout=seconds,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")

    lower_output = output.lower()
    if (
        "access denied" in lower_output
        or "could not open" in lower_output
        or "failed to open" in lower_output
        or "usb_open error" in lower_output
    ):
        return False, (
            output.strip()
            + "\n\nThe RTL-SDR was detected but is busy or blocked. Close SDRTrunk/TriCore/SDR++ "
            "or any other app using the dongle, then retry."
        )

    success = "found" in lower_output or "using device" in lower_output or "rtl-sdr" in lower_output
    return success, output.strip()
