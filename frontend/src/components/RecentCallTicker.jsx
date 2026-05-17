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
      <footer className="border-t border-white/10 bg-[#101720] px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="text-xs font-semibold uppercase tracking-normal text-slate-500">Recent Calls</div>
          <span className="text-sm text-slate-600">No calls logged yet — start scanning to see activity</span>
        </div>
      </footer>
    );
  }

  return (
    <footer className="border-t border-white/10 bg-[#101720] px-5 py-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-normal text-slate-400">
          Recent Calls <span className="ml-2 text-slate-600 font-normal normal-case">{calls.length} logged</span>
        </div>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {calls.slice(0, 12).map((call) => (
          <div
            key={call.id}
            className="shrink-0 rounded border border-white/10 bg-white/5 px-3 py-2 text-xs"
          >
            <div className={`font-semibold ${SERVICE_COLOR[call.service_type] || "text-slate-200"}`}>
              {call.name}
            </div>
            <div className="text-slate-400 tabular-nums">{(call.frequency_hz / 1_000_000).toFixed(4)} MHz</div>
            <div className="text-slate-600 mt-0.5">{call.time ? timeAgo(call.time) : ""}</div>
          </div>
        ))}
      </div>
    </footer>
  );
}
