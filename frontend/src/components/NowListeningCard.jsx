import { getAgencyLogo } from "../config/agencyLogos";

function formatMHz(frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Number.isFinite(parsed) || parsed <= 0) return "-";
  return `${(parsed / 1_000_000).toFixed(4)} MHz`;
}

function findBandForFrequency(bands, frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Array.isArray(bands) || !Number.isFinite(parsed) || parsed <= 0) return null;
  return bands.find((band) => parsed >= Number(band.start_hz) && parsed <= Number(band.end_hz)) || null;
}

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
  STARTING_DECODER: "P25 Starting",
  WAITING_FOR_TALKGROUP: "P25 Waiting",
  WAITING_FOR_TRAFFIC: "Waiting for Traffic",
  WAITING_FOR_CHANNEL_START: "Control Hunt",
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
  STARTING_DECODER:"border-triCoreAmber/30 bg-triCoreAmber/10 text-triCoreAmber",
  WAITING_FOR_TALKGROUP: "border-triCoreBlue/30 bg-triCoreBlue/10 text-triCoreBlue",
  WAITING_FOR_TRAFFIC: "border-triCoreBlue/30 bg-triCoreBlue/10 text-triCoreBlue",
  WAITING_FOR_CHANNEL_START: "border-triCoreAmber/30 bg-triCoreAmber/10 text-triCoreAmber",
  READY:          "border-white/15 bg-white/5 text-slate-300",
  LOCKED:         "border-red-400/30 bg-red-500/10 text-red-200",
};

export default function NowListeningCard({ status, dispatchAlert, systemProfile, runtime }) {
  const channel   = status?.active_channel;
  const state     = status?.state || "NO_SIGNAL";
  const power     = Number(status?.signal_power ?? 0);
  const threshold = Number(status?.signal_threshold ?? -35);
  const inDelay   = Boolean(status?.in_delay);
  const held      = Boolean(status?.held);
  const delayed   = Number(status?.delay_remaining ?? 0);
  const runtimeDiagnostics = runtime?.diagnostics || {};

  // Map power to a 0–100 meter value
  const meter = Math.max(0, Math.min(100, (power - threshold + 20) * 2.5));

  const service   = SERVICE_STYLES[channel?.service_type] ?? SERVICE_STYLES.custom;
  const stateStyle = STATE_STYLES[state] ?? STATE_STYLES.NO_SIGNAL;
  const stateLabel = STATE_LABELS[state] ?? state;
  const department = channel?.department || channel?.system || "TriCore Local";
  const primaryRadioId = channel?.primary_radio_id || channel?.source_radio_id || null;
  const targetRadioId = channel?.target_radio_id || null;
  const radioIdLine = primaryRadioId
    ? (targetRadioId && String(targetRadioId) !== String(primaryRadioId)
      ? `${primaryRadioId} / ${targetRadioId}`
      : String(primaryRadioId))
    : "Waiting for radio ID";
  const logo = getAgencyLogo({ ...channel, department });
  const channelMode = channel ? `${channel.delay_seconds}s · ${(channel.modulation || "nfm").toUpperCase()}` : "—";
  const activeSystem = systemProfile?.systems?.[0] || null;
  const activeFrequencyHz = channel?.frequency_hz || activeSystem?.active_control_channel_hz || runtimeDiagnostics?.control_channel_hz || null;
  const activeBand = findBandForFrequency(systemProfile?.bandplan?.featured_bands, activeFrequencyHz);
  const decoder = systemProfile?.decoder_engines?.[0] || null;
  const decoderLabel = decoder?.name || (runtimeDiagnostics?.engine ? String(runtimeDiagnostics.engine).toUpperCase() : "Built-in Decoder");
  const decoderProtocols = Array.isArray(decoder?.protocols) ? decoder.protocols.join(" / ") : "P25 Phase I / Phase II";
  const controlHunts = Number(runtimeDiagnostics?.failover_count || 0);
  const systemTitle = systemProfile?.name || "TriCore SDR";
  const currentSystemName = activeSystem?.name || channel?.system || "TriCore Local";
  const controlFrequency = activeSystem?.active_control_channel_hz || runtimeDiagnostics?.control_channel_hz || null;
  const trackingLabel = channel?.tracking_label || null;
  const trackingCount = Number(channel?.tracking_count || 0);

  return (
    <section className="rounded-[30px] border border-white/10 bg-[#0b141e] p-4 shadow-[0_20px_80px_rgba(0,0,0,0.32)] lg:p-5">
      {dispatchAlert && (
        <div className="mb-4 rounded-[24px] border border-triCoreAmber/30 bg-triCoreAmber/10 px-5 py-4 shadow-[0_0_24px_rgba(255,209,102,0.12)]">
          <div className="text-[11px] font-semibold uppercase tracking-[0.32em] text-triCoreAmber">Dispatch Alert</div>
          <div className="mt-2 text-xl font-semibold text-white">Heard {dispatchAlert.label}</div>
          <div className="mt-1 text-sm text-slate-200">{dispatchAlert.source}</div>
          <div className="mt-1 text-xs text-slate-400">{dispatchAlert.detail} · {dispatchAlert.heardAt}</div>
        </div>
      )}

      <div className="relative overflow-hidden rounded-[24px] border border-white/10 bg-[#0d1621] p-5">
        <div className="absolute inset-0 bg-gradient-to-br from-triCoreBlue/10 via-transparent to-triCoreGreen/10" />
        <div className="absolute right-0 top-0 h-44 w-44 rounded-full bg-triCoreGreen/10 blur-3xl" />
        <div className="relative grid gap-5 xl:grid-cols-[128px_minmax(0,1fr)_220px]">
          <div className="grid gap-3">
            <div className="flex min-h-[128px] flex-col items-center justify-center rounded-[24px] border border-triCoreBlue/20 bg-[#101c2a] px-3 text-center shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
              {logo.src && (
                <img
                  src={logo.src}
                  alt={logo.label}
                  className="h-14 w-14 object-contain"
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                />
              )}
              <span className="mt-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-triCoreBlue">{logo.label}</span>
            </div>

            <div className="rounded-[20px] border border-white/10 bg-black/20 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Signal</div>
              <div className="mt-2 font-mono text-2xl font-semibold text-white">{power.toFixed(1)} dB</div>
              <div className="mt-1 text-xs text-slate-500">Live receiver power</div>
            </div>
          </div>

          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.35em] text-slate-500">{systemTitle}</div>
            <h2 className="mt-3 max-w-4xl truncate font-mono text-3xl font-semibold tracking-[0.05em] text-white lg:text-5xl">
              {channel?.name || "SCAN MODE"}
            </h2>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Department</div>
                <div className="mt-1 text-lg font-semibold text-white">{department}</div>
              </div>
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Radio ID</div>
                <div className="mt-1 font-mono text-lg font-semibold text-white">{radioIdLine}</div>
              </div>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              {channel && (
                <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${service.badge}`}>
                  {service.label}
                </span>
              )}
              {channel?.priority && (
                <span className="rounded-full border border-triCoreAmber/30 bg-triCoreAmber/10 px-3 py-1 text-xs font-semibold text-triCoreAmber">
                  Priority
                </span>
              )}
              {channel?.favorite && (
                <span className="rounded-full border border-triCoreBlue/30 bg-triCoreBlue/10 px-3 py-1 text-xs font-semibold text-triCoreBlue">
                  Favorite
                </span>
              )}
              {held && (
                <span className="rounded-full border border-triCoreAmber/50 bg-triCoreAmber/15 px-3 py-1 text-xs font-semibold text-triCoreAmber">
                  Held
                </span>
              )}
              {inDelay && (
                <span className="rounded-full border border-white/20 bg-white/5 px-3 py-1 text-xs font-semibold text-slate-300">
                  Delay {delayed.toFixed(0)}s
                </span>
              )}
              {activeBand && (
                <span className="rounded-full border border-triCoreGreen/30 bg-triCoreGreen/10 px-3 py-1 text-xs font-semibold text-triCoreGreen">
                  {activeBand.name}
                </span>
              )}
              {trackingLabel && (
                <span className="rounded-full border border-triCoreBlue/30 bg-triCoreBlue/10 px-3 py-1 text-xs font-semibold text-triCoreBlue">
                  Tracking {trackingLabel}{trackingCount ? ` (${trackingCount})` : ""}
                </span>
              )}
              <span className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-semibold text-slate-300">
                {decoderProtocols}
              </span>
              {controlHunts > 0 && (
                <span className="rounded-full border border-triCoreAmber/30 bg-triCoreAmber/10 px-3 py-1 text-xs font-semibold text-triCoreAmber">
                  CC Hunt {controlHunts}
                </span>
              )}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
            <div className={`rounded-[22px] border px-4 py-4 ${stateStyle}`}>
              <div className="text-[11px] font-semibold uppercase tracking-[0.28em] opacity-70">State</div>
              <div className="mt-2 text-2xl font-semibold">{stateLabel}</div>
              <div className="mt-2 text-xs opacity-80">
                {held ? "Hold is keeping this traffic pinned." : inDelay ? `Delay window ${delayed.toFixed(0)}s remaining.` : "Live receiver state."}
              </div>
            </div>

            <div className="rounded-[22px] border border-white/10 bg-black/20 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Threshold</div>
              <div className="mt-2 text-2xl font-semibold text-white">{threshold.toFixed(1)} dB</div>
              <div className="mt-2 text-xs text-slate-500">Quiet gate for the signal meter</div>
            </div>
          </div>
        </div>

        <div className="relative mt-5 grid gap-3 md:grid-cols-4">
          <div className="rounded-[20px] border border-white/10 bg-black/20 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">SDR System</div>
            <div className="mt-1 text-base font-semibold text-white">{systemTitle}</div>
            <div className="mt-1 text-xs text-slate-500">{currentSystemName}</div>
          </div>
          <div className="rounded-[20px] border border-white/10 bg-black/20 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Band / Tune</div>
            <div className="mt-1 text-base font-semibold text-white">{activeBand?.name || "Wideband"}</div>
            <div className="mt-1 text-xs text-slate-500">{formatMHz(activeFrequencyHz)}</div>
          </div>
          <div className="rounded-[20px] border border-white/10 bg-black/20 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Decoder</div>
            <div className="mt-1 text-base font-semibold text-white">{decoderLabel}</div>
            <div className="mt-1 text-xs text-slate-500">{runtimeDiagnostics?.health || runtime?.message || "Idle"}</div>
          </div>
          <div className="rounded-[20px] border border-white/10 bg-black/20 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">Control / Mode</div>
            <div className="mt-1 text-base font-semibold text-white">{formatMHz(controlFrequency)}</div>
            <div className="mt-1 text-xs text-slate-500">{channelMode}</div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="rounded-[24px] border border-white/10 bg-[#0b121a]/80 p-4">
          <div className="mb-2 flex justify-between text-sm text-slate-300">
            <span>Signal Meter</span>
            <span className="tabular-nums">{power.toFixed(1)} dB</span>
          </div>
          <div className="h-6 overflow-hidden rounded-full bg-black/40 ring-1 ring-white/10">
            <div
              className="h-full rounded-full bg-gradient-to-r from-triCoreBlue via-triCoreGreen to-triCoreAmber shadow-[0_0_18px_rgba(101,240,160,0.25)] transition-all duration-150"
              style={{ width: `${meter}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-xs text-slate-500">
            <span>Quiet</span>
            <span>Threshold {threshold.toFixed(1)} dB</span>
            <span>Strong</span>
          </div>
        </div>

        <div className="rounded-[24px] border border-white/10 bg-[#0b121a]/80 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500">RTL Gain</div>
          <div className="mt-2 text-3xl font-bold tabular-nums text-white">
            {status?.gain_db == null ? "Auto" : `${Number(status.gain_db).toFixed(1)}`}
            {status?.gain_db != null && <span className="ml-1 text-lg font-normal text-slate-400">dB</span>}
          </div>
          <div className="mt-1 text-xs text-slate-500">Receiver sensitivity</div>
        </div>
      </div>
    </section>
  );
}
