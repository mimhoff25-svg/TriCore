import { RadioTower, Waves, Waypoints } from "lucide-react";

function formatFrequency(frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Number.isFinite(parsed) || parsed <= 0) return "--.----";
  return `${(parsed / 1_000_000).toFixed(4)} MHz`;
}

function titleCase(value) {
  return String(value || "--").replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export default function ActiveScanChannelCard({ status, selectedTalkgroup = null }) {
  const scanActive = Boolean(status?.is_scanning || status?.is_holding || status?.is_paused);
  const currentChannel = status?.current_channel || null;
  const channel = status?.active_channel || currentChannel || null;

  if (!scanActive || !channel) {
    return null;
  }

  const isP25 = String(currentChannel?.modulation || channel?.modulation || "").toLowerCase() === "p25_placeholder";
  const talkgroupDecimal = Number(
    status?.decoder?.talkgroup_decimal
      || selectedTalkgroup?.decimal
      || currentChannel?.p25_talkgroup_decimal
      || channel?.p25_talkgroup_decimal
      || 0,
  ) || null;
  const headline = isP25
    ? String(selectedTalkgroup?.alpha_tag || currentChannel?.name || channel?.name || "GATRRS Scan").trim()
    : String(channel?.name || currentChannel?.name || "Current Channel").trim();
  const systemName = String(currentChannel?.system_name || channel?.system_name || "TriCore Scanner").trim();
  const modulation = String(currentChannel?.modulation || channel?.modulation || "--").replace("_placeholder", "").toUpperCase();
  const bankName = String(channel?.bank_name || channel?.bank_id || currentChannel?.bank_id || "--").replace(/-/g, " ");
  const scanLabel = status?.is_holding
    ? "Locked Scan"
    : status?.is_paused
      ? "Paused Scan"
      : "Current Scan Hit";
  const syncState = isP25 ? titleCase(status?.decoder?.sync_state || "control_lock") : titleCase(status?.scanner_state || "scanning");
  const voiceFrequency = Number(status?.decoder?.voice_frequency_hz || 0) || null;
  const displayFrequency = voiceFrequency || Number(status?.current_frequency_hz || channel?.frequency_hz || 0) || null;

  return (
    <section className="rounded-[26px] border border-triCoreBlue/20 bg-[radial-gradient(circle_at_top,#14263c,rgba(9,13,18,0.94)_65%)] p-4 shadow-[0_24px_80px_rgba(0,0,0,0.38)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[#7db8ff]">{scanLabel}</div>
          <div className="mt-1 text-xs text-slate-400">{systemName}</div>
        </div>
        <div className="rounded-full border border-white/10 bg-black/25 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-200">
          {syncState}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="rounded-2xl border border-white/10 bg-black/25 p-4">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            <RadioTower className="h-4 w-4 text-triCoreGreen" />
            Active Channel
          </div>
          <div className="mt-3 break-words text-2xl font-semibold text-white sm:text-[2rem]">{headline || "--"}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-300">
            <span>{formatFrequency(displayFrequency)}</span>
            <span className="text-slate-600">|</span>
            <span>{modulation}</span>
            {talkgroupDecimal ? (
              <>
                <span className="text-slate-600">|</span>
                <span>TGID {talkgroupDecimal}</span>
              </>
            ) : null}
          </div>
        </div>

        <div className="grid gap-3">
          <div className="rounded-2xl border border-white/10 bg-black/25 p-3">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              <Waypoints className="h-4 w-4 text-triCoreBlue" />
              Scan Source
            </div>
            <div className="mt-2 text-sm font-semibold text-white">{titleCase(bankName)}</div>
            <div className="mt-1 text-xs text-slate-400">{titleCase(channel?.service_type || currentChannel?.service_type || "public_safety")}</div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-black/25 p-3">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              <Waves className="h-4 w-4 text-triCoreAmber" />
              Voice Follow
            </div>
            <div className="mt-2 text-sm font-semibold text-white">{voiceFrequency ? formatFrequency(voiceFrequency) : "Control channel watch"}</div>
            <div className="mt-1 text-xs text-slate-400">{voiceFrequency ? "Live voice frequency tracked" : "Waiting for next active grant"}</div>
          </div>
        </div>
      </div>
    </section>
  );
}