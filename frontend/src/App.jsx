import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import NowListeningCard from "./components/NowListeningCard";
import BankPanel from "./components/scanner/BankPanel";
import ChannelChart from "./components/scanner/ChannelChart";
import ReceiverPanel from "./components/scanner/ReceiverPanel";
import ScannerKeypad from "./components/scanner/ScannerKeypad";
import SearchPanel from "./components/scanner/SearchPanel";
import SignalMeter from "./components/scanner/SignalMeter";
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
  const [banks, setBanks] = useState([]);
  const [channels, setChannels] = useState([]);
  const [bandplans, setBandplans] = useState([]);
  const [time, setTime] = useState(new Date().toLocaleTimeString());
  const [gain, setGain] = useState("auto");
  const [squelch, setSquelch] = useState(-65);
  const [selectedRange, setSelectedRange] = useState("");
  const [manualFrequency, setManualFrequency] = useState("");
  const [manualModulation, setManualModulation] = useState("nfm");

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

  async function refreshBandplans() {
    const ranges = await api("/api/bandplans");
    setBandplans(ranges);
    setSelectedRange((current) => current || ranges[0]?.id || "");
  }

  async function runScannerCommand(path, body = undefined) {
    const nextStatus = await api(path, "POST", body);
    setStatus(nextStatus);
    setGain(nextStatus.gain_db == null ? "auto" : String(nextStatus.gain_db));
    setSquelch(Number(nextStatus.squelch_db ?? -65));
    refreshReceiver().catch(() => null);
    refreshChannels().catch(() => null);
    return nextStatus;
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
    await api("/api/receiver/mode", "POST", { simulated });
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
    });
  }

  async function startSearch(rangeId = selectedRange) {
    if (!rangeId) return;
    setSelectedRange(rangeId);
    await runScannerCommand("/api/scanner/search/start", { range_id: rangeId });
  }

  async function tuneChannel(channelId) {
    await runScannerCommand("/api/scanner/tune", { channel_id: channelId });
  }

  useEffect(() => {
    refreshStatus().catch(() => setStatus({
      ...INITIAL_STATUS,
      state: "error",
      scanner_state: "Error",
      error_message: "Backend offline",
      message: "Backend offline",
    }));
    refreshReceiver().catch(() => null);
    refreshBanks().catch(() => null);
    refreshChannels().catch(() => null);
    refreshBandplans().catch(() => null);

    const statusTimer = setInterval(() => refreshStatus().catch(() => null), 1000);
    const receiverTimer = setInterval(() => refreshReceiver().catch(() => null), 2500);
    const clockTimer = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => {
      clearInterval(statusTimer);
      clearInterval(receiverTimer);
      clearInterval(clockTimer);
    };
  }, []);

  const activeChannel = status.current_channel || status.active_channel;

  return (
    <div className="min-h-screen bg-[#090d12] text-white">
      <TopStatusBar status={status} receiver={receiver} currentTime={time} />

      <main className="grid gap-4 p-4 xl:grid-cols-[280px_minmax(0,1fr)_340px]">
        <BankPanel banks={banks} onEnable={enableBank} onDisable={disableBank} />

        <section className="grid min-w-0 gap-4">
          <NowListeningCard status={status} />
          <SignalMeter level={status.signal_level} squelch={status.squelch_db} />
          <ChannelChart
            channels={channels}
            banks={banks}
            activeChannel={activeChannel}
            onTune={tuneChannel}
          />
        </section>

        <aside className="grid content-start gap-4">
          <ScannerKeypad
            status={status}
            onScan={() => runScannerCommand("/api/scanner/start")}
            onStop={() => runScannerCommand("/api/scanner/stop")}
            onPause={() => status.is_paused ? runScannerCommand("/api/scanner/resume") : runScannerCommand("/api/scanner/pause")}
            onHold={() => runScannerCommand("/api/scanner/hold")}
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
