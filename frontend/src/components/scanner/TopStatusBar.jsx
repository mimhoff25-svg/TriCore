import { useEffect, useRef, useState } from "react";
import { Play, Radio, Settings, Usb, Volume2, Wifi, WifiOff } from "lucide-react";

export default function TopStatusBar({
  status,
  receiver,
  currentTime,
  audioDevices = [],
  selectedAudioDeviceId = "default",
  onAudioDeviceChange,
  audioMonitoringEnabled = false,
  onAudioMonitoringChange,
  audioVolume = 0.85,
  onAudioVolumeChange,
  onAudioMonitorPlay,
  audioMonitorError = "",
}) {
  const online = status?.state !== "error";
  const mode = receiver?.label || status?.receiver_mode || "Demo";
  const [settingsOpen, setSettingsOpen] = useState(false);
  const menuRef = useRef(null);
  const dongleConnected = Boolean(receiver?.rtl_sdr_available || (receiver?.mode === "rtl_sdr" && receiver?.available));
  const dongleMessage = receiver?.last_rtl_error || receiver?.message || "No dongle status available.";
  const volumePercent = Math.round(Math.min(1, Math.max(0, audioVolume)) * 100);

  useEffect(() => {
    function onDocumentClick(event) {
      if (!menuRef.current?.contains(event.target)) {
        setSettingsOpen(false);
      }
    }
    if (settingsOpen) {
      document.addEventListener("mousedown", onDocumentClick);
    }
    return () => document.removeEventListener("mousedown", onDocumentClick);
  }, [settingsOpen]);

  return (
    <header className="border-b border-white/10 bg-[#090d12] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-triCoreGreen/30 bg-triCoreGreen/10">
            <Radio className="h-5 w-5 text-triCoreGreen" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">TriCore Scanner</h1>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Standalone SDR scanner foundation</div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] ${online ? "border-triCoreGreen/25 bg-triCoreGreen/10 text-triCoreGreen" : "border-red-400/30 bg-red-500/10 text-red-200"}`}>
            {online ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
            {online ? "Core Online" : "Core Offline"}
          </div>
          <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm font-semibold text-slate-200">
            {status?.scanner_state || "Stopped"}
          </div>
          <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm font-semibold text-slate-200">
            {mode}
          </div>
          <div className="flex min-w-[240px] items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2">
            <Volume2 className="h-4 w-4 text-triCoreGreen" />
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={audioVolume}
              onChange={(event) => onAudioVolumeChange?.(event.target.value)}
              className="h-2 w-24 accent-triCoreGreen"
              aria-label="Live audio volume"
              title="Live audio volume"
            />
            <div className="w-9 text-right font-mono text-xs font-semibold text-slate-300">{volumePercent}</div>
            <button
              type="button"
              onClick={() => onAudioMonitorPlay?.()}
              className="rounded-md border border-triCoreGreen/35 bg-triCoreGreen/10 p-1.5 text-triCoreGreen hover:bg-triCoreGreen/20"
              aria-label="Play live audio"
              title="Play live audio"
            >
              <Play className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 font-mono text-sm font-semibold text-white">
            {currentTime}
          </div>
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setSettingsOpen((open) => !open)}
              className="rounded-lg border border-white/10 bg-black/20 p-2 text-slate-200 hover:border-triCoreGreen/40 hover:text-white"
              aria-label="Open settings"
              title="Settings"
            >
              <Settings className="h-4 w-4" />
            </button>

            {settingsOpen ? (
              <div className="absolute right-0 z-30 mt-2 w-80 rounded-xl border border-white/10 bg-[#0e1521] p-3 shadow-2xl shadow-black/50">
                <div className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Settings</div>

                <div className="mb-3 rounded-lg border border-white/10 bg-black/20 p-3">
                  <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
                    <Usb className="h-3.5 w-3.5" />
                    Dongle Status
                  </div>
                  <div className={`mb-1 text-sm font-semibold ${dongleConnected ? "text-triCoreGreen" : "text-amber-300"}`}>
                    {dongleConnected ? "Connected" : "Disconnected / Busy"}
                  </div>
                  <div className="text-xs text-slate-300">{dongleMessage}</div>
                </div>

                <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                  <div className="mb-3 rounded-md border border-white/10 bg-[#0a0f18] p-2">
                    <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
                      <Volume2 className="h-3.5 w-3.5" />
                      Live Audio Monitor
                    </div>
                    <button
                      type="button"
                      onClick={() => audioMonitoringEnabled ? onAudioMonitoringChange?.(false) : onAudioMonitorPlay?.()}
                      className={`w-full rounded-md border px-2 py-2 text-sm font-semibold ${audioMonitoringEnabled ? "border-triCoreGreen/40 bg-triCoreGreen/15 text-triCoreGreen" : "border-white/15 bg-black/20 text-slate-200"}`}
                    >
                      {audioMonitoringEnabled ? "Audio Monitor On" : "Audio Monitor Off"}
                    </button>
                    <button
                      type="button"
                      onClick={() => onAudioMonitorPlay?.()}
                      className="mt-2 flex w-full items-center justify-center gap-2 rounded-md border border-triCoreBlue/35 bg-triCoreBlue/10 px-2 py-2 text-sm font-semibold text-triCoreBlue hover:bg-triCoreBlue/20"
                    >
                      <Play className="h-3.5 w-3.5" />
                      Play Audio
                    </button>
                    {audioMonitorError ? <div className="mt-2 text-[11px] text-amber-300">{audioMonitorError}</div> : null}
                  </div>

                  <div className="mb-3 rounded-md border border-white/10 bg-[#0a0f18] p-2">
                    <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
                      <span>Volume</span>
                      <span className="font-mono text-slate-300">{volumePercent}</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.01"
                      value={audioVolume}
                      onChange={(event) => onAudioVolumeChange?.(event.target.value)}
                      className="w-full accent-triCoreGreen"
                      aria-label="Live audio volume"
                    />
                  </div>

                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Audio Output Device</div>
                  <select
                    value={selectedAudioDeviceId}
                    onChange={(event) => onAudioDeviceChange?.(event.target.value)}
                    className="w-full rounded-md border border-white/15 bg-[#0a0f18] px-2 py-2 text-sm text-slate-100 outline-none focus:border-triCoreGreen/50"
                  >
                    <option value="default">System Default</option>
                    {audioDevices.map((device) => (
                      <option key={device.deviceId || device.label} value={device.deviceId}>
                        {device.label || `Audio Output ${device.deviceId?.slice(0, 8) || "Unknown"}`}
                      </option>
                    ))}
                  </select>
                  <div className="mt-2 text-[11px] text-slate-400">
                    Device selection applies to the live audio monitor when browser/electron audio sink switching is supported.
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </header>
  );
}
