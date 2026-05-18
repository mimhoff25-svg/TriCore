from __future__ import annotations

from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "tools" / "tricore-sdr"


def runtime_tool_candidates() -> dict[str, list[Path]]:
    return {
        "fmp24": [
            RUNTIME_ROOT / "dsdplus" / "FMP24.exe",
            WORKSPACE_ROOT / "sdrpp_windows_x64" / "DSDPlus" / "FMP24.exe",
        ],
        "rtl_fm": [
            RUNTIME_ROOT / "rtl-sdr" / "rtl_fm.exe",
            Path("C:/rtl-sdr/rtl_fm.exe"),
            WORKSPACE_ROOT / "sdrpp_windows_x64" / "rtl_fm.exe",
        ],
        "rtl_test": [
            RUNTIME_ROOT / "rtl-sdr" / "rtl_test.exe",
            Path("C:/rtl-sdr/rtl_test.exe"),
            WORKSPACE_ROOT / "sdrpp_windows_x64" / "rtl_test.exe",
        ],
        "dsdplus": [
            RUNTIME_ROOT / "dsdplus" / "DSDPlus.exe",
            WORKSPACE_ROOT / "sdrpp_windows_x64" / "DSDPlus" / "DSDPlus.exe",
        ],
        "sdrtrunk_launcher": [
            RUNTIME_ROOT / "sdrtrunk" / "sdr-trunk-windows-x86_64-v0.6.1" / "bin" / "sdr-trunk.bat",
            RUNTIME_ROOT / "sdrtrunk" / "sdr-trunk.bat",
            WORKSPACE_ROOT / "SDRTrunk" / "bin" / "sdr-trunk.bat",
        ],
        "jmbe": [
            RUNTIME_ROOT / "jmbe" / "jmbe-1.0.9.jar",
            RUNTIME_ROOT / "sdrtrunk" / "jmbe" / "jmbe-1.0.9.jar",
            WORKSPACE_ROOT / "SDRTrunk" / "jmbe" / "jmbe-1.0.9.jar",
        ],
    }


def detect_runtime_tools() -> dict[str, bool]:
    return {name: any(path.exists() for path in paths) for name, paths in runtime_tool_candidates().items()}


def find_runtime_tool(name: str) -> Optional[Path]:
    for path in runtime_tool_candidates().get(name, []):
        if path.exists():
            return path
    return None


def runtime_root() -> str:
    return str(RUNTIME_ROOT)