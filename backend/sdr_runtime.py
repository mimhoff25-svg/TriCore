"""TriCore-owned SDR software runtime.

This copies the locally installed SDR tools into the project so TriCore can use
one stable runtime folder instead of depending on scattered user directories.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class SdrRuntime:
    """Manages the copied SDR runtime under tools/tricore-sdr."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.scanner_root = self.project_root.parents[1]
        self.runtime_root = self.project_root / "tools" / "tricore-sdr"
        self.rtl_dir = self.runtime_root / "rtl-sdr"
        self.dsdplus_dir = self.runtime_root / "dsdplus"
        self.sdrtrunk_dir = self.runtime_root / "sdrtrunk"
        self.jmbe_dir = self.runtime_root / "jmbe"

    def ensure(self) -> dict:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []

        copied.extend(self._copy_rtl_tools())
        copied.extend(self._copy_dsdplus())
        copied.extend(self._copy_sdrtrunk())
        copied.extend(self._copy_jmbe())

        return {
            "ready": True,
            "runtime_root": str(self.runtime_root),
            "copied": copied,
            "tools": self.status()["tools"],
        }

    def status(self) -> dict:
        tools = {
            "rtl_fm": str(self.find_tool("rtl_fm.exe")) if self.find_tool("rtl_fm.exe") else None,
            "rtl_test": str(self.find_tool("rtl_test.exe")) if self.find_tool("rtl_test.exe") else None,
            "rtlsdr_dll": str(self.find_tool("rtlsdr.dll")) if self.find_tool("rtlsdr.dll") else None,
            "dsdplus": str(self.find_tool("DSDPlus.exe")) if self.find_tool("DSDPlus.exe") else None,
            "fmp24": str(self.find_tool("FMP24.exe")) if self.find_tool("FMP24.exe") else None,
            "sdrtrunk_launcher": str(self.find_sdrtrunk_launcher()) if self.find_sdrtrunk_launcher() else None,
            "jmbe": str(self.find_jmbe()) if self.find_jmbe() else None,
        }
        return {
            "ready": self.runtime_root.exists(),
            "runtime_root": str(self.runtime_root),
            "tools": tools,
        }

    def find_tool(self, name: str) -> Path | None:
        for root in [self.rtl_dir, self.dsdplus_dir, self.runtime_root]:
            if not root.exists():
                continue
            direct = root / name
            if direct.exists():
                return direct
            matches = list(root.rglob(name))
            if matches:
                return sorted(matches)[0]
        return None

    def find_sdrtrunk_launcher(self) -> Path | None:
        if not self.sdrtrunk_dir.exists():
            return None
        matches = list(self.sdrtrunk_dir.rglob("sdr-trunk.bat"))
        return sorted(matches)[0] if matches else None

    def find_jmbe(self) -> Path | None:
        for root in [self.jmbe_dir, self.runtime_root]:
            if not root.exists():
                continue
            matches = sorted(root.rglob("jmbe-*.jar"))
            if matches:
                return matches[-1]
        return None

    def _copy_rtl_tools(self) -> list[str]:
        copied: list[str] = []
        self.rtl_dir.mkdir(parents=True, exist_ok=True)
        source_roots = [
            self.scanner_root / "sdrpp_windows_x64",
            self.scanner_root / "sdrpp_windows_x64" / "sdrpp_windows_x64",
            self.scanner_root / "sdrpp_windows_x64" / "DSDPlus",
            Path(r"C:\Program Files\PothosSDR\bin"),
        ]
        names = [
            "rtl_fm.exe",
            "rtl_test.exe",
            "rtl_tcp.exe",
            "rtl_eeprom.exe",
            "rtlsdr.dll",
            "libusb-1.0.dll",
        ]
        for root in source_roots:
            if not root.exists():
                continue
            for name in names:
                source = root / name
                if not source.exists():
                    continue
                target = self.rtl_dir / name
                if self._copy_file_if_changed(source, target):
                    copied.append(str(target))
        return copied

    def _copy_dsdplus(self) -> list[str]:
        source = self.scanner_root / "sdrpp_windows_x64" / "DSDPlus"
        if not source.exists():
            return []
        return self._copy_tree_contents(source, self.dsdplus_dir)

    def _copy_sdrtrunk(self) -> list[str]:
        source = (
            self.project_root
            / "tools"
            / "sdr-trunk-windows-x86_64-v0.6.1"
            / "sdr-trunk-windows-x86_64-v0.6.1"
        )
        if not source.exists():
            return []
        return self._copy_tree_contents(source, self.sdrtrunk_dir / source.name)

    def _copy_jmbe(self) -> list[str]:
        copied: list[str] = []
        self.jmbe_dir.mkdir(parents=True, exist_ok=True)
        for source in [
            self.scanner_root / "SDRTrunk" / "jmbe" / "jmbe-1.0.9.jar",
            Path.home() / "SDRTrunk" / "jmbe" / "jmbe-1.0.9.jar",
        ]:
            if not source.exists():
                continue
            target = self.jmbe_dir / source.name
            if self._copy_file_if_changed(source, target):
                copied.append(str(target))
        return copied

    def _copy_tree_contents(self, source: Path, target: Path) -> list[str]:
        copied: list[str] = []
        for item in source.rglob("*"):
            if not item.is_file():
                continue
            relative = item.relative_to(source)
            destination = target / relative
            if self._copy_file_if_changed(item, destination):
                copied.append(str(destination))
        return copied

    def _copy_file_if_changed(self, source: Path, target: Path) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size == source.stat().st_size:
            return False
        try:
            shutil.copy2(source, target)
        except PermissionError:
            # File is locked (e.g. rtlsdr.dll held by SDRTrunk) — skip, already present
            return False
        return True
