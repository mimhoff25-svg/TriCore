import { Activity, Plus, Radio, Wifi } from "lucide-react";

export default function TopBar({ currentTime, status, onAddChannel }) {
  const isOnline = status?.state !== "ERROR";
  const liveState = status?.state || "NO_SIGNAL";
  const held = Boolean(status?.held);

  return (
    <header className="sticky top-0 z-20 border-b border-white/10 bg-[#08111a]/90 backdrop-blur-xl">
      <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-4 lg:px-7">
        <div className="flex min-w-0 items-center gap-4">
          <div className="relative flex h-14 w-14 shrink-0 items-center justify-center">
            <div className="absolute inset-0 rounded-2xl bg-triCoreGreen/15 blur-md" />
            <div className="relative flex h-full w-full items-center justify-center rounded-2xl border border-triCoreGreen/35 bg-[#0d1c16] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
              <Radio className="h-7 w-7 text-triCoreGreen" />
            </div>
          </div>
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.35em] text-slate-500">All-In-One Radio Console</div>
            <h1 className="truncate text-2xl font-semibold tracking-[0.02em] text-white lg:text-3xl">TriCore Scanner</h1>
            <p className="truncate text-sm text-slate-400">Built-in scanning, trunking, audio, and live radio intelligence</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-right">
          <div className={`flex items-center gap-2 rounded-full border px-3 py-2 ${isOnline ? "border-triCoreGreen/25 bg-triCoreGreen/10 text-triCoreGreen" : "border-red-400/20 bg-red-500/10 text-red-200"}`}>
            <Wifi className="h-4 w-4" />
            <span className="text-xs font-semibold uppercase tracking-[0.2em]">{isOnline ? "TriCore Core Online" : "Backend Offline"}</span>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-2 text-slate-200">
            <Activity className={`h-4 w-4 ${held ? "text-triCoreAmber" : "text-triCoreBlue"}`} />
            <span className="text-sm font-semibold">{held ? "Hold" : liveState}</span>
          </div>
          <div className="rounded-full border border-white/10 bg-black/20 px-4 py-2 text-lg font-semibold tabular-nums text-white">
            {currentTime}
          </div>
          <button
            onClick={onAddChannel}
            className="flex items-center gap-2 rounded-full border border-triCoreBlue/30 bg-triCoreBlue/10 px-4 py-2 text-sm font-semibold text-triCoreBlue transition hover:bg-triCoreBlue/20"
          >
            <Plus className="h-4 w-4" />
            Add Channel
          </button>
        </div>
      </div>
    </header>
  );
}
