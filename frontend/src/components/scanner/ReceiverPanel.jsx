import { Radio, SlidersHorizontal } from "lucide-react";

function titleCase(value) {
  return String(value || "--").replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function ReceiverPanel({
  receiver,
  status,
  gain,
  squelch,
  onMode,
  onGain,
  onSquelch,
}) {
  const simulated = Boolean(receiver?.simulated);
  const p25Runtime = status?.decoder?.modulation === "p25_placeholder" && status?.decoder?.runtime && typeof status.decoder.runtime === "object"
    ? status.decoder.runtime
    : null;
  const p25BusyDevices = Array.isArray(p25Runtime?.busy_device_numbers)
    ? p25Runtime.busy_device_numbers
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value) && value > 0)
    : [];
  const p25RuntimeRows = p25Runtime
    ? [
        p25Runtime?.health ? ["Managed P25", titleCase(p25Runtime.health)] : null,
        Number.isFinite(Number(p25Runtime?.device_count)) && Number(p25Runtime.device_count) > 0
          ? ["RTL Devices Seen", String(Number(p25Runtime.device_count))]
          : null,
        p25BusyDevices.length ? ["Busy Devices", p25BusyDevices.map((value) => `#${value}`).join(", ")] : null,
        Number.isFinite(Number(p25Runtime?.selected_device_number)) && Number(p25Runtime.selected_device_number) > 0
          ? ["Chosen Device", `#${Number(p25Runtime.selected_device_number)}`]
          : null,
        p25Runtime?.selected_serial ? ["Chosen Serial", String(p25Runtime.selected_serial)] : null,
        p25Runtime?.failing_serial ? ["Failing Serial", String(p25Runtime.failing_serial)] : null,
      ].filter(Boolean)
    : [];
  const frequencyText = Number.isFinite(Number(receiver?.tuned_frequency_hz)) && Number(receiver?.tuned_frequency_hz) > 0
    ? `${(Number(receiver.tuned_frequency_hz) / 1_000_000).toFixed(4)} MHz`
    : "--.---- MHz";
  const effectiveGain = gain === "auto" ? "Auto" : `${Number(gain).toFixed(1)} dB`;
  const lastRtlError = receiver?.last_rtl_error || receiver?.error_message || "None";
  const rows = [
    ["Receiver Mode", receiver?.label || status?.receiver_mode || "Demo"],
    ["Demo Receiver", receiver?.demo_available === false ? "Unavailable" : "Available"],
    ["RTL-SDR", receiver?.rtl_sdr_available ? "Available" : "Unavailable"],
    ["Tuned Frequency", frequencyText],
    ["Gain", effectiveGain],
    ["Squelch", `${Number(squelch).toFixed(0)} dB`],
    ["Last RTL-SDR Error", lastRtlError],
  ];

  return (
    <section className="rounded-lg border border-white/10 bg-[#101720] p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
        <SlidersHorizontal className="h-4 w-4 text-triCoreAmber" />
        Receiver / Hardware Check
      </div>

      <div className="mb-4 grid gap-2 rounded-lg border border-white/10 bg-black/20 p-3 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
            <div className="min-w-0 break-words font-semibold text-slate-200">{value}</div>
          </div>
        ))}
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

      {(p25Runtime?.error_detail || p25RuntimeRows.length) && (
        <div className="mt-4 rounded-lg border border-triCoreAmber/25 bg-[rgba(74,48,8,0.28)] p-3 text-sm">
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-triCoreAmber">Managed P25 Diagnostics</div>
          {p25Runtime?.error_detail && (
            <div className="mt-2 text-sm leading-5 text-[#fff1cf]">{p25Runtime.error_detail}</div>
          )}
          {p25RuntimeRows.length > 0 && (
            <div className="mt-3 grid gap-2 rounded-lg border border-white/8 bg-black/15 p-3 text-sm">
              {p25RuntimeRows.map(([label, value]) => (
                <div key={label} className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
                  <div className="min-w-0 break-words font-semibold text-slate-100">{value}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {receiver?.error_message && (
        <div className="mt-3 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
          {receiver.error_message}
        </div>
      )}
    </section>
  );
}
