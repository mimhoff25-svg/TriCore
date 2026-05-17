import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import ChannelEditor from "./components/ChannelEditor";
import NowListeningCard from "./components/NowListeningCard";
import RecentCallTicker from "./components/RecentCallTicker";
import ScannerControls from "./components/ScannerControls";
import SystemList from "./components/SystemList";
import TopBar from "./components/TopBar";

const API_BASE = "http://127.0.0.1:8000";

async function api(path, method = "GET", body = undefined) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed with ${res.status}`);
  }
  return data;
}

function App() {
  const [status, setStatus] = useState({
    state: "NO_SIGNAL", message: "Loading...", simulated: false, held: false, in_delay: false,
  });
  const [time, setTime]               = useState(new Date().toLocaleTimeString());
  const [gain, setGain]               = useState("auto");
  const [muted, setMuted]             = useState(false);
  const [disabledSystems, setDisabledSystems] = useState(new Set());
  const [calls, setCalls]             = useState([]);
  const [channels, setChannels]       = useState([]);
  const [fmStations, setFmStations]   = useState([]);
  const [fmPlayer, setFmPlayer]       = useState(null);
  const [p25, setP25]                 = useState(null);
  const [sdrRuntime, setSdrRuntime]   = useState(null);
  const [activePlaylist, setActivePlaylist] = useState(null);
  const [showAddChannel, setShowAddChannel] = useState(false);

  async function refreshStatus() {
    const s = await api("/api/status");
    setStatus(s);
  }

  async function refreshCalls() {
    const c = await api("/api/calls");
    setCalls(c);
  }

  async function refreshP25() {
    const p = await api("/api/p25/status");
    setP25(p);
  }

  async function refreshSdrRuntime() {
    setSdrRuntime(await api("/api/sdr/runtime/status"));
  }

  async function refreshChannels() {
    const ch = await api("/api/channels");
    setChannels(ch);
  }

  async function refreshFmStations() {
    const stations = await api("/api/fm/stations");
    setFmStations(stations);
  }

  async function refreshFmPlayer() {
    const player = await api("/api/fm/player/status");
    setFmPlayer(player);
  }

  // ── Scanner lifecycle ──────────────────────────────────────────────────────

  async function startScanner() {
    setActivePlaylist(null);
    setDisabledSystems(new Set());
    await api("/api/scanner/channel-filter", "POST", { channel_ids: null });
    await api("/api/scanner/group-filter", "POST", { systems: null });
    setStatus(await api("/api/scanner/start", "POST"));
  }

  async function stopScanner() {
    setStatus(await api("/api/scanner/stop", "POST"));
  }

  async function scanSystem(systemName) {
    const systemChannels = channels.filter((channel) => channel.system === systemName);
    if (systemChannels.length && systemChannels.every((channel) => channel.service_type === "railroad" || channel.category === "railroad")) {
      await tuneToChannel(systemChannels[0]);
      setActivePlaylist({ id: `system-${systemName}`, name: systemName });
      return;
    }
    const allNames = [...new Set(channels.map((c) => c.system))];
    const nextDisabled = new Set(allNames.filter((name) => name !== systemName));
    setDisabledSystems(nextDisabled);
    setActivePlaylist({ id: `system-${systemName}`, name: systemName });
    await api("/api/scanner/channel-filter", "POST", { channel_ids: null });
    await api("/api/scanner/group-filter", "POST", { systems: [systemName] });
    setStatus(await api("/api/scanner/start", "POST"));
  }

  async function scanAllSystems() {
    setDisabledSystems(new Set());
    setActivePlaylist(null);
    await api("/api/scanner/channel-filter", "POST", { channel_ids: null });
    await api("/api/scanner/group-filter", "POST", { systems: null });
    setStatus(await api("/api/scanner/start", "POST"));
  }

  async function scanPlaylist(playlist) {
    const playlistChannels = channels.filter((channel) => playlist.channelIds.includes(channel.id));
    if (playlist.id === "railroad" && playlistChannels.length) {
      await tuneToChannel(playlistChannels[0]);
      setActivePlaylist({ id: playlist.id, name: playlist.name });
      return;
    }
    const allNames = [...new Set(channels.map((c) => c.system))];
    const enabled = new Set(playlist.systemNames || []);
    setDisabledSystems(new Set(allNames.filter((name) => !enabled.has(name))));
    setActivePlaylist({ id: playlist.id, name: playlist.name });
    await api("/api/scanner/group-filter", "POST", { systems: null });
    await api("/api/scanner/channel-filter", "POST", { channel_ids: playlist.channelIds });
    setStatus(await api("/api/scanner/start", "POST"));
  }

  // ── Scanner controls ───────────────────────────────────────────────────────

  async function holdOrResume() {
    if (status.held) {
      setStatus(await api("/api/scanner/clear-hold", "POST"));
    } else {
      setStatus(await api("/api/scanner/hold", "POST"));
    }
  }

  async function skipChannel() {
    setStatus(await api("/api/scanner/skip", "POST"));
  }

  async function toggleMute() {
    const next = !muted;
    setMuted(next);
    setStatus(await api("/api/scanner/mute", "POST", { muted: next }));
  }

  // ── Group filter (Do Not Monitor) ─────────────────────────────────────────

  async function toggleSystem(systemName) {
    const next = new Set(disabledSystems);
    if (next.has(systemName)) {
      next.delete(systemName);
    } else {
      next.add(systemName);
    }
    setDisabledSystems(next);
    const allNames = [...new Set(channels.map((c) => c.system))];
    const enabled = allNames.filter((n) => !next.has(n));
    await api("/api/scanner/group-filter", "POST", {
      systems: enabled.length === allNames.length ? null : enabled,
    });
  }

  // ── Individual channel tune ────────────────────────────────────────────────

  async function tuneToChannel(channel) {
    try {
      if (channel.service_type === "fm_radio") {
        const player = await api("/api/fm/play", "POST", { channel_id: channel.id });
        setFmPlayer(player);
        setStatus(await api("/api/status"));
      } else {
        setStatus(await api("/api/scanner/tune", "POST", { channel_id: channel.id }));
      }
    } catch (error) {
      setStatus((current) => ({ ...current, message: error.message || "Channel tune failed" }));
    }
  }

  // ── Add channel ────────────────────────────────────────────────────────────

  async function addChannel(data) {
    try {
      const nextStatus = await api("/api/channels/add", "POST", data);
      setStatus(nextStatus);
      setShowAddChannel(false);
      await refreshChannels();
    } catch (error) {
      setStatus((current) => ({ ...current, message: error.message || "Channel add failed" }));
    }
  }

  // ── Device settings ────────────────────────────────────────────────────────

  async function changeGain(value) {
    setGain(value);
    setStatus(await api("/api/scanner/gain", "POST", {
      gain_db: value === "auto" ? null : Number(value),
    }));
  }

  async function launchTrunkingDecoder() {
    try {
      setP25(await api("/api/p25/start", "POST"));
    } catch (error) {
      setP25((current) => ({ ...current, message: error.message || "SDR backend start failed" }));
    }
  }

  async function selectTalkgroup(talkgroup) {
    try {
      setActivePlaylist({ id: `tg-${talkgroup.decimal}`, name: talkgroup.alpha_tag });
      setP25(await api("/api/p25/select-talkgroup", "POST", { decimal: talkgroup.decimal }));
    } catch (error) {
      setP25((current) => ({ ...current, message: error.message || "Talkgroup select failed" }));
    }
  }

  async function stopP25Decoder() {
    try {
      setP25(await api("/api/p25/stop", "POST"));
    } catch (error) {
      setP25((current) => ({ ...current, message: error.message || "P25 stop failed" }));
    }
  }

  async function syncSdrRuntime() {
    try {
      setSdrRuntime(await api("/api/sdr/runtime/sync", "POST"));
    } catch (error) {
      setSdrRuntime((current) => ({ ...current, ready: false, message: error.message || "Runtime sync failed" }));
    }
  }

  async function stopFmPlayer() {
    setFmPlayer(await api("/api/fm/stop", "POST"));
  }

  async function fineTuneFm(offsetHz) {
    const stationId = fmPlayer?.station?.id || activeFmStation?.id;
    if (!stationId) return;
    setFmPlayer(await api("/api/fm/fine-tune", "POST", { channel_id: stationId, offset_hz: offsetHz }));
  }

  // ── Polling + clock ────────────────────────────────────────────────────────

  useEffect(() => {
    refreshStatus().catch(() =>
      setStatus({ state: "ERROR", message: "Backend offline", simulated: false, held: false })
    );
    refreshCalls().catch(() => null);
    refreshChannels().catch(() => null);
    refreshP25().catch(() => null);
    refreshSdrRuntime().catch(() => null);
    refreshFmStations().catch(() => null);
    refreshFmPlayer().catch(() => null);
    const statusTimer = setInterval(() => refreshStatus().catch(() => null), 1000);
    const callsTimer  = setInterval(() => refreshCalls().catch(() => null), 5000);
    const p25Timer    = setInterval(() => refreshP25().catch(() => null), 1500);
    const fmTimer     = setInterval(() => refreshFmPlayer().catch(() => null), 1000);
    const clockTimer  = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => {
      clearInterval(statusTimer);
      clearInterval(callsTimer);
      clearInterval(p25Timer);
      clearInterval(fmTimer);
      clearInterval(clockTimer);
    };
  }, []);

  const scanning = status.state === "SCANNING" || status.state === "RECEIVING_CALL" || status.state === "HOLDING_CHANNEL";
  const activeFmStation = fmPlayer?.station || fmStations.find((station) => station.id === status.active_channel?.id);
  const p25DisplayChannel = p25?.selected_talkgroup && p25?.running
    ? {
        id: `tg-${p25.selected_talkgroup.decimal}`,
        name: p25.selected_talkgroup.alpha_tag,
        frequency_hz: p25.active_call?.voice_frequency_hz || p25.preferred_control_channel_hz,
        system: "GATRRS",
        service_type: p25.selected_talkgroup.service_type,
        modulation: "p25",
        delay_seconds: 0,
      }
    : null;
  const displayStatus = p25DisplayChannel
    ? {
        ...status,
        state: p25.state || "WAITING_FOR_TALKGROUP",
        message: p25.message,
        active_channel: p25DisplayChannel,
        signal_power: status.signal_power ?? 0,
      }
    : status;

  return (
    <div className="min-h-screen bg-[#090d13] text-white">
      <TopBar currentTime={time} status={displayStatus} onAddChannel={() => setShowAddChannel(true)} />

      <main className="flex min-h-[calc(100vh-148px)] flex-col lg:flex-row">
        <SystemList
          channels={channels}
          disabledSystems={disabledSystems}
          onToggleSystem={toggleSystem}
          onTuneChannel={tuneToChannel}
          onScanSystem={scanSystem}
          onScanAllSystems={scanAllSystems}
          onScanPlaylist={scanPlaylist}
          onSelectTalkgroup={selectTalkgroup}
          activeChannel={displayStatus.active_channel}
          activePlaylist={activePlaylist}
          selectedTalkgroup={p25?.selected_talkgroup}
        />

        <section className="flex-1 p-5 lg:p-7">
          {/* Quick-status row */}
          <div className="mb-5 grid gap-3 md:grid-cols-4">
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <div className="text-xs font-semibold uppercase tracking-normal text-slate-500">Scanner State</div>
              <div className="mt-2 text-xl font-semibold">{displayStatus.state || "NO_SIGNAL"}</div>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <div className="text-xs font-semibold uppercase tracking-normal text-slate-500">Receiver</div>
              <div className="mt-2 text-xl font-semibold">RTL-SDR</div>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <div className="text-xs font-semibold uppercase tracking-normal text-slate-500">Channels Scanned</div>
              <div className="mt-2 text-xl font-semibold tabular-nums">{status.channels_scanned ?? 0}</div>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <div className="text-xs font-semibold uppercase tracking-normal text-slate-500">Calls Logged</div>
              <div className="mt-2 text-xl font-semibold tabular-nums">{calls.length}</div>
            </div>
          </div>

          <NowListeningCard status={displayStatus} />

          <div className="mt-5 rounded border border-pink-400/20 bg-[#151e2b] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">FM Station ID</h2>
                <p className="mt-1 text-sm text-slate-400">
                  {fmPlayer?.playing && activeFmStation?.now_playing
                    ? activeFmStation.now_playing
                    : fmPlayer?.playing && activeFmStation
                    ? `Playing ${activeFmStation.callsign} - ${activeFmStation.name}`
                    : activeFmStation
                    ? `${activeFmStation.callsign} - ${activeFmStation.name}`
                    : `${fmStations.length} configured Austin FM stations`}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <div className="rounded border border-pink-400/20 bg-pink-500/10 px-3 py-2 text-sm font-semibold text-pink-200">
                  {activeFmStation ? `${activeFmStation.frequency_mhz.toFixed(1)} MHz` : "Station List"}
                </div>
                {fmPlayer?.playing && (
                  <>
                    <button
                      onClick={() => fineTuneFm(Number(fmPlayer.frequency_offset_hz || 0) - 25000)}
                      className="rounded border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-white/5"
                    >
                      -25k
                    </button>
                    <button
                      onClick={() => fineTuneFm(0)}
                      className="rounded border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-white/5"
                    >
                      Center
                    </button>
                    <button
                      onClick={() => fineTuneFm(Number(fmPlayer.frequency_offset_hz || 0) + 25000)}
                      className="rounded border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-white/5"
                    >
                      +25k
                    </button>
                    <button
                      onClick={stopFmPlayer}
                      className="rounded border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-white/5"
                    >
                      Stop FM
                    </button>
                  </>
                )}
              </div>
            </div>
            <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Artist</div>
                <div className="mt-1 font-semibold text-white">{activeFmStation?.artist || activeFmStation?.callsign || "Tune FM channel"}</div>
              </div>
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Song</div>
                <div className="mt-1 font-semibold text-white">{activeFmStation?.song_title || activeFmStation?.name || "Waiting for metadata"}</div>
              </div>
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Metadata</div>
                <div className="mt-1 font-semibold text-white">{activeFmStation?.metadata_status === "ok" ? activeFmStation.metadata_source : activeFmStation?.metadata_status || "Not configured"}</div>
              </div>
            </div>
            {activeFmStation?.metadata_raw && (
              <div className="mt-3 rounded border border-white/10 bg-black/20 p-3 text-xs text-slate-400">
                {activeFmStation.program_name
                  ? `${activeFmStation.program_name}${activeFmStation.program_host ? ` with ${activeFmStation.program_host}` : ""}${activeFmStation.album ? ` - ${activeFmStation.album}` : ""}`
                  : activeFmStation.metadata_raw}
              </div>
            )}
            <div className="mt-3 text-sm text-slate-400">
              {fmPlayer?.playing
                ? `Audio playing through Windows output. Tuned ${((fmPlayer.tuned_frequency_hz || fmPlayer.frequency_hz || 0) / 1_000_000).toFixed(4)} MHz, offset ${Number(fmPlayer.frequency_offset_hz || 0)} Hz, gain ${fmPlayer.gain_used_db ?? "auto"} dB. Signal ${Number(fmPlayer.last_db ?? -99).toFixed(1)} dB, peak ${Number(fmPlayer.peak_db ?? -99).toFixed(1)} dB.`
                : "Click any Austin FM Radio channel in the left panel to tune, play audio, and show station ID."}
            </div>
          </div>

          <ScannerControls
            status={status}
            gain={gain}
            muted={muted}
            onStart={startScanner}
            onStop={stopScanner}
            onScanAllSystems={scanAllSystems}
            onHoldOrResume={holdOrResume}
            onSkip={skipChannel}
            onToggleMute={toggleMute}
            onGain={changeGain}
          />

          <div className="mt-5 rounded border border-triCoreBlue/20 bg-[#151e2b] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">P25 Trunking Decoder</h2>
                <p className="mt-1 text-sm text-slate-400">
                  {p25?.message || "Loading decoder status"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {p25?.running && (
                  <button
                    onClick={stopP25Decoder}
                    className="rounded border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-white/5"
                  >
                    Stop SDR Backend
                  </button>
                )}
                <button
                  onClick={launchTrunkingDecoder}
                  className="rounded border border-triCoreBlue/30 bg-triCoreBlue/10 px-4 py-2 text-sm font-semibold text-triCoreBlue hover:bg-triCoreBlue/20"
                >
                  Start SDR Backend
                </button>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded border border-white/10 bg-black/20 p-3">
              <div>
                <div className="text-xs uppercase tracking-normal text-slate-500">TriCore SDR Runtime</div>
                <div className="mt-1 text-sm font-semibold text-white">
                  {sdrRuntime?.ready ? "Copied and ready" : "Not synced"}
                </div>
                <div className="mt-1 max-w-3xl truncate text-xs text-slate-500">
                  {sdrRuntime?.runtime_root || "tools/tricore-sdr"}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                <span className={sdrRuntime?.tools?.rtl_fm ? "text-triCoreGreen" : "text-red-300"}>RTL</span>
                <span className={sdrRuntime?.tools?.dsdplus ? "text-triCoreGreen" : "text-red-300"}>DSD+</span>
                <span className={sdrRuntime?.tools?.sdrtrunk_launcher ? "text-triCoreGreen" : "text-red-300"}>P25</span>
                <span className={sdrRuntime?.tools?.jmbe ? "text-triCoreGreen" : "text-red-300"}>JMBE</span>
                <button
                  onClick={syncSdrRuntime}
                  className="rounded border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-white/5"
                >
                  Sync Runtime
                </button>
              </div>
            </div>
            <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Selected TG</div>
                <div className="mt-1 font-semibold text-white">
                  {p25?.selected_talkgroup ? `${p25.selected_talkgroup.alpha_tag} (${p25.selected_talkgroup.decimal})` : "Click a GATRRS talkgroup"}
                </div>
              </div>
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Decoder State</div>
                <div className={`mt-1 font-semibold ${p25?.state === "STARTING" ? "animate-pulse text-yellow-400" : p25?.running ? "text-triCoreGreen" : "text-white"}`}>
                  {p25?.running ? p25?.state || "RUNNING" : p25?.external_decoder?.installed ? "SDRTrunk Ready" : "Not Found"}
                </div>
              </div>
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Radio IDs</div>
                <div className="mt-1 font-semibold text-white">
                  {p25?.active_call?.source_radio_id || p25?.active_call?.target_radio_id
                    ? `SRC ${p25?.active_call?.source_radio_id || "?"} / DST ${p25?.active_call?.target_radio_id || "?"}`
                    : "Waiting for SDRTrunk call data"}
                </div>
              </div>
            </div>
            <div className="mt-3 grid gap-3 text-sm md:grid-cols-3">
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Control Channel</div>
                <div className="mt-1 font-semibold text-white">
                  {p25?.preferred_control_channel_hz ? `${(p25.preferred_control_channel_hz / 1_000_000).toFixed(4)} MHz` : "Not configured"}
                </div>
              </div>
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Voice Frequency</div>
                <div className="mt-1 font-semibold text-white">
                  {p25?.active_call?.voice_frequency_hz ? `${(p25.active_call.voice_frequency_hz / 1_000_000).toFixed(4)} MHz` : "Waiting"}
                </div>
              </div>
              <div className="rounded border border-white/10 bg-black/20 p-3">
                <div className="text-xs uppercase tracking-normal text-slate-500">Audio Path</div>
                <div className="mt-1 font-semibold text-white">Hidden SDR Backend</div>
              </div>
            </div>
            {p25?.last_event?.raw && (
              <div className="mt-3 truncate rounded border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-400">
                {p25.last_event.raw}
              </div>
            )}

            {/* Native voice scanner activity */}
            {p25?.voice_scan_active && (
              <div className="mt-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-normal text-triCoreGreen/70">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-triCoreGreen" />
                  GATRRS Voice Scan Active
                  {p25.voice_sweep_stats && (
                    <span className="ml-auto font-normal normal-case text-slate-500">
                      sweep {p25.voice_sweep_stats.sweeps} · {p25.voice_sweep_stats.last_sweep_ms}ms · {p25.voice_sweep_stats.channels} ch
                    </span>
                  )}
                </div>
                {p25.active_voice_channels?.length > 0 ? (
                  <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                    {p25.active_voice_channels.map((ch) => (
                      <div key={ch.frequency_hz} className="flex items-center gap-2 rounded border border-triCoreGreen/25 bg-triCoreGreen/5 px-3 py-2 text-xs">
                        <span className="h-2 w-2 shrink-0 rounded-full bg-triCoreGreen" />
                        <span className="font-mono font-semibold text-triCoreGreen">{ch.frequency_mhz} MHz</span>
                        <span className="ml-auto text-slate-400 tabular-nums">{ch.signal_db} dB</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-500">
                    No P25 voice activity detected — scanning {p25?.voice_sweep_stats?.channels ?? "…"} GATRRS frequencies
                  </div>
                )}
              </div>
            )}
            {p25?.voice_scan_error && (
              <div className="mt-2 rounded border border-red-400/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                Voice scan: {p25.voice_scan_error}
              </div>
            )}
          </div>

          <div className="mt-5 rounded border border-white/10 bg-black/20 p-4 text-sm text-slate-300">
            <strong className="text-white">Status: </strong>{status.message || "Ready"}
          </div>
        </section>
      </main>

      <RecentCallTicker calls={calls} />

      {showAddChannel && (
        <ChannelEditor
          onSave={addChannel}
          onClose={() => setShowAddChannel(false)}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
