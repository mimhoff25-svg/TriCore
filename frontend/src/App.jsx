import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import ChannelEditor from "./components/ChannelEditor";
import NowListeningCard from "./components/NowListeningCard";
import RadioLog from "./components/RadioLog";
import SystemList from "./components/SystemList";

const API_BASE = "http://127.0.0.1:8000";
const DISPATCH_WATCHES = [
  { id: "tcso-david", label: "TCSO DAVID", needles: ["tcso david"] },
  { id: "tcso", label: "TCSO Traffic", needles: ["tcso"], activeOnly: true },
  { id: "fire-dispatch", label: "Fire Dispatch", needles: ["fire dispatch"] },
  { id: "ems-dispatch", label: "EMS Dispatch", needles: ["ems dispatch"] },
];

function findDispatchAlert(displayStatus, p25) {
  const channel = displayStatus?.active_channel;
  const candidates = [
    channel?.id,
    channel?.name,
    channel?.system,
    channel?.department,
    p25?.selected_talkgroup?.id,
    p25?.selected_talkgroup?.alpha_tag,
    p25?.selected_talkgroup?.description,
    p25?.selected_talkgroup?.tag,
    p25?.active_call?.talkgroup?.id,
    p25?.active_call?.talkgroup?.alpha_tag,
    p25?.active_call?.talkgroup?.description,
    p25?.active_call?.talkgroup?.tag,
    p25?.last_event?.raw,
  ]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());
  const activeCandidates = [
    channel?.id,
    channel?.name,
    channel?.system,
    channel?.department,
    p25?.active_call?.talkgroup?.id,
    p25?.active_call?.talkgroup?.alpha_tag,
    p25?.active_call?.talkgroup?.description,
    p25?.active_call?.talkgroup?.tag,
    p25?.last_event?.raw,
  ]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());

  const match = DISPATCH_WATCHES.find((watch) => {
    const haystack = watch.activeOnly ? activeCandidates : candidates;
    return watch.needles.some((needle) => haystack.some((candidate) => candidate.includes(needle)));
  });
  if (!match) return null;

  const source = channel?.name
    || p25?.active_call?.talkgroup?.alpha_tag
    || p25?.selected_talkgroup?.alpha_tag
    || match.label;

  return {
    id: match.id,
    label: match.label,
    source,
    detail: channel?.system
      || p25?.selected_talkgroup?.tag
      || p25?.active_call?.talkgroup?.tag
      || "TriCore live match",
    key: `${match.id}:${channel?.id || p25?.selected_talkgroup?.id || p25?.active_call?.talkgroup?.id || source}`,
  };
}

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
  const [sdrSystem, setSdrSystem]     = useState(null);
  const [activePlaylist, setActivePlaylist] = useState(null);
  const [showAddChannel, setShowAddChannel] = useState(false);
  const [talkgroupRefreshKey, setTalkgroupRefreshKey] = useState(0);
  const [playlistSyncing, setPlaylistSyncing] = useState(false);
  const [playlistSyncInfo, setPlaylistSyncInfo] = useState("");
  const [dispatchAlert, setDispatchAlert] = useState(null);
  const [transcripts, setTranscripts] = useState([]);
  const [transcriptStatus, setTranscriptStatus] = useState({ running: false });
  const modeSwitchSeq = useRef(0);
  const decoderInitStarted = useRef(false);
  const lastDispatchAlertKey = useRef("");

  function beginModeSwitch() {
    modeSwitchSeq.current += 1;
    return modeSwitchSeq.current;
  }

  function isLatestModeSwitch(seq) {
    return seq === modeSwitchSeq.current;
  }

  function inferTalkgroupDecimal(channel) {
    const raw = channel?.talkgroup_decimal ?? channel?.tgid ?? channel?.decimal;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function isP25Channel(channel) {
    if (!channel) return false;
    const modulation = String(channel.modulation || "").toLowerCase();
    const category = String(channel.category || "").toLowerCase();
    const system = String(channel.system || "").toLowerCase();
    const serviceType = String(channel.service_type || "").toLowerCase();
    return modulation === "p25"
      || category.includes("trunk")
      || system.includes("gatrrs")
      || serviceType === "p25"
      || inferTalkgroupDecimal(channel) !== null;
  }

  function isFmChannel(channel) {
    const modulation = String(channel?.modulation || "").toLowerCase();
    const category = String(channel?.category || "").toLowerCase();
    const serviceType = String(channel?.service_type || "").toLowerCase();
    return serviceType === "fm_radio" || category === "fm_radio" || modulation === "wfm";
  }

  function isAmOrSwChannel(channel) {
    const modulation = String(channel?.modulation || "").toLowerCase();
    const category = String(channel?.category || "").toLowerCase();
    const serviceType = String(channel?.service_type || "").toLowerCase();
    const name = String(channel?.name || "").toLowerCase();
    const isAm = serviceType === "am_radio" || category === "am_radio" || modulation === "am";
    const isSw = serviceType === "shortwave" || category === "shortwave" || category === "sw" || modulation === "usb" || modulation === "lsb" || name.includes("shortwave");
    return isAm || isSw;
  }

  function isBroadcastLikeChannel(channel) {
    return isFmChannel(channel) || isAmOrSwChannel(channel);
  }

  async function stopFmIfPlaying() {
    try {
      const player = await api("/api/fm/stop", "POST");
      setFmPlayer(player);
    } catch {
      // Keep mode switching resilient if FM stop endpoint is unavailable.
    }
  }

  async function stopP25IfRunning() {
    try {
      setP25(await api("/api/p25/stop", "POST"));
    } catch {
      // Decoder may already be stopped.
    }
  }

  async function prepareBuiltInDecoder() {
    if (!sdrRuntime?.ready) {
      await syncSdrRuntime();
    }
    if (talkgroupRefreshKey === 0) {
      await syncP25Playlist();
    }
    return await api("/api/p25/start", "POST");
  }

  async function activateTalkgroup(talkgroup, playlistName = null, playlistId = null) {
    const seq = beginModeSwitch();
    try {
      await stopFmIfPlaying().catch(() => null);
      await api("/api/scanner/stop", "POST").catch(() => null);
      const started = await prepareBuiltInDecoder();
      if (!isLatestModeSwitch(seq)) return;
      setP25(started);
      const selected = await api("/api/p25/select-talkgroup", "POST", { decimal: talkgroup.decimal });
      if (!isLatestModeSwitch(seq)) return;
      setActivePlaylist({ id: playlistId || `tg-${talkgroup.decimal}`, name: playlistName || talkgroup.alpha_tag });
      setP25(selected);
      refreshStatus().catch(() => null);
    } catch (error) {
      if (!isLatestModeSwitch(seq)) return;
      setP25((current) => ({ ...current, message: error.message || "Talkgroup select failed" }));
    }
  }

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

  async function refreshSdrSystem() {
    setSdrSystem(await api("/api/sdr/system"));
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
    const seq = beginModeSwitch();
    setActivePlaylist(null);
    setDisabledSystems(new Set());
    await stopFmIfPlaying().catch(() => null);
    await stopP25IfRunning().catch(() => null);
    await api("/api/scanner/channel-filter", "POST", { channel_ids: null });
    await api("/api/scanner/group-filter", "POST", { systems: null });
    const nextStatus = await api("/api/scanner/start", "POST");
    if (!isLatestModeSwitch(seq)) return;
    setStatus(nextStatus);
  }

  async function stopScanner() {
    setStatus(await api("/api/scanner/stop", "POST"));
  }

  async function scanSystem(systemName) {
    const seq = beginModeSwitch();
    const systemChannels = channels.filter((channel) => channel.system === systemName);
    if (systemChannels.length && systemChannels.every((channel) => isBroadcastLikeChannel(channel))) {
      await tuneToChannel(systemChannels[0]);
      setActivePlaylist({ id: `system-${systemName}`, name: systemName });
      return;
    }
    if (systemChannels.length && systemChannels.every((channel) => channel.service_type === "railroad" || channel.category === "railroad")) {
      await tuneToChannel(systemChannels[0]);
      setActivePlaylist({ id: `system-${systemName}`, name: systemName });
      return;
    }
    const allNames = [...new Set(channels.map((c) => c.system))];
    const nextDisabled = new Set(allNames.filter((name) => name !== systemName));
    setDisabledSystems(nextDisabled);
    setActivePlaylist({ id: `system-${systemName}`, name: systemName });
    await stopFmIfPlaying().catch(() => null);
    await stopP25IfRunning().catch(() => null);
    await api("/api/scanner/channel-filter", "POST", { channel_ids: null });
    await api("/api/scanner/group-filter", "POST", { systems: [systemName] });
    const nextStatus = await api("/api/scanner/start", "POST");
    if (!isLatestModeSwitch(seq)) return;
    setStatus(nextStatus);
  }

  async function scanAllSystems() {
    const seq = beginModeSwitch();
    setDisabledSystems(new Set());
    setActivePlaylist(null);
    await stopFmIfPlaying().catch(() => null);
    await stopP25IfRunning().catch(() => null);
    await api("/api/scanner/channel-filter", "POST", { channel_ids: null });
    await api("/api/scanner/group-filter", "POST", { systems: null });
    const nextStatus = await api("/api/scanner/start", "POST");
    if (!isLatestModeSwitch(seq)) return;
    setStatus(nextStatus);
  }

  async function scanPlaylist(playlist) {
    const seq = beginModeSwitch();
    const playlistChannels = channels.filter((channel) => playlist.channelIds.includes(channel.id));
    const directTuneIds = new Set(["broadcast-fm", "broadcast-am", "shortwave", "mode-fm", "mode-am", "mode-sw"]);
    if (playlistChannels.length && (directTuneIds.has(playlist.id) || playlistChannels.every((channel) => isBroadcastLikeChannel(channel)))) {
      await tuneToChannel(playlistChannels[0]);
      setActivePlaylist({ id: playlist.id, name: playlist.name });
      return;
    }
    if (playlist.id === "railroad" && playlistChannels.length) {
      await tuneToChannel(playlistChannels[0]);
      setActivePlaylist({ id: playlist.id, name: playlist.name });
      return;
    }
    const allNames = [...new Set(channels.map((c) => c.system))];
    const enabled = new Set(playlist.systemNames || []);
    setDisabledSystems(new Set(allNames.filter((name) => !enabled.has(name))));
    setActivePlaylist({ id: playlist.id, name: playlist.name });
    await stopFmIfPlaying().catch(() => null);
    await stopP25IfRunning().catch(() => null);
    await api("/api/scanner/group-filter", "POST", { systems: null });
    await api("/api/scanner/channel-filter", "POST", { channel_ids: playlist.channelIds });
    const nextStatus = await api("/api/scanner/start", "POST");
    if (!isLatestModeSwitch(seq)) return;
    setStatus(nextStatus);
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

  async function holdCurrentChannelOrFallback(fallbackStatus) {
    try {
      return await api("/api/scanner/hold", "POST");
    } catch {
      return fallbackStatus;
    }
  }

  // ── Individual channel tune ────────────────────────────────────────────────

  async function tuneToChannel(channel) {
    const seq = beginModeSwitch();
    try {
      if (isP25Channel(channel)) {
        const decimal = inferTalkgroupDecimal(channel);
        if (decimal == null) {
          setStatus((current) => ({ ...current, message: "P25 channel is missing a talkgroup decimal." }));
          return;
        }
        await activateTalkgroup({
          decimal,
          alpha_tag: channel.name || `Talkgroup ${decimal}`,
        }, channel.name || channel.system || "P25 Talkgroup");
        return;
      }

      if (isFmChannel(channel)) {
        await api("/api/scanner/stop", "POST").catch(() => null);
        await stopP25IfRunning().catch(() => null);
        const player = await api("/api/fm/play", "POST", { channel_id: channel.id });
        if (!isLatestModeSwitch(seq)) return;
        setFmPlayer(player);
        setStatus(await api("/api/status"));
      } else if (isAmOrSwChannel(channel)) {
        await stopFmIfPlaying().catch(() => null);
        await stopP25IfRunning().catch(() => null);
        const nextStatus = await api("/api/scanner/tune", "POST", { channel_id: channel.id });
        const heldStatus = await holdCurrentChannelOrFallback(nextStatus);
        if (!isLatestModeSwitch(seq)) return;
        setStatus({
          ...heldStatus,
          message: `${channel.name} locked.`,
        });
      } else {
        await stopFmIfPlaying().catch(() => null);
        await stopP25IfRunning().catch(() => null);
        const nextStatus = await api("/api/scanner/tune", "POST", { channel_id: channel.id });
        const heldStatus = await holdCurrentChannelOrFallback(nextStatus);
        if (!isLatestModeSwitch(seq)) return;
        setStatus(heldStatus);
      }
    } catch (error) {
      if (!isLatestModeSwitch(seq)) return;
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
      setP25(await prepareBuiltInDecoder());
    } catch (error) {
      setP25((current) => ({ ...current, message: error.message || "Built-in decoder start failed" }));
    }
  }

  async function selectTalkgroup(talkgroup) {
    await activateTalkgroup(talkgroup);
  }

  async function scanTalkgroupDepartment(name, list, playlistId = null) {
    const talkgroups = Array.isArray(list) ? list : [];
    if (!talkgroups.length) return;
    const nextTalkgroup = talkgroups.find((tg) => !tg.encrypted) || talkgroups[0];
    await activateTalkgroup(nextTalkgroup, name, playlistId);
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
      refreshSdrSystem().catch(() => null);
    } catch (error) {
      setSdrRuntime((current) => ({ ...current, ready: false, message: error.message || "Runtime sync failed" }));
    }
  }

  async function syncP25Playlist() {
    setPlaylistSyncing(true);
    try {
      const result = await api("/api/p25/sync-playlist", "POST");
      setTalkgroupRefreshKey((current) => current + 1);
      setPlaylistSyncInfo(
        result.updated
          ? "Imported trunking playlist into TriCore."
          : "Trunking playlist already in sync."
      );
      refreshP25().catch(() => null);
    } catch (error) {
      setPlaylistSyncInfo(error.message || "Playlist sync failed.");
    } finally {
      setPlaylistSyncing(false);
    }
  }

  async function refreshTranscripts() {
    const [entries, ts] = await Promise.all([
      api("/api/transcripts"),
      api("/api/transcripts/status"),
    ]);
    setTranscripts(entries);
    setTranscriptStatus(ts);
  }

  async function startTranscription() {
    const result = await api("/api/transcripts/start", "POST");
    if (!result.ok) {
      setTranscriptStatus((current) => ({ ...current, error: result.error }));
    } else {
      setTranscriptStatus((current) => ({ ...current, running: true, error: null }));
    }
  }

  async function stopTranscription() {
    await api("/api/transcripts/stop", "POST");
    setTranscriptStatus((current) => ({ ...current, running: false }));
  }

  async function clearTranscripts() {
    await api("/api/transcripts/clear", "POST");
    setTranscripts([]);
  }

  async function initializeBuiltInDecoder() {
    if (decoderInitStarted.current) return;
    decoderInitStarted.current = true;

    await syncSdrRuntime();
    await syncP25Playlist();

    try {
      setP25(await prepareBuiltInDecoder());
    } catch (error) {
      setP25((current) => ({ ...current, message: error.message || "Built-in decoder startup failed" }));
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
    refreshSdrSystem().catch(() => null);
    refreshFmStations().catch(() => null);
    refreshFmPlayer().catch(() => null);
    refreshTranscripts().catch(() => null);
    initializeBuiltInDecoder().catch(() => null);
    const statusTimer = setInterval(() => refreshStatus().catch(() => null), 1000);
    const callsTimer  = setInterval(() => refreshCalls().catch(() => null), 5000);
    const p25Timer    = setInterval(() => refreshP25().catch(() => null), 1500);
    const systemTimer = setInterval(() => refreshSdrSystem().catch(() => null), 5000);
    const fmTimer         = setInterval(() => refreshFmPlayer().catch(() => null), 1000);
    const transcriptTimer = setInterval(() => refreshTranscripts().catch(() => null), 3000);
    const clockTimer      = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => {
      clearInterval(statusTimer);
      clearInterval(callsTimer);
      clearInterval(p25Timer);
      clearInterval(systemTimer);
      clearInterval(fmTimer);
      clearInterval(transcriptTimer);
      clearInterval(clockTimer);
    };
  }, []);

  const scanning = status.state === "SCANNING" || status.state === "RECEIVING_CALL" || status.state === "HOLDING_CHANNEL";
  const activeFmStation = fmPlayer?.station || fmStations.find((station) => station.id === status.active_channel?.id);
  const activeFmFrequencyMhz = Number(activeFmStation?.frequency_mhz);
  const p25ActiveTalkgroup = p25?.active_call?.talkgroup && typeof p25.active_call.talkgroup === "object"
    ? p25.active_call.talkgroup
    : null;
  const p25EventTalkgroup = p25?.last_event?.talkgroup && typeof p25.last_event.talkgroup === "object"
    ? p25.last_event.talkgroup
    : null;
  const p25TrackingTalkgroup = p25?.selected_talkgroup || null;
  const p25SelectedTalkgroup = p25ActiveTalkgroup || p25EventTalkgroup || p25TrackingTalkgroup;
  const p25PrimaryRadioId = p25?.active_call?.source_radio_id
    || p25?.active_call?.target_radio_id
    || p25?.last_event?.source_radio_id
    || p25?.last_event?.target_radio_id
    || null;
  const p25TargetRadioId = p25?.active_call?.target_radio_id
    || p25?.last_event?.target_radio_id
    || null;
  const p25DisplayChannel = p25?.running && (p25SelectedTalkgroup || p25?.active_call)
    ? {
        id: `tg-${p25SelectedTalkgroup?.decimal || p25.active_call?.talkgroup_decimal || "active"}`,
        name: p25ActiveTalkgroup?.alpha_tag || p25EventTalkgroup?.alpha_tag || p25?.tracking_label || p25SelectedTalkgroup?.alpha_tag || `TG ${p25.active_call?.talkgroup_decimal || "Active"}`,
        frequency_hz: p25.active_call?.voice_frequency_hz || p25.preferred_control_channel_hz,
        system: "GATRRS",
        department: p25SelectedTalkgroup?.tag || p25SelectedTalkgroup?.description || "Travis County",
        tracking_label: p25?.tracking_label,
        tracking_count: p25?.tracked_talkgroup_count,
        selected_talkgroup: p25TrackingTalkgroup?.alpha_tag,
        primary_radio_id: p25PrimaryRadioId,
        target_radio_id: p25TargetRadioId,
        service_type: p25SelectedTalkgroup?.service_type || "custom",
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
  const matchedDispatch = findDispatchAlert(displayStatus, p25);

  useEffect(() => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    if (window.Notification.permission === "default") {
      window.Notification.requestPermission().catch(() => null);
    }
  }, []);

  useEffect(() => {
    if (!matchedDispatch) return;
    if (matchedDispatch.key === lastDispatchAlertKey.current) return;

    lastDispatchAlertKey.current = matchedDispatch.key;
    setDispatchAlert({
      ...matchedDispatch,
      heardAt: new Date().toLocaleTimeString(),
    });

    if (typeof window === "undefined" || !("Notification" in window)) return;
    if (window.Notification.permission !== "granted") return;

    try {
      new window.Notification(`TriCore heard ${matchedDispatch.label}`, {
        body: `${matchedDispatch.source} on ${matchedDispatch.detail}`,
        silent: false,
      });
    } catch {
      // Ignore notification failures and keep the in-app alert.
    }
  }, [matchedDispatch]);

  useEffect(() => {
    if (!dispatchAlert) return;
    const timer = setTimeout(() => {
      setDispatchAlert((current) => (current?.key === dispatchAlert.key ? null : current));
    }, 15000);
    return () => clearTimeout(timer);
  }, [dispatchAlert]);

  return (
    <div className="min-h-screen bg-[#091119] text-white">
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-8%] top-[-5%] h-72 w-72 rounded-full bg-triCoreBlue/10 blur-3xl" />
        <div className="absolute right-[-6%] top-[14%] h-64 w-64 rounded-full bg-triCoreAmber/10 blur-3xl" />
        <div className="absolute bottom-[-12%] left-[26%] h-80 w-80 rounded-full bg-triCoreGreen/10 blur-3xl" />
      </div>

      <main className="flex min-h-screen flex-col lg:flex-row">
        <SystemList
          channels={channels}
          disabledSystems={disabledSystems}
          onToggleSystem={toggleSystem}
          onTuneChannel={tuneToChannel}
          onScanSystem={scanSystem}
          onScanAllSystems={scanAllSystems}
          onScanPlaylist={scanPlaylist}
          onScanTalkgroupGroup={scanTalkgroupDepartment}
          onSelectTalkgroup={selectTalkgroup}
          activeChannel={displayStatus.active_channel}
          activePlaylist={activePlaylist}
          selectedTalkgroup={p25?.selected_talkgroup}
          talkgroupRefreshKey={talkgroupRefreshKey}
        />

        <section className="relative flex-1 overflow-hidden">
          <div className="relative flex min-h-screen items-center justify-center p-5 lg:p-7">
            <div className="w-full max-w-6xl rounded-[32px] border border-white/10 bg-[#09111a]/65 p-4 shadow-[0_24px_90px_rgba(0,0,0,0.35)] backdrop-blur-xl lg:p-6">
              <NowListeningCard
                status={displayStatus}
                dispatchAlert={dispatchAlert}
                systemProfile={sdrSystem}
                runtime={sdrRuntime}
              />
              <div className="mt-4">
                <RadioLog
                  transcripts={transcripts}
                  transcriptStatus={transcriptStatus}
                  onStart={startTranscription}
                  onStop={stopTranscription}
                  onClear={clearTranscripts}
                />
              </div>
            </div>
          </div>
        </section>
      </main>

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
