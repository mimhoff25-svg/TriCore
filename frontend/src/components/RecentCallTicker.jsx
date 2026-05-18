const SERVICE_COLOR = {
  fire: "text-red-300", ems: "text-orange-300", police: "text-blue-300",
  weather: "text-sky-300", fm_radio: "text-pink-300", am_radio: "text-rose-300",
  interop: "text-violet-300", public_works: "text-green-300",
  utility: "text-yellow-300", custom: "text-slate-300",
};

function timeAgo(isoString) {
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function RecentCallTicker({ calls = [] }) {
  if (calls.length === 0) {
    return (
      <footer className="border-t border-white/10 bg-[#071019]/95 px-5 py-4 backdrop-blur-xl">
        <div className="flex flex-wrap items-center gap-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.32em] text-slate-500">Recent Calls</div>
          <span className="text-sm text-slate-600">No calls logged yet — start scanning to see activity.</span>
        </div>
      </footer>
    );
  }

  return (
    <footer className="border-t border-white/10 bg-[#071019]/95 px-5 py-4 backdrop-blur-xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.32em] text-slate-400">Recent Calls</div>
        <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-300">
          {calls.length} logged
        </div>
      </div>
      <div className="mt-3 flex gap-3 overflow-x-auto pb-1">
        {calls.slice(0, 12).map((call) => (
          <div
            key={call.id}
            className="shrink-0 rounded-[20px] border border-white/10 bg-[#111a25]/75 px-3 py-3 text-xs shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
          >
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${(SERVICE_COLOR[call.service_type] || "text-slate-200").replace("text", "bg")}`} />
              <div className={`font-semibold ${SERVICE_COLOR[call.service_type] || "text-slate-200"}`}>
                {call.name}
              </div>
            </div>
            <div className="mt-2 text-slate-400 tabular-nums">{(Number(call.frequency_hz || 0) / 1_000_000).toFixed(4)} MHz</div>
            <div className="mt-1 text-slate-600">{call.time ? timeAgo(call.time) : ""}</div>
          </div>
        ))}
      </div>
    </footer>
  );
}
