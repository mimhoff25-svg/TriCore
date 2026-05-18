import { Radio, Wifi, WifiOff } from "lucide-react";

export default function TopStatusBar({ status, receiver, currentTime }) {
  const online = status?.state !== "error";
  const mode = receiver?.label || status?.receiver_mode || "Demo";

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
          <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 font-mono text-sm font-semibold text-white">
            {currentTime}
          </div>
        </div>
      </div>
    </header>
  );
}

