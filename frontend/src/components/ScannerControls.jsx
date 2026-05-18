import {
  Mic,
  MicOff,
  Pause,
  Pin,
  PinOff,
  Play,
  Radio,
  RotateCcw,
  SkipForward,
  Square,
  StepForward,
} from "lucide-react";

const baseButton = "flex min-h-12 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40";
const quietButton = `${baseButton} border-white/10 bg-[#121c29] text-slate-100 hover:border-white/20 hover:bg-[#182334]`;
const greenButton = `${baseButton} border-triCoreGreen/30 bg-triCoreGreen text-slate-950 hover:brightness-110`;
const amberButton = `${baseButton} border-triCoreAmber/35 bg-triCoreAmber text-slate-950 hover:brightness-110`;
const redButton = `${baseButton} border-red-400/30 bg-red-500/85 text-white hover:bg-red-500`;

export default function ScannerControls({
  status,
  gain,
  onStart,
  onStop,
  onPause,
  onResume,
  onHold,
  onReleaseHold,
  onNext,
  onSkip,
  onToggleMute,
  onGain,
  onReceiverMode,
}) {
  const currentChannel = status?.current_channel || status?.active_channel || null;
  const scanning = Boolean(status?.is_scanning);
  const paused = Boolean(status?.is_paused);
  const holding = Boolean(status?.is_holding ?? status?.held);
  const muted = Boolean(status?.is_muted ?? status?.muted);
  const simulated = Boolean(status?.simulated);

  return (
    <section className="rounded-xl border border-white/10 bg-[#0e1722] p-4 shadow-[0_20px_60px_rgba(0,0,0,0.28)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Scanner Controls</div>
          <h2 className="mt-1 text-lg font-semibold text-white">Mission Operation</h2>
        </div>
        <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm font-semibold text-slate-200">
          {status?.scanner_state || "Stopped"}
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <button onClick={onStart} disabled={scanning && !paused && !holding} className={greenButton}>
          <Play className="h-4 w-4" />
          Start
        </button>
        <button onClick={onStop} className={redButton}>
          <Square className="h-4 w-4" />
          Stop
        </button>
        <button onClick={onPause} disabled={!scanning || paused} className={quietButton}>
          <Pause className="h-4 w-4" />
          Pause
        </button>
        <button onClick={onResume} disabled={!paused} className={quietButton}>
          <RotateCcw className="h-4 w-4" />
          Resume
        </button>
        <button onClick={onHold} disabled={!currentChannel || holding} className={holding ? amberButton : quietButton}>
          <Pin className="h-4 w-4" />
          Stay Here
        </button>
        <button onClick={onReleaseHold} disabled={!holding} className={quietButton}>
          <PinOff className="h-4 w-4" />
          Release
        </button>
        <button onClick={onNext} className={quietButton}>
          <StepForward className="h-4 w-4" />
          Next
        </button>
        <button onClick={onSkip} disabled={!currentChannel} className={quietButton}>
          <SkipForward className="h-4 w-4" />
          Skip
        </button>
        <button onClick={onToggleMute} className={muted ? amberButton : quietButton}>
          {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          {muted ? "Unmute" : "Mute"}
        </button>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Receiver Mode</div>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => onReceiverMode?.(true)}
              className={simulated ? amberButton : quietButton}
            >
              <Radio className="h-4 w-4" />
              Demo
            </button>
            <button
              onClick={() => onReceiverMode?.(false)}
              className={!simulated ? greenButton : quietButton}
            >
              <Radio className="h-4 w-4" />
              RTL-SDR
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-black/20 p-3">
          <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-slate-500" htmlFor="gain">
            Gain
          </label>
          <select
            id="gain"
            value={gain}
            onChange={(event) => onGain?.(event.target.value)}
            className="w-full rounded-lg border border-white/10 bg-[#111a26] px-3 py-2 text-sm font-semibold text-white"
          >
            <option value="auto">Auto</option>
            <option value="9">9.0 dB</option>
            <option value="19.7">19.7 dB</option>
            <option value="28">28.0 dB</option>
            <option value="36.4">36.4 dB</option>
            <option value="49.6">49.6 dB</option>
          </select>
        </div>
      </div>
    </section>
  );
}
