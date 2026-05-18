import {
  CloudSun,
  EyeOff,
  Heart,
  Mic,
  MicOff,
  Music,
  Pause,
  Pin,
  PinOff,
  Play,
  Radio,
  Search,
  SkipForward,
  Square,
} from "lucide-react";

const button = "flex min-h-11 items-center justify-center gap-2 rounded-lg border border-white/10 bg-[#151d28] px-3 py-2 text-sm font-semibold text-slate-100 transition hover:border-white/20 hover:bg-[#1b2634] disabled:cursor-not-allowed disabled:opacity-40";
const green = "flex min-h-11 items-center justify-center gap-2 rounded-lg border border-triCoreGreen/30 bg-triCoreGreen px-3 py-2 text-sm font-semibold text-slate-950 transition hover:brightness-110";
const red = "flex min-h-11 items-center justify-center gap-2 rounded-lg border border-red-400/30 bg-red-500/85 px-3 py-2 text-sm font-semibold text-white transition hover:bg-red-500";
const amber = "flex min-h-11 items-center justify-center gap-2 rounded-lg border border-triCoreAmber/30 bg-triCoreAmber px-3 py-2 text-sm font-semibold text-slate-950 transition hover:brightness-110";

export default function ScannerKeypad({
  status,
  onScan,
  onStop,
  onPause,
  onHold,
  onRelease,
  onSkip,
  onLockout,
  onPriority,
  onManual,
  onSearch,
  onWeather,
  onFm,
  onMute,
}) {
  const hasChannel = Boolean(status?.current_channel || status?.active_channel);
  const holding = Boolean(status?.is_holding);
  const muted = Boolean(status?.is_muted);
  const paused = Boolean(status?.is_paused);

  return (
    <section className="rounded-lg border border-white/10 bg-[#101720] p-4">
      <div className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">Scanner Keypad</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <button onClick={onScan} className={green}><Play className="h-4 w-4" />Scan</button>
        <button onClick={onStop} className={red}><Square className="h-4 w-4" />Stop</button>
        <button onClick={onPause} disabled={!status?.is_scanning && !paused} className={button}><Pause className="h-4 w-4" />{paused ? "Resume" : "Pause"}</button>
        <button onClick={onHold} disabled={!hasChannel || holding} className={holding ? amber : button}><Pin className="h-4 w-4" />Stay Here</button>
        <button onClick={onRelease} disabled={!holding} className={button}><PinOff className="h-4 w-4" />Release</button>
        <button onClick={onSkip} disabled={!hasChannel} className={button}><SkipForward className="h-4 w-4" />Skip</button>
        <button onClick={onLockout} disabled={!hasChannel} className={button}><EyeOff className="h-4 w-4" />Hide Channel</button>
        <button onClick={onPriority} disabled={!hasChannel} className={button}><Heart className="h-4 w-4" />Priority</button>
        <button onClick={onManual} className={button}><Radio className="h-4 w-4" />Manual</button>
        <button onClick={onSearch} className={button}><Search className="h-4 w-4" />Search</button>
        <button onClick={onWeather} className={button}><CloudSun className="h-4 w-4" />Weather</button>
        <button onClick={onFm} className={button}><Music className="h-4 w-4" />FM</button>
        <button onClick={onMute} className={button}>{muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}{muted ? "Unmute" : "Mute"}</button>
      </div>
    </section>
  );
}
