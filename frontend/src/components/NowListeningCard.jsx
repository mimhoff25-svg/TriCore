// Service type → display label + color classes
const SERVICE_STYLES = {
  police:        { label: "Police",        badge: "bg-blue-500/20 text-blue-200 border-blue-400/30" },
  fire:          { label: "Fire",          badge: "bg-red-500/20 text-red-200 border-red-400/30" },
  ems:           { label: "EMS",           badge: "bg-orange-500/20 text-orange-200 border-orange-400/30" },
  weather:       { label: "Weather",       badge: "bg-sky-500/20 text-sky-200 border-sky-400/30" },
  utility:       { label: "Utility",       badge: "bg-yellow-500/20 text-yellow-200 border-yellow-400/30" },
  public_works:  { label: "Public Works",  badge: "bg-green-500/20 text-green-200 border-green-400/30" },
  transportation:{ label: "Transportation",badge: "bg-indigo-500/20 text-indigo-200 border-indigo-400/30" },
  railroad:      { label: "Railroad",      badge: "bg-lime-500/20 text-lime-200 border-lime-400/30" },
  interop:       { label: "Interop",       badge: "bg-violet-500/20 text-violet-200 border-violet-400/30" },
  fm_radio:      { label: "FM Radio",      badge: "bg-pink-500/20 text-pink-200 border-pink-400/30" },
  am_radio:      { label: "AM Radio",      badge: "bg-rose-500/20 text-rose-200 border-rose-400/30" },
  custom:        { label: "Other",         badge: "bg-white/5 text-slate-300 border-white/10" },
};

const STATE_LABELS = {
  SCANNING:       "Scanning",
  RECEIVING_CALL: "Receiving",
  HOLDING_CHANNEL:"Staying Here",
  MUTED:          "Muted",
  UNAVAILABLE:    "Unavailable",
  ERROR:          "Error",
  NO_SIGNAL:      "No Signal",
  DEVICE_NOT_FOUND: "Device Not Found",
  STARTING:       "P25 Starting",
  WAITING_FOR_TALKGROUP: "P25 Waiting",
  READY:          "Ready",
  LOCKED:         "Locked",
};

const STATE_STYLES = {
  SCANNING:       "border-triCoreBlue/30 bg-triCoreBlue/10 text-triCoreBlue",
  RECEIVING_CALL: "border-triCoreGreen/30 bg-triCoreGreen/10 text-triCoreGreen",
  HOLDING_CHANNEL:"border-triCoreAmber/30 bg-triCoreAmber/10 text-triCoreAmber",
  MUTED:          "border-slate-400/30 bg-slate-400/10 text-slate-300",
  UNAVAILABLE:    "border-red-400/30 bg-red-500/10 text-red-200",
  ERROR:          "border-red-400/30 bg-red-500/10 text-red-200",
  NO_SIGNAL:      "border-white/15 bg-white/5 text-slate-300",
  DEVICE_NOT_FOUND:"border-red-400/30 bg-red-500/10 text-red-200",
  STARTING:       "border-triCoreAmber/30 bg-triCoreAmber/10 text-triCoreAmber",
  WAITING_FOR_TALKGROUP: "border-triCoreBlue/30 bg-triCoreBlue/10 text-triCoreBlue",
  READY:          "border-white/15 bg-white/5 text-slate-300",
  LOCKED:         "border-red-400/30 bg-red-500/10 text-red-200",
};

export default function NowListeningCard({ status }) {
  const channel   = status?.active_channel;
  const state     = status?.state || "NO_SIGNAL";
  const power     = Number(status?.signal_power ?? 0);
  const threshold = Number(status?.signal_threshold ?? -35);
  const inDelay   = Boolean(status?.in_delay);
  const held      = Boolean(status?.held);
  const delayed   = Number(status?.delay_remaining ?? 0);

  // Map power to a 0–100 meter value
  const meter = Math.max(0, Math.min(100, (power - threshold + 20) * 2.5));

  const service   = SERVICE_STYLES[channel?.service_type] ?? SERVICE_STYLES.custom;
  const stateStyle = STATE_STYLES[state] ?? STATE_STYLES.NO_SIGNAL;
  const stateLabel = STATE_LABELS[state] ?? state;

  return (
    <section className="rounded border border-white/10 bg-[#0f1720] p-4 shadow-[0_0_50px_rgba(101,240,160,0.08)] lg:p-5">

      {/* Header row: channel name + badges + state pill */}
      <div className="rounded border border-triCoreGreen/20 bg-[#06110c] p-4 shadow-[inset_0_0_24px_rgba(101,240,160,0.08)]">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-normal text-triCoreGreen/70">TriCore Scanner Display</p>
            <h2 className="mt-3 max-w-3xl font-mono text-3xl font-bold tracking-normal text-triCoreGreen lg:text-5xl">
              {channel?.name || "SCAN MODE"}
            </h2>
            <div className="mt-2 font-mono text-xl font-semibold text-triCoreGreen/90">
              {channel ? `${(channel.frequency_hz / 1_000_000).toFixed(5)} MHz` : "Waiting for channel activity"}
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
            {channel && (
              <span className={`rounded border px-2 py-1 text-xs font-semibold ${service.badge}`}>
                {service.label}
              </span>
            )}
            {channel?.priority && (
              <span className="rounded border border-triCoreAmber/30 bg-triCoreAmber/10 px-2 py-1 text-xs font-semibold text-triCoreAmber">
                Priority
              </span>
            )}
            {channel?.favorite && (
              <span className="rounded border border-triCoreBlue/30 bg-triCoreBlue/10 px-2 py-1 text-xs font-semibold text-triCoreBlue">
                Favorite
              </span>
            )}
            {held && (
              <span className="rounded border border-triCoreAmber/50 bg-triCoreAmber/15 px-2 py-1 text-xs font-semibold text-triCoreAmber">
                Held
              </span>
            )}
            {inDelay && (
              <span className="rounded border border-white/20 bg-white/5 px-2 py-1 text-xs font-semibold text-slate-300">
                Delay {delayed.toFixed(0)}s
              </span>
            )}
            </div>
          </div>

          <div className={`rounded border px-5 py-3 text-xl font-bold ${stateStyle}`}>
            {stateLabel}
          </div>
        </div>
      </div>

      {/* Channel detail row */}
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <div className="rounded border border-white/10 bg-black/20 p-4">
          <div className="text-xs uppercase tracking-normal text-slate-500">Radio System</div>
          <div className="mt-1 text-base font-semibold text-white">{channel?.system || "TriCore Local"}</div>
        </div>
        <div className="rounded border border-white/10 bg-black/20 p-4">
          <div className="text-xs uppercase tracking-normal text-slate-500">Channel ID</div>
          <div className="mt-1 text-base font-semibold text-white">{channel?.id || "—"}</div>
        </div>
        <div className="rounded border border-white/10 bg-black/20 p-4">
          <div className="text-xs uppercase tracking-normal text-slate-500">Frequency</div>
          <div className="mt-1 text-base font-semibold text-white tabular-nums">
            {channel ? `${(channel.frequency_hz / 1_000_000).toFixed(5)} MHz` : "—"}
          </div>
        </div>
        <div className="rounded border border-white/10 bg-black/20 p-4">
          <div className="text-xs uppercase tracking-normal text-slate-500">Delay / Mode</div>
          <div className="mt-1 text-base font-semibold text-white">
            {channel ? `${channel.delay_seconds}s · ${(channel.modulation || "nfm").toUpperCase()}` : "—"}
          </div>
        </div>
      </div>

      {/* Signal meter + gain */}
      <div className="mt-6 grid gap-5 lg:grid-cols-[1fr_200px]">
        <div>
          <div className="mb-2 flex justify-between text-sm text-slate-300">
            <span>Signal Meter</span>
            <span className="tabular-nums">{power.toFixed(1)} dB</span>
          </div>
          <div className="h-6 overflow-hidden rounded bg-black/40 ring-1 ring-white/10">
            <div
              className="h-full rounded transition-all duration-150 bg-gradient-to-r from-triCoreBlue via-triCoreGreen to-triCoreAmber shadow-[0_0_18px_rgba(101,240,160,0.25)]"
              style={{ width: `${meter}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-xs text-slate-500">
            <span>Quiet</span>
            <span>Threshold {threshold.toFixed(1)} dB</span>
            <span>Strong</span>
          </div>
        </div>

        <div className="rounded border border-white/10 bg-black/20 p-4">
          <div className="text-xs uppercase tracking-normal text-slate-500">
            RTL Gain
          </div>
          <div className="mt-2 text-3xl font-bold tabular-nums text-white">
            {status?.gain_db == null ? "Auto" : `${Number(status.gain_db).toFixed(1)}`}
            {status?.gain_db != null && <span className="ml-1 text-lg font-normal text-slate-400">dB</span>}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Receiver sensitivity
          </div>
        </div>
      </div>
    </section>
  );
}
