import { Lock, Play, RadioTower, Search } from "lucide-react";
import { useMemo, useState } from "react";

const SERVICE_DOT = {
  police: "bg-blue-400",
  fire: "bg-red-400",
  ems: "bg-orange-400",
  public_works: "bg-green-400",
  transportation: "bg-indigo-400",
  interop: "bg-violet-400",
  corrections: "bg-cyan-400",
  hospital: "bg-teal-400",
  schools: "bg-fuchsia-400",
  custom: "bg-slate-400",
};

function serviceLabel(value) {
  return String(value || "custom").replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function isTcso(talkgroup) {
  const text = `${talkgroup?.alpha_tag || ""} ${talkgroup?.description || ""}`.toLowerCase();
  return text.includes("tcso") || text.includes("tc trans");
}

function groupTalkgroups(talkgroups) {
  const groups = new Map();
  for (const talkgroup of talkgroups) {
    const tag = talkgroup.tag || talkgroup.category || serviceLabel(talkgroup.service_type);
    const list = groups.get(tag) || [];
    list.push(talkgroup);
    groups.set(tag, list);
  }
  return [...groups.entries()]
    .map(([tag, list]) => ({
      tag,
      list: list.slice().sort((a, b) => Number(a.decimal || 0) - Number(b.decimal || 0)),
      locked: list.filter((item) => item.encrypted).length,
      clear: list.filter((item) => !item.encrypted).length,
    }))
    .sort((a, b) => {
      const aTcso = a.list.some(isTcso);
      const bTcso = b.list.some(isTcso);
      if (aTcso !== bTcso) return aTcso ? -1 : 1;
      return a.tag.localeCompare(b.tag);
    });
}

export default function GatrrsPanel({
  talkgroups = [],
  selectedTalkgroup,
  onSelectTalkgroup,
}) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState({});
  const normalizedQuery = query.trim().toLowerCase();

  const filteredTalkgroups = useMemo(() => {
    if (!normalizedQuery) return talkgroups;
    return talkgroups.filter((talkgroup) => (
      [
        talkgroup.alpha_tag,
        talkgroup.description,
        talkgroup.tag,
        talkgroup.service_type,
        talkgroup.decimal,
      ].some((value) => String(value || "").toLowerCase().includes(normalizedQuery))
    ));
  }, [talkgroups, normalizedQuery]);

  const groups = useMemo(() => groupTalkgroups(filteredTalkgroups), [filteredTalkgroups]);
  const clearCount = talkgroups.filter((talkgroup) => !talkgroup.encrypted).length;
  const lockedCount = talkgroups.length - clearCount;

  function groupOpen(group, index) {
    if (expanded[group.tag] !== undefined) return expanded[group.tag];
    return index < 2 || group.list.some((talkgroup) => selectedTalkgroup?.decimal === talkgroup.decimal);
  }

  return (
    <section className="rounded-lg border border-triCoreBlue/20 bg-[#101720]">
      <div className="border-b border-white/10 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
          <RadioTower className="h-4 w-4 text-triCoreBlue" />
          GATRRS P25
        </div>
        <div className="mt-1 text-xs text-slate-500">
          {groups.length} categories - {clearCount} clear - {lockedCount} locked
        </div>
        <div className="mt-3 flex items-center gap-2 rounded-md border border-white/10 bg-black/20 px-2 py-1.5">
          <Search className="h-4 w-4 text-slate-500" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter talkgroups"
            className="w-full bg-transparent text-sm text-white placeholder:text-slate-500 focus:outline-none"
          />
        </div>
      </div>

      <div className="max-h-[48vh] overflow-y-auto p-2">
        {groups.map((group, index) => {
          const isOpen = groupOpen(group, index);
          return (
            <details
              key={group.tag}
              open={isOpen}
              onToggle={(event) => {
                const open = event.currentTarget.open;
                setExpanded((current) => (
                  current[group.tag] === open ? current : { ...current, [group.tag]: open }
                ));
              }}
              className="mb-2 rounded-lg border border-white/10 bg-black/15"
            >
              <summary className="cursor-pointer list-none p-3">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${SERVICE_DOT[group.list[0]?.service_type] || SERVICE_DOT.custom}`} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-white">{group.tag}</div>
                    <div className="text-xs text-slate-500">{group.list.length} TGs - {group.clear} clear{group.locked ? ` - ${group.locked} locked` : ""}</div>
                  </div>
                </div>
              </summary>

              <div className="border-t border-white/10">
                {group.list.map((talkgroup) => {
                  const active = selectedTalkgroup?.decimal === talkgroup.decimal;
                  const locked = Boolean(talkgroup.encrypted);
                  return (
                    <button
                      key={talkgroup.id || talkgroup.decimal}
                      type="button"
                      disabled={locked}
                      onClick={() => onSelectTalkgroup?.(talkgroup)}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left transition ${
                        active
                          ? "bg-triCoreBlue/20 text-white"
                          : locked
                            ? "text-slate-600"
                            : "text-slate-300 hover:bg-white/5"
                      }`}
                    >
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${locked ? "bg-red-400" : SERVICE_DOT[talkgroup.service_type] || SERVICE_DOT.custom}`} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-semibold">{talkgroup.alpha_tag}</span>
                        <span className="block truncate text-[11px] text-slate-500">
                          TG {talkgroup.decimal} - {talkgroup.description || serviceLabel(talkgroup.service_type)}
                        </span>
                      </span>
                      <span className={`flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${locked ? "border-red-400/30 text-red-300" : "border-triCoreBlue/25 text-triCoreBlue"}`}>
                        {locked ? <Lock className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                        {locked ? "LOCK" : "P25"}
                      </span>
                    </button>
                  );
                })}
              </div>
            </details>
          );
        })}
        {groups.length === 0 && (
          <div className="rounded border border-white/10 bg-black/20 p-3 text-sm text-slate-500">
            No GATRRS talkgroups found.
          </div>
        )}
      </div>
    </section>
  );
}
