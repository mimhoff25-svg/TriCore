import { Activity, Plus, Radio, Wifi } from "lucide-react";

export default function TopBar({ currentTime, status, onAddChannel }) {
  const isOnline = status?.state !== "ERROR";
  const receiverLabel = "RTL-SDR Hardware";

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 bg-[#111822]/95 px-5 py-4 lg:px-7">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded border border-triCoreGreen/30 bg-triCoreGreen/10 shadow-[0_0_28px_rgba(101,240,160,0.16)]">
          <Radio className="h-7 w-7 text-triCoreGreen" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-normal lg:text-3xl">TriCore Scanner</h1>
          <p className="text-sm text-slate-300">{receiverLabel}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-right">
        <div className={`flex items-center gap-2 rounded border px-3 py-2 ${isOnline ? "border-green-400/20 bg-green-500/10 text-triCoreGreen" : "border-red-400/20 bg-red-500/10 text-red-200"}`}>
          <Wifi className="h-4 w-4" />
          <span className="text-sm font-semibold">{isOnline ? "Windows Node Online" : "Backend Offline"}</span>
        </div>
        <div className="flex items-center gap-2 rounded border border-white/10 bg-white/5 px-3 py-2 text-slate-200">
          <Activity className="h-4 w-4 text-triCoreBlue" />
          <span className="text-sm font-semibold">{status?.state || "NO_SIGNAL"}</span>
        </div>
        <button
          onClick={onAddChannel}
          className="flex items-center gap-2 rounded border border-triCoreBlue/30 bg-triCoreBlue/10 px-3 py-2 text-sm font-semibold text-triCoreBlue hover:bg-triCoreBlue/20 transition"
        >
          <Plus className="h-4 w-4" />
          Add Channel
        </button>
        <div className="min-w-28 text-xl font-semibold tabular-nums">{currentTime}</div>
      </div>
    </header>
  );
}
