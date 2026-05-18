import { Heart, Mic, MicOff, Play, Radio, RotateCcw, SkipForward, Square } from "lucide-react";

const btn = "group flex min-h-[84px] flex-col items-start justify-between rounded-[22px] border border-white/10 bg-[#121c29] px-4 py-3 text-left text-slate-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] transition hover:border-white/20 hover:bg-[#182334] disabled:opacity-40";
const btnG = "group flex min-h-[84px] flex-col items-start justify-between rounded-[22px] border border-triCoreGreen/20 bg-triCoreGreen px-4 py-3 text-left font-semibold text-slate-950 shadow-[0_0_22px_rgba(101,240,160,0.20)] hover:brightness-110";
const btnA = "group flex min-h-[84px] flex-col items-start justify-between rounded-[22px] border border-triCoreAmber/20 bg-triCoreAmber px-4 py-3 text-left font-semibold text-slate-950 shadow-[0_0_16px_rgba(255,209,102,0.18)] hover:brightness-110";
const btnR = "group flex min-h-[84px] flex-col items-start justify-between rounded-[22px] border border-red-400/20 bg-red-500/80 px-4 py-3 text-left font-semibold text-white hover:bg-red-500";

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
    <section className="rounded-[28px] border border-white/10 bg-[#0e1722] p-5 shadow-[0_20px_60px_rgba(0,0,0,0.28)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.32em] text-slate-500">Command Deck</div>
          <h2 className="mt-2 text-lg font-semibold">Front Panel</h2>
          <p className="mt-1 text-sm text-slate-400">Use Scan Lists on the left to scan one system, or drive the whole receiver here.</p>
        </div>
        <div className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] ${held ? "border-triCoreAmber/30 bg-triCoreAmber/10 text-triCoreAmber" : scanning ? "border-triCoreGreen/25 bg-triCoreGreen/10 text-triCoreGreen" : "border-white/10 bg-white/5 text-slate-300"}`}>
          {held ? "Hold Active" : scanning ? "Live Scan" : "Idle"}
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {scanning ? (
          <button onClick={onStop} aria-label="Stop" className={btnR}>
            <div className="flex items-center gap-2 text-base font-semibold">
              <Square className="h-4 w-4" />
              Stop
            </div>
            <div className="text-xs text-white/80">Silence the active scan engine</div>
          </button>
        ) : (
          <button onClick={onStart} aria-label="Scan" className={btnG}>
            <div className="flex items-center gap-2 text-base font-semibold">
              <Play className="h-4 w-4" />
              Scan
            </div>
            <div className="text-xs text-slate-950/75">Cycle all enabled channels</div>
          </button>
        )}

        <button onClick={onScanAllSystems || onStart} aria-label="All Scan" className={btn}>
          <div className="flex items-center gap-2 text-base font-semibold">
            <RotateCcw className="h-4 w-4" />
            All Scan
          </div>
          <div className="text-xs text-slate-500">Reset filters and scan every system</div>
        </button>

        <button
          onClick={onHoldOrResume}
          aria-label={held ? "Resume" : "Stay Here"}
          disabled={!scanning && !held}
          className={held ? btnA : btn}
        >
          <div className="flex items-center gap-2 text-base font-semibold">
            <Radio className="h-4 w-4" />
            {held ? "Resume" : "Stay Here"}
          </div>
          <div className="text-xs text-slate-500">Lock or release the current traffic</div>
        </button>

        <button onClick={onSkip} aria-label="Avoid" disabled={!scanning} className={btn}>
          <div className="flex items-center gap-2 text-base font-semibold">
            <SkipForward className="h-4 w-4" />
            Avoid
          </div>
          <div className="text-xs text-slate-500">Temporarily skip the active channel</div>
        </button>

        <button onClick={onToggleMute} aria-label={muted ? "Unmute" : "Mute"} className={muted ? btnA : btn}>
          <div className="flex items-center gap-2 text-base font-semibold">
            {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            {muted ? "Unmute" : "Mute"}
          </div>
          <div className="text-xs text-slate-500">Toggle receiver audio output</div>
        </button>

        <button disabled aria-label="Favorites" className={btn}>
          <div className="flex items-center gap-2 text-base font-semibold">
            <Heart className="h-4 w-4" />
            Favorites
          </div>
          <div className="text-xs text-slate-500">Reserved for saved quick actions</div>
        </button>
      </div>

      <div className="mt-5 rounded-[22px] border border-white/10 bg-black/20 p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <label className="text-sm font-semibold text-slate-300" htmlFor="gain">RTL Gain</label>
          <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-300">
            {gain === "auto" ? "Auto" : `${gain} dB`}
          </div>
        </div>
        <select
          id="gain"
          value={gain}
          onChange={(e) => onGain(e.target.value)}
          className="w-full rounded-2xl border border-white/10 bg-[#111a26] px-3 py-3 text-white"
        >
          <option value="auto">Auto</option>
          <option value="9">9.0 dB</option>
          <option value="19.7">19.7 dB</option>
          <option value="28">28.0 dB</option>
          <option value="36.4">36.4 dB</option>
          <option value="49.6">49.6 dB</option>
        </select>
        <div className="mt-3 text-sm text-slate-400">
          Rail VHF often needs a decent antenna. Try 28-36 dB if the scanner never stops.
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-[18px] border border-white/10 bg-[#111923] px-4 py-3 text-sm text-slate-400"><span className="font-semibold text-slate-200">Scan</span> starts cycling enabled channels.</div>
        <div className="rounded-[18px] border border-white/10 bg-[#111923] px-4 py-3 text-sm text-slate-400"><span className="font-semibold text-slate-200">Play on a Scan List</span> scans only that system.</div>
        <div className="rounded-[18px] border border-white/10 bg-[#111923] px-4 py-3 text-sm text-slate-400"><span className="font-semibold text-slate-200">Stay Here</span> locks to the current channel.</div>
        <div className="rounded-[18px] border border-white/10 bg-[#111923] px-4 py-3 text-sm text-slate-400"><span className="font-semibold text-slate-200">Avoid</span> temporarily skips the current channel.</div>
      </div>
    </section>
  );
}
