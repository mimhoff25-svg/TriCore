import { Activity, ListChecks, RadioTower } from "lucide-react";

function titleCase(value) {
  return String(value || "--").replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export default function ScanModePanel({ status, activeChannel = null, selectedTalkgroup = null, talkgroups = [] }) {
  const scanning = Boolean(status?.is_scanning || status?.is_holding || status?.is_paused);
  const enabledTalkgroupCount = talkgroups.filter((talkgroup) => talkgroup && !talkgroup.encrypted && talkgroup.scan_enabled).length;
  const focusLabel = String(
    selectedTalkgroup?.alpha_tag
      || activeChannel?.name
      || "Waiting for active channel",
  ).trim();
  const modeLabel = status?.is_holding
    ? "Stay Here"
    : status?.is_paused
      ? "Paused"
      : status?.is_scanning
        ? "Scanning"
        : titleCase(status?.state || "stopped");

  return (
    <section className="rounded-lg border border-white/10 bg-[#101720] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">Scan Mode</div>
          <div className="mt-1 text-xs text-slate-500">Current scan state and active focus</div>
        </div>
        <div className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${scanning ? "border-triCoreGreen/30 bg-triCoreGreen/15 text-triCoreGreen" : "border-white/10 bg-black/25 text-slate-300"}`}>
          {modeLabel}
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            <RadioTower className="h-4 w-4 text-triCoreBlue" />
            Active Focus
          </div>
          <div className="mt-2 text-sm font-semibold text-white">{focusLabel}</div>
          <div className="mt-1 text-xs text-slate-400">{activeChannel ? titleCase(activeChannel.service_type || activeChannel.category || "public_safety") : "No active channel selected"}</div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              <ListChecks className="h-4 w-4 text-triCoreAmber" />
              Armed TGs
            </div>
            <div className="mt-2 text-xl font-semibold text-white">{enabledTalkgroupCount}</div>
            <div className="mt-1 text-xs text-slate-400">GATRRS talkgroups enabled</div>
          </div>

          <div className="rounded-xl border border-white/10 bg-black/20 p-3">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              <Activity className="h-4 w-4 text-triCoreGreen" />
              Status
            </div>
            <div className="mt-2 text-xl font-semibold text-white">{titleCase(status?.scanner_state || status?.state || "stopped")}</div>
            <div className="mt-1 text-xs text-slate-400">{status?.message || "Scanner ready"}</div>
          </div>
        </div>
      </div>
    </section>
  );
}