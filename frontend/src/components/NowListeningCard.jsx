import { AlertTriangle, Radio, Signal } from "lucide-react";

function formatMHz(frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Number.isFinite(parsed) || parsed <= 0) return "--.---- MHz";
  return `${(parsed / 1_000_000).toFixed(4)} MHz`;
}

function scannerState(status) {
  return status?.scanner_state || "Stopped";
}

function titleCase(value) {
  return String(value || "--").replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export default function NowListeningCard({ status }) {
  const channel = status?.current_channel || status?.active_channel || null;
  const frequencyHz = status?.current_frequency_hz || channel?.frequency_hz || null;
  const signalLevel = Number(status?.signal_level ?? status?.signal_power ?? -72);
  const receiverMode = status?.receiver_mode || (status?.simulated ? "Demo" : "RTL-SDR");
  const unavailable = Boolean(channel?.unavailable || channel?.encrypted);
  const state = scannerState(status);
  const meter = Math.max(0, Math.min(100, (signalLevel + 110) * 1.6));
  const gainText = status?.gain_db == null ? "Auto" : `${Number(status.gain_db).toFixed(1)} dB`;
  const currentBank = channel?.bank_name || titleCase(channel?.bank_id);
  const currentService = titleCase(channel?.service_type);
  const modulation = String(channel?.modulation || "--").toUpperCase();
  const mutedText = status?.is_muted ? "Muted" : "Live";

  return (
    <section className="rounded-xl border border-white/10 bg-[#0b141e] p-4 shadow-[0_20px_80px_rgba(0,0,0,0.32)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Now Listening</div>
          <h2 className="mt-2 truncate font-mono text-3xl font-semibold text-white">
            {channel?.name || "No Channel Selected"}
          </h2>
          <div className="mt-1 truncate text-sm font-semibold text-slate-300">
            {channel?.system_name || channel?.system || "TriCore Scanner"}
          </div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm font-semibold text-slate-200">
          {state}
        </div>
      </div>

      {(unavailable || status?.error_message) && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-triCoreAmber/30 bg-triCoreAmber/10 px-3 py-2 text-sm text-triCoreAmber">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{unavailable ? "Unavailable channel skipped." : status.error_message}</span>
        </div>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Bank</div>
          <div className="mt-2 text-xl font-semibold text-white">{currentBank}</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Service</div>
          <div className="mt-2 text-xl font-semibold text-white">{currentService}</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Frequency</div>
          <div className="mt-2 font-mono text-xl font-semibold text-white">{formatMHz(frequencyHz)}</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Signal</div>
          <div className="mt-2 flex items-center gap-2 text-xl font-semibold text-white">
            <Signal className="h-5 w-5 text-triCoreGreen" />
            {signalLevel.toFixed(1)} dB
          </div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Channel</div>
          <div className="mt-2 text-xl font-semibold text-white">{channel?.name || "--"}</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Modulation</div>
          <div className="mt-2 text-xl font-semibold text-white">{modulation}</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Receiver</div>
          <div className="mt-2 flex items-center gap-2 text-xl font-semibold text-white">
            <Radio className="h-5 w-5 text-triCoreBlue" />
            {receiverMode}
          </div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">State</div>
          <div className="mt-2 text-xl font-semibold text-white">{state}</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Squelch</div>
          <div className="mt-2 text-xl font-semibold text-white">{Number(status?.squelch_db ?? -65).toFixed(0)} dB</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Gain</div>
          <div className="mt-2 text-xl font-semibold text-white">{gainText}</div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Audio</div>
          <div className="mt-2 text-xl font-semibold text-white">{mutedText}</div>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-3">
        <div className="mb-2 flex justify-between text-sm text-slate-300">
          <span>Signal Level</span>
          <span className="tabular-nums">{signalLevel.toFixed(1)} dB</span>
        </div>
        <div className="h-5 overflow-hidden rounded-full bg-black/40 ring-1 ring-white/10">
          <div
            className="h-full rounded-full bg-gradient-to-r from-triCoreBlue via-triCoreGreen to-triCoreAmber transition-all duration-150"
            style={{ width: `${meter}%` }}
          />
        </div>
      </div>
    </section>
  );
}
