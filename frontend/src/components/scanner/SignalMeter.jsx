export default function SignalMeter({ level = -100, squelch = -65 }) {
  const parsed = Number(level);
  const meter = Math.max(0, Math.min(100, (parsed + 110) * 1.6));
  const open = parsed >= Number(squelch);

  return (
    <div className="rounded-lg border border-white/10 bg-[#101720] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Signal Meter</div>
          <div className="mt-1 font-mono text-2xl font-semibold text-white">{parsed.toFixed(1)} dB</div>
        </div>
        <div className={`rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] ${open ? "border-triCoreGreen/30 bg-triCoreGreen/10 text-triCoreGreen" : "border-white/10 bg-white/5 text-slate-400"}`}>
          {open ? "Open" : "Quiet"}
        </div>
      </div>
      <div className="mt-4 h-5 overflow-hidden rounded bg-black/50 ring-1 ring-white/10">
        <div
          className="h-full bg-gradient-to-r from-triCoreBlue via-triCoreGreen to-triCoreAmber"
          style={{ width: `${meter}%` }}
        />
      </div>
      <div className="mt-2 flex justify-between text-xs text-slate-500">
        <span>Weak</span>
        <span>Squelch {Number(squelch).toFixed(1)} dB</span>
        <span>Strong</span>
      </div>
    </div>
  );
}

