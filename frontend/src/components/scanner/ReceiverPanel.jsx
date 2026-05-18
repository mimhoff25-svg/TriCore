import { Radio, SlidersHorizontal } from "lucide-react";

export default function ReceiverPanel({
  receiver,
  gain,
  squelch,
  onMode,
  onGain,
  onSquelch,
}) {
  const simulated = Boolean(receiver?.simulated);

  return (
    <section className="rounded-lg border border-white/10 bg-[#101720] p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
        <SlidersHorizontal className="h-4 w-4 text-triCoreAmber" />
        Receiver
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={() => onMode?.(true)}
          className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${simulated ? "border-triCoreAmber/30 bg-triCoreAmber text-slate-950" : "border-white/10 bg-[#151d28] text-slate-100"}`}
        >
          <Radio className="h-4 w-4" />
          Demo
        </button>
        <button
          onClick={() => onMode?.(false)}
          className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${!simulated ? "border-triCoreGreen/30 bg-triCoreGreen text-slate-950" : "border-white/10 bg-[#151d28] text-slate-100"}`}
        >
          <Radio className="h-4 w-4" />
          RTL-SDR
        </button>
      </div>

      <label className="mt-4 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500" htmlFor="gain">Gain</label>
      <select
        id="gain"
        value={gain}
        onChange={(event) => onGain?.(event.target.value)}
        className="mt-2 w-full rounded-lg border border-white/10 bg-[#151d28] px-3 py-2 text-sm font-semibold text-white"
      >
        <option value="auto">Auto</option>
        <option value="9">9.0 dB</option>
        <option value="19.7">19.7 dB</option>
        <option value="28">28.0 dB</option>
        <option value="36.4">36.4 dB</option>
        <option value="49.6">49.6 dB</option>
      </select>

      <label className="mt-4 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500" htmlFor="squelch">Squelch</label>
      <input
        id="squelch"
        type="range"
        min="-100"
        max="-30"
        step="1"
        value={squelch}
        onChange={(event) => onSquelch?.(Number(event.target.value))}
        className="mt-3 w-full"
      />
      <div className="mt-1 text-sm font-semibold text-slate-300">{Number(squelch).toFixed(0)} dB</div>

      {receiver?.error_message && (
        <div className="mt-3 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
          {receiver.error_message}
        </div>
      )}
    </section>
  );
}

