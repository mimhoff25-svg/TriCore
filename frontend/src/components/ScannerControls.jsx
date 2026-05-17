import { Heart, Mic, MicOff, Play, Radio, RotateCcw, SkipForward, Square } from "lucide-react";

const btn = "flex min-h-12 items-center justify-center gap-2 rounded border border-white/10 bg-[#202938] px-3 py-3 font-semibold text-slate-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] transition hover:border-white/20 hover:bg-[#273244] disabled:opacity-40";
const btnG = "flex min-h-12 items-center justify-center gap-2 rounded bg-triCoreGreen px-4 py-3 font-semibold text-slate-950 shadow-[0_0_22px_rgba(101,240,160,0.20)] hover:brightness-110";
const btnA = "flex min-h-12 items-center justify-center gap-2 rounded bg-triCoreAmber px-4 py-3 font-semibold text-slate-950 shadow-[0_0_16px_rgba(255,209,102,0.18)] hover:brightness-110";
const btnR = "flex min-h-12 items-center justify-center gap-2 rounded bg-red-500/80 px-3 py-3 font-semibold text-white hover:bg-red-500";

export default function ScannerControls({
  status,
  gain,
  muted,
  onStart,
  onStop,
  onScanAllSystems,
  onHoldOrResume,
  onSkip,
  onToggleMute,
  onGain,
}) {
  const held = Boolean(status?.held);
  const scanning = status?.state === "SCANNING" || status?.state === "RECEIVING_CALL" || status?.state === "HOLDING_CHANNEL";

  return (
    <section className="mt-5 rounded border border-white/10 bg-[#111923] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Front Panel</h2>
        <p className="text-sm text-slate-400">Use Scan Lists on the left to scan one system, or scan all enabled systems here.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {scanning ? (
          <button onClick={onStop} className={btnR}>
            <Square className="h-4 w-4" />
            Stop
          </button>
        ) : (
          <button onClick={onStart} className={btnG}>
            <Play className="h-4 w-4" />
            Scan
          </button>
        )}

        <button onClick={onScanAllSystems || onStart} className={btn}>
          <RotateCcw className="h-4 w-4" />
          All Scan
        </button>

        <button
          onClick={onHoldOrResume}
          disabled={!scanning && !held}
          className={held ? btnA : btn}
        >
          <Radio className="h-4 w-4" />
          {held ? "Resume" : "Stay Here"}
        </button>

        <button onClick={onSkip} disabled={!scanning} className={btn}>
          <SkipForward className="h-4 w-4" />
          Avoid
        </button>

        <button onClick={onToggleMute} className={muted ? btnA : btn}>
          {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          {muted ? "Unmute" : "Mute"}
        </button>

        <button disabled className={btn}>
          <Heart className="h-4 w-4" />
          Favorites
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 rounded border border-white/10 bg-black/20 p-4">
        <label className="text-sm font-semibold text-slate-300" htmlFor="gain">RTL Gain</label>
        <select
          id="gain"
          value={gain}
          onChange={(e) => onGain(e.target.value)}
          className="rounded border border-white/10 bg-black/30 px-3 py-2 text-white"
        >
          <option value="auto">Auto</option>
          <option value="9">9.0 dB</option>
          <option value="19.7">19.7 dB</option>
          <option value="28">28.0 dB</option>
          <option value="36.4">36.4 dB</option>
          <option value="49.6">49.6 dB</option>
        </select>
        <span className="text-sm text-slate-400">
          Rail VHF often needs a decent antenna. Try 28-36 dB if the scanner never stops.
        </span>
      </div>

      <div className="mt-3 grid gap-2 rounded border border-white/10 bg-black/20 p-4 text-sm md:grid-cols-2">
        <div className="text-slate-400"><span className="font-semibold text-slate-200">Scan</span> starts cycling enabled channels</div>
        <div className="text-slate-400"><span className="font-semibold text-slate-200">Play on a Scan List</span> scans only that system</div>
        <div className="text-slate-400"><span className="font-semibold text-slate-200">Stay Here</span> locks to the current channel</div>
        <div className="text-slate-400"><span className="font-semibold text-slate-200">Avoid</span> temporarily skips the current channel</div>
      </div>
    </section>
  );
}
