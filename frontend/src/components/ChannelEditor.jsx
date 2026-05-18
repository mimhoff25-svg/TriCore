import { useState } from "react";
import { X } from "lucide-react";

const MODULATIONS = ["nfm", "wfm", "am"];
const SERVICE_TYPES = [
  "fire", "ems", "police", "weather", "public_works",
  "utility", "transportation", "interop", "fm_radio", "am_radio", "custom",
];

export default function ChannelEditor({ onSave, onClose }) {
  const [form, setForm] = useState({
    name: "",
    system: "",
    frequency_mhz: "",
    modulation: "nfm",
    service_type: "custom",
    delay_seconds: 2,
    priority: false,
    favorite: false,
  });
  const [error, setError] = useState("");

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    setError("");
  }

  function submit(e) {
    e.preventDefault();
    const freq = parseFloat(form.frequency_mhz);
    if (!form.name.trim()) return setError("Name is required.");
    if (!form.system.trim()) return setError("System is required.");
    if (!freq || freq < 0.1 || freq > 1800) return setError("Enter a valid frequency (0.1–1800 MHz).");

    onSave({
      name: form.name.trim(),
      system: form.system.trim(),
      frequency_hz: Math.round(freq * 1_000_000),
      modulation: form.modulation,
      service_type: form.service_type,
      category: "other",
      delay_seconds: Number(form.delay_seconds),
      priority: form.priority,
      favorite: form.favorite,
      encrypted: false,
    });
  }

  const inp = "w-full rounded-2xl border border-white/10 bg-[#101925] px-3 py-3 text-white text-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] focus:border-triCoreBlue/50 focus:outline-none";
  const label = "mb-1 block text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#02050a]/80 px-4 backdrop-blur-md">
      <div className="relative w-full max-w-xl overflow-hidden rounded-[28px] border border-white/15 bg-[#111a24] p-6 shadow-2xl">
        <div className="absolute inset-0 bg-gradient-to-br from-triCoreBlue/10 via-transparent to-triCoreGreen/10" />
        <button onClick={onClose} className="absolute right-4 top-4 z-10 rounded-full border border-white/10 bg-black/20 p-2 text-slate-400 hover:text-white">
          <X className="h-5 w-5" />
        </button>

        <div className="relative z-10 mb-5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.35em] text-slate-500">TriCore Editor</div>
          <h2 className="mt-2 text-xl font-bold text-white">Add Channel</h2>
          <p className="mt-1 text-sm text-slate-400">Create a new conventional channel and drop it directly into the live scanner list.</p>
        </div>

        <form onSubmit={submit} className="relative z-10 space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className={label}>Channel Name</label>
              <input className={inp} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="AFD Fire Dispatch" />
            </div>
            <div className="col-span-2">
              <label className={label}>System / Group</label>
              <input className={inp} value={form.system} onChange={(e) => set("system", e.target.value)} placeholder="Austin Fire & EMS" />
            </div>
            <div>
              <label className={label}>Frequency (MHz)</label>
              <input className={inp} type="number" step="0.0001" value={form.frequency_mhz} onChange={(e) => set("frequency_mhz", e.target.value)} placeholder="154.1750" />
            </div>
            <div>
              <label className={label}>Mode</label>
              <select className={inp} value={form.modulation} onChange={(e) => set("modulation", e.target.value)}>
                {MODULATIONS.map((m) => <option key={m} value={m}>{m.toUpperCase()}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>Service Type</label>
              <select className={inp} value={form.service_type} onChange={(e) => set("service_type", e.target.value)}>
                {SERVICE_TYPES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>Delay (seconds)</label>
              <input className={inp} type="number" min="0" max="10" step="0.5" value={form.delay_seconds} onChange={(e) => set("delay_seconds", e.target.value)} />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex items-center gap-2 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-slate-300 cursor-pointer">
              <input type="checkbox" checked={form.priority} onChange={(e) => set("priority", e.target.checked)} className="accent-triCoreAmber" />
              Priority
            </label>
            <label className="flex items-center gap-2 rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-slate-300 cursor-pointer">
              <input type="checkbox" checked={form.favorite} onChange={(e) => set("favorite", e.target.checked)} className="accent-triCoreBlue" />
              Favorite
            </label>
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}

          <div className="flex gap-3 pt-1">
            <button type="submit" className="flex-1 rounded-2xl bg-triCoreGreen px-4 py-3 font-semibold text-slate-950 hover:brightness-110">
              Add Channel
            </button>
            <button type="button" onClick={onClose} className="rounded-2xl border border-white/10 px-4 py-3 text-sm text-slate-300 hover:bg-white/5">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
