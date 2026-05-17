import { ChevronDown, ChevronRight, Folder, ListTree, Lock, Play, RadioTower, RotateCcw, Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const API_BASE = "http://127.0.0.1:8000";

const SERVICE_DOT = {
  police: "bg-blue-400",
  fire: "bg-red-400",
  ems: "bg-orange-400",
  weather: "bg-sky-400",
  public_works: "bg-green-400",
  utility: "bg-yellow-400",
  transportation: "bg-indigo-400",
  interop: "bg-violet-400",
  railroad: "bg-lime-400",
  corrections: "bg-cyan-400",
  hospital: "bg-teal-400",
  data: "bg-slate-500",
  schools: "bg-fuchsia-400",
  fm_radio: "bg-pink-400",
  am_radio: "bg-rose-400",
  custom: "bg-slate-400",
};

const SERVICE_LABEL = {
  police: "Law",
  fire: "Fire",
  ems: "EMS",
  weather: "Weather",
  public_works: "Public Works",
  utility: "Utilities",
  transportation: "Transit",
  interop: "Interop",
  railroad: "Railroad",
  corrections: "Corrections",
  hospital: "Hospitals",
  data: "Data",
  schools: "Schools",
  fm_radio: "FM Broadcast",
  am_radio: "AM Broadcast",
  custom: "Other",
};

const PLAYLISTS = [
  { id: "favorites", name: "Favorites", label: "FL 0", match: (ch) => ch.favorite },
  { id: "railroad", name: "Railroad", label: "FL 1", match: (ch) => ch.service_type === "railroad" || ch.category === "railroad" },
  { id: "public-safety", name: "Public Safety", label: "FL 2", match: (ch) => ["police", "fire", "ems", "interop"].includes(ch.service_type) || ch.category === "public_safety" },
  { id: "fire-ems", name: "Fire / EMS", label: "FL 3", match: (ch) => ["fire", "ems"].includes(ch.service_type) },
  { id: "weather", name: "Weather", label: "FL 4", match: (ch) => ch.service_type === "weather" },
  { id: "broadcast", name: "Broadcast FM", label: "FL 5", match: (ch) => ch.service_type === "fm_radio" },
];

function groupBy(items, keyFn) {
  const groups = {};
  for (const item of items) {
    const key = keyFn(item) || "Other";
    if (!groups[key]) groups[key] = [];
    groups[key].push(item);
  }
  return groups;
}

function ToggleIcon({ open }) {
  return open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />;
}

export default function SystemList({
  channels: channelsProp,
  disabledSystems,
  onToggleSystem,
  onTuneChannel,
  onScanSystem,
  onScanAllSystems,
  onScanPlaylist,
  onSelectTalkgroup,
  activeChannel,
  activePlaylist,
  selectedTalkgroup,
}) {
  const [internalChannels, setInternalChannels] = useState([]);
  const [talkgroups, setTalkgroups] = useState([]);
  const [expanded, setExpanded] = useState({
    favorites: true,
    services: true,
    departments: true,
    trunked: true,
  });
  const [loading, setLoading] = useState(!channelsProp);

  const channels = channelsProp ?? internalChannels;

  useEffect(() => {
    const promises = [
      fetch(`${API_BASE}/api/trunked/talkgroups?include_encrypted=true`).then((r) => r.json()).catch(() => []),
    ];
    if (!channelsProp) {
      promises.unshift(fetch(`${API_BASE}/api/channels`).then((r) => r.json()));
    }
    Promise.all(promises)
      .then((results) => {
        if (!channelsProp) {
          setInternalChannels(results[0]);
          setTalkgroups(results[1]);
        } else {
          setTalkgroups(results[0]);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [channelsProp]);

  const playlists = useMemo(
    () => PLAYLISTS.map((playlist) => ({
      ...playlist,
      channels: channels.filter(playlist.match),
    })).filter((playlist) => playlist.channels.length > 0),
    [channels],
  );

  const serviceGroups = useMemo(() => groupBy(channels, (ch) => ch.service_type), [channels]);
  const systemGroups = useMemo(() => groupBy(channels, (ch) => ch.system), [channels]);
  const talkgroupGroups = useMemo(() => groupBy(talkgroups, (tg) => tg.tag || SERVICE_LABEL[tg.service_type]), [talkgroups]);

  function toggleExpand(name) {
    setExpanded((prev) => ({ ...prev, [name]: !prev[name] }));
  }

  function scanChannels(id, name, list) {
    onScanPlaylist?.({
      id,
      name,
      channelIds: list.map((ch) => ch.id),
      systemNames: [...new Set(list.map((ch) => ch.system))],
    });
  }

  function folderHeader(id, title, subtitle, icon, action) {
    const open = Boolean(expanded[id]);
    return (
      <div className="flex items-center gap-2 px-3 py-2">
        <button onClick={() => toggleExpand(id)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <span className="text-slate-500"><ToggleIcon open={open} /></span>
          <span className="text-slate-400">{icon}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-white">{title}</span>
            <span className="block truncate text-xs text-slate-500">{subtitle}</span>
          </span>
        </button>
        {action}
      </div>
    );
  }

  return (
    <aside className="flex w-full flex-col border-r border-white/10 bg-[#101720] lg:w-80">
      <div className="border-b border-white/10 p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-normal text-slate-300">Bearcat Scan Lists</h2>
          <button
            onClick={onScanAllSystems}
            aria-label="Scan all systems"
            title="Scan all systems"
            className="flex h-8 w-8 items-center justify-center rounded border border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-0.5 text-xs text-slate-500">
          {Object.keys(systemGroups).length} departments - {channels.length} channels - {talkgroups.length} talkgroups
        </p>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {loading && <div className="p-3 text-sm text-slate-500">Loading...</div>}

        <div className="rounded border border-triCoreAmber/20 bg-triCoreAmber/5">
          {folderHeader("favorites", "Favorites Lists", `${playlists.length} quick scan folders`, <Star className="h-4 w-4" />)}
          {expanded.favorites && (
            <div className="border-t border-white/5 p-2">
              {playlists.map((playlist) => (
                <div
                  key={playlist.id}
                  className={`mb-1 rounded border ${activePlaylist?.id === playlist.id ? "border-triCoreGreen/40 bg-triCoreGreen/10" : "border-white/10 bg-black/10"}`}
                >
                  <div className="flex items-center gap-2 px-2 py-2">
                    <span className="rounded border border-triCoreAmber/25 px-1.5 py-0.5 text-[10px] font-bold text-triCoreAmber">{playlist.label}</span>
                    <button onClick={() => toggleExpand(`playlist-${playlist.id}`)} className="min-w-0 flex-1 text-left">
                      <div className="truncate text-sm font-semibold text-white">{playlist.name}</div>
                      <div className="text-xs text-slate-500">{playlist.channels.length} channels</div>
                    </button>
                    <button
                      onClick={() => scanChannels(playlist.id, playlist.name, playlist.channels)}
                      aria-label={`Scan playlist ${playlist.name}`}
                      className="flex h-8 w-8 items-center justify-center rounded border border-triCoreGreen/25 bg-triCoreGreen/10 text-triCoreGreen hover:bg-triCoreGreen/20"
                    >
                      <Play className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {expanded[`playlist-${playlist.id}`] && (
                    <div className="border-t border-white/5">
                      {playlist.channels.map((ch) => <ChannelRow key={ch.id} channel={ch} active={activeChannel?.id === ch.id} onTuneChannel={onTuneChannel} />)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded border border-white/10 bg-black/10">
          {folderHeader("services", "Service Types", "Bearcat-style service search", <ListTree className="h-4 w-4" />)}
          {expanded.services && (
            <div className="border-t border-white/5">
              {Object.entries(serviceGroups).sort(([a], [b]) => (SERVICE_LABEL[a] || a).localeCompare(SERVICE_LABEL[b] || b)).map(([service, list]) => {
                const id = `service-${service}`;
                return (
                  <div key={service} className="border-b border-white/5 last:border-b-0">
                    <div className="flex items-center gap-2 px-3 py-2">
                      <span className={`h-2 w-2 rounded-full ${SERVICE_DOT[service] || SERVICE_DOT.custom}`} />
                      <button onClick={() => toggleExpand(id)} className="min-w-0 flex-1 text-left">
                        <div className="truncate text-sm font-semibold text-white">{SERVICE_LABEL[service] || service}</div>
                        <div className="text-xs text-slate-500">{list.length} channels</div>
                      </button>
                      <button
                        onClick={() => scanChannels(id, SERVICE_LABEL[service] || service, list)}
                        aria-label={`Scan service ${SERVICE_LABEL[service] || service}`}
                        className="flex h-8 w-8 items-center justify-center rounded border border-triCoreGreen/25 bg-triCoreGreen/10 text-triCoreGreen hover:bg-triCoreGreen/20"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    {expanded[id] && list.map((ch) => <ChannelRow key={ch.id} channel={ch} active={activeChannel?.id === ch.id} onTuneChannel={onTuneChannel} />)}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="rounded border border-white/10 bg-black/10">
          {folderHeader("departments", "Departments / Systems", "Enable, avoid, or scan one department", <Folder className="h-4 w-4" />)}
          {expanded.departments && (
            <div className="border-t border-white/5">
              {Object.entries(systemGroups).sort(([a], [b]) => a.localeCompare(b)).map(([system, list]) => {
                const isDisabled = disabledSystems?.has(system);
                const id = `system-${system}`;
                return (
                  <div key={system} className={`border-b border-white/5 last:border-b-0 ${isDisabled ? "opacity-45" : ""}`}>
                    <div className="flex items-center gap-2 px-3 py-2">
                      <button
                        onClick={() => onToggleSystem?.(system)}
                        aria-label={isDisabled ? `Enable ${system}` : `Disable ${system}`}
                        title={isDisabled ? "Enable department" : "Avoid department"}
                        className={`h-4 w-4 shrink-0 rounded-sm border ${isDisabled ? "border-white/20" : "border-triCoreGreen bg-triCoreGreen/20"}`}
                      />
                      <button onClick={() => toggleExpand(id)} className="min-w-0 flex-1 text-left">
                        <div className="truncate text-sm font-semibold text-white">{system}</div>
                        <div className="text-xs text-slate-500">{list.length} channels</div>
                      </button>
                      <button
                        onClick={() => onScanSystem?.(system)}
                        aria-label={`Scan ${system}`}
                        className="flex h-8 w-8 items-center justify-center rounded border border-triCoreGreen/25 bg-triCoreGreen/10 text-triCoreGreen hover:bg-triCoreGreen/20"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    {expanded[id] && list.map((ch) => <ChannelRow key={ch.id} channel={ch} active={activeChannel?.id === ch.id} onTuneChannel={onTuneChannel} />)}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {talkgroups.length > 0 && (
          <div className="rounded border border-triCoreBlue/20 bg-triCoreBlue/5">
            {folderHeader("trunked", "GATRRS Talkgroup Folders", "Click a clear talkgroup to monitor in SDRTrunk", <RadioTower className="h-4 w-4" />)}
            {expanded.trunked && (
              <div className="border-t border-white/5">
                {Object.entries(talkgroupGroups).sort(([a], [b]) => a.localeCompare(b)).map(([tag, list]) => {
                  const id = `tg-${tag}`;
                  const locked = list.filter((tg) => tg.encrypted).length;
                  return (
                    <div key={tag} className="border-b border-white/5 last:border-b-0">
                      <button onClick={() => toggleExpand(id)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
                        <span className="text-slate-500"><ToggleIcon open={expanded[id]} /></span>
                        <span className={`h-2 w-2 rounded-full ${SERVICE_DOT[list[0]?.service_type] || SERVICE_DOT.custom}`} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold text-white">{tag}</span>
                          <span className="block text-xs text-slate-500">{list.length} TGs{locked ? ` - ${locked} locked` : ""}</span>
                        </span>
                      </button>
                      {expanded[id] && list.map((tg) => (
                        <TalkgroupRow
                          key={tg.id}
                          talkgroup={tg}
                          active={selectedTalkgroup?.decimal === tg.decimal}
                          onSelectTalkgroup={onSelectTalkgroup}
                        />
                      ))}
                    </div>
                  );
                })}
                <div className="px-3 py-2 text-xs text-slate-500">
                  P25 voice follows the control channel in SDRTrunk. Locked entries are encrypted/unavailable.
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function ChannelRow({ channel, active, onTuneChannel }) {
  return (
    <button
      onClick={() => onTuneChannel?.(channel)}
      className={`flex w-full items-center gap-2 px-4 py-2 text-left transition hover:bg-white/5 ${active ? "bg-triCoreGreen/10" : ""}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${SERVICE_DOT[channel.service_type] || SERVICE_DOT.custom}`} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-slate-200">{channel.name}</span>
        <span className="block text-xs text-slate-500 tabular-nums">
          {(channel.frequency_hz / 1_000_000).toFixed(4)} MHz
          {channel.priority && <span className="ml-1 text-triCoreAmber">PRI</span>}
          {channel.favorite && <span className="ml-1 text-triCoreBlue">FAV</span>}
        </span>
      </span>
      <RadioTower className="h-3.5 w-3.5 shrink-0 text-slate-500" />
    </button>
  );
}

function TalkgroupRow({ talkgroup, active, onSelectTalkgroup }) {
  return (
    <button
      onClick={() => onSelectTalkgroup?.(talkgroup)}
      aria-label={`Monitor ${talkgroup.alpha_tag}`}
      className={`flex w-full items-center gap-2 px-4 py-2 text-left transition hover:bg-white/5 ${active ? "bg-triCoreBlue/15 ring-1 ring-inset ring-triCoreBlue/35" : ""}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${talkgroup.encrypted ? "bg-red-400" : SERVICE_DOT[talkgroup.service_type] || SERVICE_DOT.custom}`} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-slate-200">{talkgroup.alpha_tag}</span>
        <span className="block truncate text-xs text-slate-500">TG {talkgroup.decimal} - {talkgroup.description || talkgroup.tag}</span>
      </span>
      <span className={`flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${talkgroup.encrypted ? "border-red-400/30 text-red-300" : "border-triCoreBlue/20 text-triCoreBlue"}`}>
        {talkgroup.encrypted && <Lock className="h-3 w-3" />}
        {talkgroup.encrypted ? "LOCK" : "P25"}
      </span>
    </button>
  );
}
