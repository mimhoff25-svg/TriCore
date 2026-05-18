import { Search } from "lucide-react";

export default function SearchPanel({
  bandplans = [],
  selectedRange,
  manualFrequency,
  manualModulation,
  onRange,
  onManualFrequency,
  onManualModulation,
  onStartSearch,
  onStopSearch,
  onManualTune,
}) {
  return (
    <section className="rounded-lg border border-white/10 bg-[#101720] p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
        <Search className="h-4 w-4 text-triCoreBlue" />
        Search / Manual
      </div>

      <label className="block text-xs font-semibold uppercase tracking-[0.14em] text-slate-500" htmlFor="range">Service Range</label>
      <select
        id="range"
        value={selectedRange}
        onChange={(event) => onRange?.(event.target.value)}
        className="mt-2 w-full rounded-lg border border-white/10 bg-[#151d28] px-3 py-2 text-sm font-semibold text-white"
      >
        {bandplans.map((range) => (
          <option key={range.id} value={range.id}>{range.name}</option>
        ))}
      </select>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button onClick={onStartSearch} className="rounded-lg border border-triCoreBlue/30 bg-triCoreBlue px-3 py-2 text-sm font-semibold text-slate-950">
          Search
        </button>
        <button onClick={onStopSearch} className="rounded-lg border border-white/10 bg-[#151d28] px-3 py-2 text-sm font-semibold text-slate-100">
          Stop Search
        </button>
      </div>

      <div className="mt-4 grid grid-cols-[minmax(0,1fr)_90px] gap-2">
        <input
          value={manualFrequency}
          onChange={(event) => onManualFrequency?.(event.target.value)}
          placeholder="Frequency MHz"
          className="rounded-lg border border-white/10 bg-[#151d28] px-3 py-2 text-sm font-semibold text-white placeholder:text-slate-500"
        />
        <select
          value={manualModulation}
          onChange={(event) => onManualModulation?.(event.target.value)}
          className="rounded-lg border border-white/10 bg-[#151d28] px-2 py-2 text-sm font-semibold uppercase text-white"
        >
          <option value="nfm">NFM</option>
          <option value="wfm">WFM</option>
          <option value="am">AM</option>
        </select>
      </div>
      <button onClick={onManualTune} className="mt-2 w-full rounded-lg border border-triCoreGreen/30 bg-triCoreGreen px-3 py-2 text-sm font-semibold text-slate-950">
        Manual Tune
      </button>
    </section>
  );
}

