import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import NowListeningCard from "./components/NowListeningCard";
import RadioLog from "./components/RadioLog";
import ActiveScanChannelCard from "./components/scanner/ActiveScanChannelCard";
import ReceiverPanel from "./components/scanner/ReceiverPanel";
import ScanFoldersPanel from "./components/scanner/ScanFoldersPanel";
import ScanModePanel from "./components/scanner/ScanModePanel";
import ScannerKeypad from "./components/scanner/ScannerKeypad";
import SearchPanel from "./components/scanner/SearchPanel";
import TopStatusBar from "./components/scanner/TopStatusBar";

const API_BASE = import.meta.env.VITE_TRICORE_API_BASE || "http://127.0.0.1:8000";

const INITIAL_STATUS = {
  state: "stopped",
  is_scanning: false,
  is_paused: false,
  is_holding: false,
  is_muted: false,
  current_channel: null,
  active_channel: null,
  current_frequency_hz: null,
  signal_level: -100,
  receiver_mode: "Demo",
  simulated: true,
  squelch_db: -65,
  gain_db: null,
  selected_bank_ids: [],
  message: "Loading...",
  error_message: null,
  scanner_state: "Stopped",
};

async function api(path, method = "GET", body = undefined) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`${API_BASE}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed with ${response.status}`);
  }
  return data;
}

function App() {
  const [status, setStatus] = useState(INITIAL_STATUS);
  const [receiver, setReceiver] = useState(null);
  const [audioDevices, setAudioDevices] = useState([]);
  const [selectedAudioDeviceId, setSelectedAudioDeviceId] = useState("default");
  const [banks, setBanks] = useState([]);
  const [channels, setChannels] = useState([]);
  const [talkgroups, setTalkgroups] = useState([]);
  const [p25Status, setP25Status] = useState(null);
  const [bandplans, setBandplans] = useState([]);
  const [transcripts, setTranscripts] = useState([]);
  const [transcriptStatus, setTranscriptStatus] = useState({ running: false, error: null, transcript_count: 0 });
  const [time, setTime] = useState(new Date().toLocaleTimeString());
  const [gain, setGain] = useState("auto");
  const [squelch, setSquelch] = useState(-65);
  const [selectedRange, setSelectedRange] = useState("");
  const [manualFrequency, setManualFrequency] = useState("");
  const [manualModulation, setManualModulation] = useState("nfm");
  const [audioMonitoringEnabled, setAudioMonitoringEnabled] = useState(true);
  const [audioVolume, setAudioVolume] = useState(() => {
    const saved = Number(localStorage.getItem("tricore.audioVolume"));
    return Number.isFinite(saved) && saved >= 0.05 ? Math.min(1, saved) : 0.85;
  });
  const [audioLevel, setAudioLevel] = useState(0);
  const [audioStreamVersion, setAudioStreamVersion] = useState(0);
  const [audioMonitorError, setAudioMonitorError] = useState("");
  const audioRef = useRef(null);
  const audioStreamUrlRef = useRef("");
  const audioContextRef = useRef(null);
  const audioAnalyserRef = useRef(null);
  const audioSourceRef = useRef(null);
  const audioMeterFrameRef = useRef(null);
  const audioFadeTimerRef = useRef(null);
  const audioStopTimerRef = useRef(null);
  const commandSequenceRef = useRef(0);

  async function refreshStatus() {
    const nextStatus = await api("/api/scanner/status");
    setStatus(nextStatus);
    setGain(nextStatus.gain_db == null ? "auto" : String(nextStatus.gain_db));
    setSquelch(Number(nextStatus.squelch_db ?? -65));
    return nextStatus;
  }

  async function refreshReceiver() {
    setReceiver(await api("/api/receiver/status"));
  }

  async function refreshBanks() {
    setBanks(await api("/api/banks"));
  }

  async function refreshChannels() {
    setChannels(await api("/api/channels"));
  }

  async function refreshTalkgroups() {
    setTalkgroups(await api("/api/trunked/talkgroups?include_encrypted=true"));
  }

  async function refreshP25Status() {
    const payload = await api("/api/p25/status");
    setP25Status(payload);
    return payload;
  }

  async function refreshBandplans() {
    const ranges = await api("/api/bandplans");
    setBandplans(ranges);
    setSelectedRange((current) => current || ranges[0]?.id || "");
  }

  async function refreshTranscriber() {
    const payload = await api("/api/transcriber/status");
    setTranscriptStatus(payload);
    setTranscripts(payload.transcripts || []);
    return payload;
  }

  function activePlaybackChannel(nextStatus = status) {
    return nextStatus?.current_channel || nextStatus?.active_channel || null;
  }

  function p25AudioBlockReason(nextStatus = status, nextP25Status = p25Status, options = {}) {
    const { allowManagedDsdPlus = false } = options;
    const playbackChannel = activePlaybackChannel(nextStatus);
    if (String(playbackChannel?.modulation || "").toLowerCase() !== "p25_placeholder") {
      return "";
    }

    const runtimeEngine = String(
      nextP25Status?.decoder?.runtime?.engine ||
      nextStatus?.decoder?.runtime?.engine ||
      "",
    ).toLowerCase();

    if (runtimeEngine === "sdrtrunk") {
      return String(
        nextP25Status?.message ||
        nextStatus?.decoder?.message ||
        nextStatus?.message ||
        "SDRTrunk fallback is handling P25 audio directly. In-app live audio and transcription are unavailable in fallback mode.",
      ).trim();
    }

    const runtimeHealth = String(
      nextP25Status?.decoder?.runtime?.health ||
      nextStatus?.decoder?.runtime?.health ||
      nextP25Status?.sync_state ||
      nextStatus?.decoder?.sync_state ||
      "",
    ).toLowerCase();

    if (runtimeHealth !== "no_tuner" && runtimeHealth !== "driver_conflict" && runtimeHealth !== "error") {
      const directAudioOutput = String(
        nextP25Status?.decoder?.runtime?.audio_output_name ||
        nextStatus?.decoder?.runtime?.audio_output_name ||
        "",
      ).trim();
      if (!directAudioOutput || allowManagedDsdPlus) {
        return "";
      }
      return `P25 audio is already playing directly through DSDPlus on ${directAudioOutput}. Browser live audio is disabled for P25 to prevent repeated audio.`;
    }

    return String(
      nextP25Status?.message ||
      nextStatus?.decoder?.message ||
      nextStatus?.message ||
      "Managed P25 audio is unavailable until the RTL-SDR tuner is accessible.",
    ).trim();
  }

  async function runScannerCommand(path, body = undefined, options = {}) {
    const sequence = commandSequenceRef.current + 1;
    commandSequenceRef.current = sequence;
    if (audioRef.current) {
      fadeAudioTo(0, 90);
    }
    const nextStatus = await api(path, "POST", body);
    if (sequence !== commandSequenceRef.current) {
      return nextStatus;
    }
    setStatus(nextStatus);
    setGain(nextStatus.gain_db == null ? "auto" : String(nextStatus.gain_db));
    setSquelch(Number(nextStatus.squelch_db ?? -65));
    setAudioStreamVersion((version) => version + 1);
    refreshReceiver().catch(() => null);
    if (options.retuneTranscriber) {
      await retuneTranscriberToActiveChannel(nextStatus);
    }
    return nextStatus;
  }

  async function retuneTranscriberToActiveChannel(expectedStatus = null) {
    const current = await api("/api/transcriber/status");
    const expectedFrequency = Number(expectedStatus?.current_frequency_hz || 0);
    const expectedModulation = String(
      expectedStatus?.current_channel?.modulation ||
      expectedStatus?.active_channel?.modulation ||
      "",
    ).toLowerCase();

    if (
      current.running &&
      Number(current.current_frequency_hz || 0) === expectedFrequency &&
      (!expectedModulation || String(current.current_modulation || "").toLowerCase() === expectedModulation)
    ) {
      setTranscriptStatus(current);
      setTranscripts(current.transcripts || []);
      return current;
    }

    if (!current.running) {
      setTranscriptStatus(current);
      setTranscripts(current.transcripts || []);
      return current;
    }

    await api("/api/transcriber/stop", "POST");
    const payload = await api("/api/transcriber/start", "POST");
    setTranscriptStatus(payload);
    setTranscripts(payload.transcripts || []);
    setAudioStreamVersion((version) => version + 1);
    return payload;
  }

  async function refreshAudioDevices() {
    if (!navigator?.mediaDevices?.enumerateDevices) {
      setAudioDevices([]);
      updateAudioOutputDevice("default");
      return;
    }
    const devices = await navigator.mediaDevices.enumerateDevices();
    const outputs = devices.filter((device) => device.kind === "audiooutput");
    setAudioDevices(outputs);
    setSelectedAudioDeviceId((current) => {
      if (!current || current === "default") {
        localStorage.setItem("tricore.audioOutputDevice", "default");
        return "default";
      }
      const stillAvailable = outputs.some((device) => device.deviceId === current);
      if (!stillAvailable) {
        localStorage.setItem("tricore.audioOutputDevice", "default");
        return "default";
      }
      return current;
    });
  }

  function updateAudioOutputDevice(deviceId) {
    setSelectedAudioDeviceId(deviceId);
    localStorage.setItem("tricore.audioOutputDevice", deviceId);
  }

  function updateAudioMonitoringEnabled(enabled) {
    setAudioMonitoringEnabled(enabled);
    localStorage.setItem("tricore.audioMonitoringEnabled", enabled ? "1" : "0");
    if (enabled) {
      playLiveAudio();
    } else {
      api("/api/audio/stop", "POST").catch(() => null);
    }
  }

  function updateAudioVolume(value) {
    const nextVolume = Math.min(1, Math.max(0, Number(value)));
    setAudioVolume(nextVolume);
    localStorage.setItem("tricore.audioVolume", String(nextVolume));
    if (audioRef.current) {
      audioRef.current.volume = nextVolume;
    }
  }

  function enableBrowserAudioForP25() {
    const nextVolume = audioVolume >= 0.05 ? audioVolume : 0.85;
    if (nextVolume !== audioVolume) {
      setAudioVolume(nextVolume);
      localStorage.setItem("tricore.audioVolume", String(nextVolume));
    }
    setAudioMonitoringEnabled(true);
    localStorage.setItem("tricore.audioMonitoringEnabled", "1");
    if (audioRef.current) {
      audioRef.current.muted = false;
      audioRef.current.volume = nextVolume;
    }
    setAudioStreamVersion((version) => version + 1);
  }

  async function playLiveAudio() {
    const audio = audioRef.current;
    if (!audio) return;

    const isP25 = String(activePlaybackChannel()?.modulation || "").toLowerCase() === "p25_placeholder";

    const blockReason = p25AudioBlockReason(status, p25Status, { allowManagedDsdPlus: true });
    if (blockReason) {
      setAudioMonitorError(blockReason);
      return;
    }

    if (isP25 && !transcriptStatus.running) {
      try {
        const started = await api("/api/transcriber/start", "POST");
        setTranscriptStatus(started);
        setTranscripts(started.transcripts || []);
      } catch (_err) {
        // best-effort; audio stream will show error if transcriber is unavailable
      }
    }

    const nextVolume = audioVolume >= 0.05 ? audioVolume : 0.85;
    if (nextVolume !== audioVolume) {
      setAudioVolume(nextVolume);
      localStorage.setItem("tricore.audioVolume", String(nextVolume));
    }

    setAudioMonitoringEnabled(true);
    localStorage.setItem("tricore.audioMonitoringEnabled", "1");
    audio.muted = false;
    audio.volume = nextVolume;
    setAudioStreamVersion((version) => version + 1);
    await audioContextRef.current?.resume?.().catch(() => null);
    await audio.play().catch((error) => {
      setAudioMonitorError(`Click Play Audio again: ${error?.message || error}`);
    });
  }

  function handleAudioMonitorError() {
    setAudioMonitorError("Live audio stream unavailable. Check RTL-SDR device access and receiver status.");
  }

  function fadeAudioTo(targetVolume, durationMs = 180) {
    const audio = audioRef.current;
    if (!audio) return;

    if (audioFadeTimerRef.current) {
      window.clearInterval(audioFadeTimerRef.current);
    }

    const target = Math.min(1, Math.max(0, Number(targetVolume)));
    const start = Number(audio.volume || 0);
    const startedAt = performance.now();

    audioFadeTimerRef.current = window.setInterval(() => {
      const progress = Math.min(1, (performance.now() - startedAt) / durationMs);
      audio.volume = start + ((target - start) * progress);
      if (progress >= 1) {
        window.clearInterval(audioFadeTimerRef.current);
        audioFadeTimerRef.current = null;
      }
    }, 16);
  }

  async function enableBank(bankId) {
    await api(`/api/banks/${bankId}/enable`, "POST");
    await refreshBanks();
    await refreshStatus();
  }

  async function disableBank(bankId) {
    await api(`/api/banks/${bankId}/disable`, "POST");
    await refreshBanks();
    await refreshStatus();
  }

  async function setScanSelection(node, enabled) {
    const channelIds = Array.isArray(node?.channelIds) ? node.channelIds : [];
    const talkgroupDecimals = Array.isArray(node?.talkgroupDecimals) ? node.talkgroupDecimals : [];
    if (!channelIds.length && !talkgroupDecimals.length) {
      return;
    }
    const channelIdSet = new Set(channelIds);
    const talkgroupDecimalSet = new Set(talkgroupDecimals.map((value) => Number(value)));
    setChannels((current) => current.map((channel) => (
      channelIdSet.has(channel.id)
        ? { ...channel, scan_enabled: enabled }
        : channel
    )));
    setTalkgroups((current) => current.map((talkgroup) => (
      talkgroupDecimalSet.has(Number(talkgroup.decimal))
        ? { ...talkgroup, scan_enabled: enabled }
        : talkgroup
    )));

    const nextStatus = await api("/api/scan-selection", "POST", {
      enabled,
      channel_ids: channelIds,
      talkgroup_decimals: talkgroupDecimals,
    });
    setStatus(nextStatus);
    await Promise.all([
      refreshChannels().catch(() => null),
      refreshTalkgroups().catch(() => null),
      refreshReceiver().catch(() => null),
    ]);
  }

  async function changeGain(value) {
    setGain(value);
    await runScannerCommand("/api/scanner/gain", {
      gain_db: value === "auto" ? null : Number(value),
    });
  }

  async function changeSquelch(value) {
    setSquelch(value);
    await runScannerCommand("/api/scanner/squelch", { squelch_db: value });
  }

  async function changeReceiverMode(simulated) {
    commandSequenceRef.current += 1;
    await api("/api/receiver/mode", "POST", { simulated });
    setAudioStreamVersion((version) => version + 1);
    await refreshReceiver();
    await refreshStatus();
  }

  async function manualTune() {
    const mhz = Number(manualFrequency);
    if (!Number.isFinite(mhz) || mhz <= 0) return;
    await runScannerCommand("/api/scanner/manual-tune", {
      frequency_mhz: mhz,
      modulation: manualModulation,
      name: "Manual Tune",
    }, { retuneTranscriber: true });
  }

  async function startSearch(rangeId = selectedRange) {
    if (!rangeId) return;
    setSelectedRange(rangeId);
    await runScannerCommand("/api/scanner/search/start", { range_id: rangeId }, { retuneTranscriber: true });
  }

  async function tuneChannel(channelId) {
    await runScannerCommand("/api/scanner/tune", { channel_id: channelId }, { retuneTranscriber: true });
    refreshP25Status().catch(() => null);
  }

  async function lockOnDisplayedChannel() {
    const lockedChannel = status.current_channel || status.active_channel;
    if (!lockedChannel || lockedChannel.unavailable || lockedChannel.encrypted) {
      return;
    }

    const liveTalkgroupDecimal = Number(
      status?.decoder?.talkgroup_decimal || p25Status?.talkgroup_decimal || 0,
    );
    const selectedTalkgroupDecimal = Number(lockedChannel.p25_talkgroup_decimal || 0);
    const talkgroupDecimal = liveTalkgroupDecimal > 0 ? liveTalkgroupDecimal : selectedTalkgroupDecimal;

    if (talkgroupDecimal > 0) {
      await selectTalkgroup({
        decimal: talkgroupDecimal,
        encrypted: Boolean(lockedChannel.encrypted),
      });
      return;
    }

    if (lockedChannel.id) {
      await tuneChannel(lockedChannel.id);
    }
  }

  async function selectTalkgroup(talkgroup) {
    if (!talkgroup || talkgroup.encrypted) {
      setAudioMonitorError("That GATRRS talkgroup is encrypted or unavailable.");
      return;
    }
    commandSequenceRef.current += 1;
    if (audioRef.current) {
      fadeAudioTo(0, 90);
    }
    try {
      const payload = await api("/api/p25/select-talkgroup", "POST", { decimal: Number(talkgroup.decimal) });
      setP25Status(payload);
      const nextStatus = await refreshStatus();
      await refreshReceiver();
      const nextP25Status = await refreshP25Status().catch(() => payload);
      const blockReason = p25AudioBlockReason(nextStatus, nextP25Status, { allowManagedDsdPlus: true });
      if (blockReason) {
        await refreshTranscriber().catch(() => null);
        setAudioMonitorError(blockReason);
        return;
      }
      const started = await api("/api/transcriber/start", "POST");
      setTranscriptStatus(started);
      setTranscripts(started.transcripts || []);
      setAudioMonitorError("");
      if (String(started.current_modulation || "").toLowerCase() === "p25_placeholder") {
        enableBrowserAudioForP25();
      }
      setAudioStreamVersion((v) => v + 1);
    } catch (error) {
      setAudioMonitorError(String(error?.message || error));
    }
  }

  async function startTranscriber() {
    if (String(activePlaybackChannel()?.modulation || "").toLowerCase() === "p25_placeholder") {
      const nextStatus = await refreshStatus().catch(() => status);
      const nextP25Status = await refreshP25Status().catch(() => p25Status);
      const blockReason = p25AudioBlockReason(nextStatus, nextP25Status, { allowManagedDsdPlus: true });
      if (blockReason) {
        await refreshTranscriber().catch(() => null);
        setAudioMonitorError(blockReason);
        return;
      }
    }

    const payload = await api("/api/transcriber/start", "POST");
    setTranscriptStatus(payload);
    setTranscripts(payload.transcripts || []);
    setAudioMonitorError("");
    if (String(payload.current_modulation || "").toLowerCase() === "p25_placeholder") {
      enableBrowserAudioForP25();
    }
  }

  async function stopTranscriber() {
    const payload = await api("/api/transcriber/stop", "POST");
    setTranscriptStatus(payload);
    setTranscripts(payload.transcripts || []);
  }

  async function clearTranscripts() {
    const payload = await api("/api/transcriber/clear", "POST");
    setTranscriptStatus(payload);
    setTranscripts(payload.transcripts || []);
  }

  useEffect(() => {
    refreshStatus()
      .then((initialStatus) => {
        if (initialStatus.state === "stopped" || initialStatus.state === "error") {
          api("/api/scanner/start", "POST")
            .then((started) => setStatus(started))
            .catch(() => null);
        }
      })
      .catch(() => setStatus({
        ...INITIAL_STATUS,
        state: "error",
        scanner_state: "Error",
        error_message: "Backend offline",
        message: "Backend offline",
      }));
    refreshReceiver().catch(() => null);
    refreshBanks().catch(() => null);
    refreshChannels().catch(() => null);
    refreshTalkgroups().catch(() => null);
    refreshP25Status().catch(() => null);
    refreshBandplans().catch(() => null);
    refreshTranscriber().catch(() => null);
    refreshAudioDevices().catch(() => null);

    const mediaDevices = navigator?.mediaDevices;
    const onDeviceChange = () => refreshAudioDevices().catch(() => null);
    if (mediaDevices?.addEventListener) {
      mediaDevices.addEventListener("devicechange", onDeviceChange);
    }

    const statusTimer = setInterval(() => refreshStatus().catch(() => null), 1000);
    const receiverTimer = setInterval(() => refreshReceiver().catch(() => null), 2500);
    const transcriberTimer = setInterval(() => refreshTranscriber().catch(() => null), 2000);
    const p25Timer = setInterval(() => refreshP25Status().catch(() => null), 2500);
    const clockTimer = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => {
      clearInterval(statusTimer);
      clearInterval(receiverTimer);
      clearInterval(transcriberTimer);
      clearInterval(p25Timer);
      clearInterval(clockTimer);
      if (mediaDevices?.removeEventListener) {
        mediaDevices.removeEventListener("devicechange", onDeviceChange);
      }
    };
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || typeof audio.setSinkId !== "function") {
      return;
    }

    const sinkId = selectedAudioDeviceId || "default";
    audio.setSinkId(sinkId).catch((error) => {
      setAudioMonitorError(`Audio output device error: ${error?.message || error}`);
      updateAudioOutputDevice("default");
    });
  }, [selectedAudioDeviceId]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.volume = audioVolume;
    }
    localStorage.setItem("tricore.audioVolume", String(audioVolume));
  }, [audioVolume]);

  useEffect(() => {
    const audio = audioRef.current;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!audio || !AudioContextClass) {
      return undefined;
    }

    const context = audioContextRef.current || new AudioContextClass();
    audioContextRef.current = context;

    const analyser = audioAnalyserRef.current || context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.65;
    audioAnalyserRef.current = analyser;

    if (!audioSourceRef.current) {
      audioSourceRef.current = context.createMediaElementSource(audio);
      audioSourceRef.current.connect(analyser);
      analyser.connect(context.destination);
    }

    const data = new Uint8Array(analyser.fftSize);
    const updateMeter = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let index = 0; index < data.length; index += 1) {
        const centered = (data[index] - 128) / 128;
        sum += centered * centered;
      }
      const rms = Math.sqrt(sum / data.length);
      const nextAudioLevel = Math.min(1, rms * 5);
      setAudioLevel(nextAudioLevel);
      audioMeterFrameRef.current = requestAnimationFrame(updateMeter);
    };

    audioMeterFrameRef.current = requestAnimationFrame(updateMeter);
    return () => {
      if (audioMeterFrameRef.current) {
        cancelAnimationFrame(audioMeterFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }

    const playbackChannel = status.current_channel || status.active_channel;
    const currentModulation = String(
      transcriptStatus.running
        ? (transcriptStatus.current_modulation || playbackChannel?.modulation || "nfm")
        : (playbackChannel?.modulation || "nfm"),
    ).toLowerCase();
    const browserAudioModulation = ["nfm", "am", "wfm"].includes(currentModulation) || (
      currentModulation === "p25_placeholder" && transcriptStatus.running
    );
    const usingSharedTranscriberAudio = Boolean(
      transcriptStatus.running &&
      (transcriptStatus.current_frequency_hz || status.current_frequency_hz),
    );
    const activeScannerAudioState = Boolean(
      status.state === "manual_tune" ||
      status.state === "searching" ||
      status.is_holding ||
      status.is_scanning,
    );

    const canPlay = Boolean(
      audioMonitoringEnabled &&
        browserAudioModulation &&
        (usingSharedTranscriberAudio || (receiver?.available ?? true)) &&
      !status.is_muted &&
      (transcriptStatus.current_frequency_hz || status.current_frequency_hz) &&
      activeScannerAudioState,
    );

    if (audioStopTimerRef.current) {
      window.clearTimeout(audioStopTimerRef.current);
      audioStopTimerRef.current = null;
    }

    if (!canPlay) {
      if (audioStreamUrlRef.current) {
        api("/api/audio/stop", "POST").catch(() => null);
      }
      fadeAudioTo(0, 120);
      audioStopTimerRef.current = window.setTimeout(() => {
        audio.pause();
        audio.removeAttribute("src");
        audioStreamUrlRef.current = "";
        audio.load();
      }, 140);
      setAudioLevel(0);
      return;
    }

    const playbackFrequencyHz = transcriptStatus.running
      ? transcriptStatus.current_frequency_hz || status.current_frequency_hz
      : status.current_frequency_hz;
    const modulation = transcriptStatus.running
      ? (transcriptStatus.current_modulation || playbackChannel?.modulation || "nfm").toLowerCase()
      : (playbackChannel?.modulation || "nfm").toLowerCase();
    const params = new URLSearchParams({
      frequency_hz: String(playbackFrequencyHz),
      modulation,
      stream_id: `${audioStreamVersion}-${transcriptStatus.running ? "transcribe" : "live"}`,
    });
    if (status.gain_db != null) {
      params.set("gain_db", String(status.gain_db));
    }
    if (status.squelch_db != null) {
      params.set("squelch_db", String(status.squelch_db));
    }
    const streamUrl = `${API_BASE}/api/audio/live?${params.toString()}`;

    audio.volume = audioVolume;
    if (audioStreamUrlRef.current !== streamUrl) {
      audio.src = streamUrl;
      audioStreamUrlRef.current = streamUrl;
      setAudioMonitorError("");
    }

    audioContextRef.current?.resume?.().catch(() => null);
    const playPromise = audio.play();
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch((error) => {
        setAudioMonitorError(`Audio playback needs a click: ${error?.message || error}`);
      });
    } else {
      setAudioMonitorError("");
    }

    return undefined;
  }, [
    audioMonitoringEnabled,
    transcriptStatus.running,
    transcriptStatus.current_frequency_hz,
    transcriptStatus.current_modulation,
    receiver?.available,
    status.is_muted,
    status.current_frequency_hz,
    status.gain_db,
    status.squelch_db,
    status.state,
    status.is_scanning,
    status.is_holding,
    status.current_channel?.modulation,
    status.active_channel?.modulation,
    audioVolume,
    audioStreamVersion,
  ]);

  const activeChannel = status.current_channel || status.active_channel;
  const selectedTalkgroup = p25Status?.selected_talkgroup || (
    p25Status?.talkgroup_decimal || status?.decoder?.talkgroup_decimal
      ? {
          decimal: Number(p25Status?.talkgroup_decimal || status?.decoder?.talkgroup_decimal),
          alpha_tag: p25Status?.tracking_label || activeChannel?.name,
        }
      : null
  ) || (
    activeChannel?.p25_talkgroup_decimal
      ? { decimal: activeChannel.p25_talkgroup_decimal, alpha_tag: activeChannel.name }
      : null
  );
  const liveAudioLevel = Number(audioLevel || 0);
  const liveAudioSignalLevel = liveAudioLevel > 0.01
    ? -96 + (Math.min(1, liveAudioLevel) * 62)
    : Number(status.signal_level ?? -100);
  const transcriberSignalLevel = Number(transcriptStatus.current_signal_level);
  const displayStatus = {
    ...status,
    signal_level: transcriptStatus.running && Number.isFinite(transcriberSignalLevel)
      ? transcriberSignalLevel
      : liveAudioSignalLevel,
  };
  const displayAudioLevel = Math.max(
    liveAudioLevel,
    transcriptStatus.running && Number.isFinite(Number(transcriptStatus.current_audio_level))
      ? Number(transcriptStatus.current_audio_level)
      : 0,
  );

  return (
    <div className="min-h-screen bg-[#090d12] text-white">
      <audio
        ref={audioRef}
        autoPlay
        playsInline
        controls
        className="sr-only"
        crossOrigin="anonymous"
        onCanPlay={() => setAudioMonitorError("")}
        onPlaying={() => {
          setAudioMonitorError("");
          fadeAudioTo(audioVolume, 220);
        }}
        onError={handleAudioMonitorError}
      />
      <TopStatusBar
        status={status}
        receiver={receiver}
        currentTime={time}
        audioDevices={audioDevices}
        selectedAudioDeviceId={selectedAudioDeviceId}
        onAudioDeviceChange={updateAudioOutputDevice}
        audioMonitoringEnabled={audioMonitoringEnabled}
        onAudioMonitoringChange={updateAudioMonitoringEnabled}
        audioVolume={audioVolume}
        onAudioVolumeChange={updateAudioVolume}
        onAudioMonitorPlay={playLiveAudio}
        audioMonitorError={audioMonitorError}
      />

      <main className="grid gap-4 p-4 xl:grid-cols-[320px_minmax(0,1fr)_340px]">
        <div className="grid content-start gap-4">
          <ScanFoldersPanel
            channels={channels}
            talkgroups={talkgroups}
            activeChannel={activeChannel}
            selectedTalkgroup={selectedTalkgroup}
            onTune={tuneChannel}
            onSelectTalkgroup={selectTalkgroup}
            onSetScanEnabled={setScanSelection}
          />
        </div>

        <section className="grid min-w-0 gap-4">
          <ActiveScanChannelCard
            status={displayStatus}
            selectedTalkgroup={selectedTalkgroup}
          />
          <NowListeningCard
            status={displayStatus}
            audioLevel={displayAudioLevel}
            onLockChannel={lockOnDisplayedChannel}
            selectedTalkgroup={selectedTalkgroup}
          />
          <RadioLog
            transcripts={transcripts}
            transcriptStatus={transcriptStatus}
            onStart={startTranscriber}
            onStop={stopTranscriber}
            onClear={clearTranscripts}
          />
        </section>

        <aside className="grid content-start gap-4">
          <ScanModePanel
            status={status}
            activeChannel={activeChannel}
            selectedTalkgroup={selectedTalkgroup}
            talkgroups={talkgroups}
          />
          <ScannerKeypad
            status={status}
            onScan={() => runScannerCommand("/api/scanner/start")}
            onStop={() => runScannerCommand("/api/scanner/stop")}
            onPause={() => status.is_paused ? runScannerCommand("/api/scanner/resume") : runScannerCommand("/api/scanner/pause")}
            onHold={lockOnDisplayedChannel}
            onRelease={() => runScannerCommand("/api/scanner/release")}
            onSkip={() => runScannerCommand("/api/scanner/skip")}
            onLockout={() => runScannerCommand("/api/scanner/lockout", { channel_id: activeChannel?.id })}
            onPriority={() => runScannerCommand("/api/scanner/priority", { channel_id: activeChannel?.id, priority: true })}
            onManual={manualTune}
            onSearch={() => startSearch()}
            onWeather={() => startSearch("noaa-weather")}
            onFm={() => startSearch("fm-broadcast")}
            onMute={() => runScannerCommand("/api/scanner/mute", { muted: !status.is_muted })}
          />
          <ReceiverPanel
            receiver={receiver}
            status={status}
            gain={gain}
            squelch={squelch}
            onMode={changeReceiverMode}
            onGain={changeGain}
            onSquelch={changeSquelch}
          />
          <SearchPanel
            bandplans={bandplans}
            selectedRange={selectedRange}
            manualFrequency={manualFrequency}
            manualModulation={manualModulation}
            onRange={setSelectedRange}
            onManualFrequency={setManualFrequency}
            onManualModulation={setManualModulation}
            onStartSearch={() => startSearch()}
            onStopSearch={() => runScannerCommand("/api/scanner/search/stop")}
            onManualTune={manualTune}
          />
        </aside>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
