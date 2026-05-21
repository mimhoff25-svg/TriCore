import { AlertTriangle, Radio } from "lucide-react";

function formatFrequencyValue(frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Number.isFinite(parsed) || parsed <= 0) return "--.----";
  return (parsed / 1_000_000).toFixed(4);
}

function scannerState(status) {
  return status?.scanner_state || "Stopped";
}

function titleCase(value) {
  return String(value || "--").replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function voiceBars(audioLevel) {
  return Math.round(clamp(Number(audioLevel || 0) * 2.3, 0, 1) * 10);
}

function signalBars(level) {
  return Math.round(clamp((Number(level) + 100) / 60, 0, 1) * 10);
}

function sUnitFromDb(level) {
  if (level < -93) return "S0";
  const s = Math.floor((level + 93) / 6) + 1;
  if (s <= 9) return `S${clamp(s, 1, 9)}`;
  return `S9+${Math.max(0, Math.round(level + 39))}`;
}

function SegmentMeter({ bars, color = "green", label }) {
  const activeClass = color === "blue" ? "is-blue" : "is-green";

  return (
    <div className="scanner-segment-meter" aria-label={label}>
      {Array.from({ length: 10 }, (_, index) => (
        <span key={index} className={index < bars ? activeClass : ""} />
      ))}
    </div>
  );
}

function MeterRow({ label, value, note, bars, color = "green", active = false }) {
  const toneClass = active
    ? color === "blue"
      ? "text-[#66d1ff]"
      : "text-[#b6ff84]"
    : "text-slate-500";

  return (
    <div className="scanner-meter-row">
      <div>
        <div className="scanner-meter-kicker">{label}</div>
        <div className="scanner-meter-value">{value}</div>
      </div>
      <SegmentMeter bars={bars} color={color} label={`${label} ${bars} of 10 bars`} />
      <div className={`scanner-meter-note ${toneClass}`}>{note}</div>
    </div>
  );
}

export default function NowListeningCard({ status, audioLevel = 0, onLockChannel = null, selectedTalkgroup = null }) {
  const channel = status?.current_channel || status?.active_channel || null;
  const frequencyHz = status?.current_frequency_hz || channel?.frequency_hz || null;
  const receiverMode = status?.receiver_mode || (status?.simulated ? "Demo" : "RTL-SDR");
  const unavailable = Boolean(channel?.unavailable || channel?.encrypted);
  const state = scannerState(status);
  const gainText = status?.gain_db == null ? "Auto" : `${Number(status.gain_db).toFixed(1)} dB`;
  const currentBank = channel?.bank_name || titleCase(channel?.bank_id);
  const currentService = titleCase(channel?.service_type);
  const modulation = String(channel?.modulation || "--").replace("_placeholder", "").toUpperCase();
  const mutedText = status?.is_muted ? "Muted" : "Live";
  const systemName = channel?.system_name || channel?.system || "TriCore Scanner";
  const signalLevel = Number(status?.signal_level ?? -100);
  const squelchLevel = Number(status?.squelch_db ?? -65);
  const voicePercent = Math.round(clamp(Number(audioLevel || 0) * 100, 0, 100));
  const voiceActive = Number(audioLevel) > 0.035;
  const isP25 = channel?.modulation === "p25_placeholder";
  const decoderLabel = isP25 ? status?.decoder?.label || "Managed P25 Runtime" : null;
  const decoderMessage = isP25 ? String(status?.decoder?.message || status?.message || "").trim() : "";
  const decoderRuntime = isP25 && status?.decoder?.runtime && typeof status.decoder.runtime === "object"
    ? status.decoder.runtime
    : null;
  const p25TunerDetail = isP25 ? String(decoderRuntime?.error_detail || "").trim() : "";
  const decoderSummary = isP25 && p25TunerDetail && decoderMessage.endsWith(p25TunerDetail)
    ? decoderMessage.slice(0, Math.max(0, decoderMessage.length - p25TunerDetail.length)).trim()
    : decoderMessage;
  const p25SyncState = isP25 ? titleCase(status?.decoder?.sync_state || "idle") : null;
  const p25Talkgroup = isP25 ? status?.decoder?.talkgroup_decimal || channel?.p25_talkgroup_decimal || null : null;
  const p25SelectedTalkgroup = isP25 && selectedTalkgroup && typeof selectedTalkgroup === "object"
    ? selectedTalkgroup
    : null;
  const p25SourceId = isP25 ? status?.decoder?.source_radio_id || null : null;
  const p25TargetId = isP25 ? status?.decoder?.target_radio_id || null : null;
  const p25RecentRadios = isP25 && Array.isArray(status?.decoder?.recent_radios)
    ? status.decoder.recent_radios.filter((item) => item && typeof item === "object")
    : [];
  const p25Phase = isP25 ? status?.decoder?.phase || null : null;
  const p25Nac = isP25 ? status?.decoder?.nac || null : null;
  const p25VoiceFrequencyHz = isP25 ? Number(status?.decoder?.voice_frequency_hz || 0) || null : null;
  const p25ControlFrequencyHz = isP25
    ? Number(status?.decoder?.control_channel_hz || channel?.p25_control_channels_hz?.[0] || channel?.frequency_hz || 0) || null
    : null;
  const p25SyncNote = !isP25
    ? ""
    : p25VoiceFrequencyHz
      ? `Voice ${formatFrequencyValue(p25VoiceFrequencyHz)} MHz • Control ${formatFrequencyValue(p25ControlFrequencyHz)} MHz`
      : p25ControlFrequencyHz
        ? `${p25SyncState} • Control ${formatFrequencyValue(p25ControlFrequencyHz)} MHz`
        : (p25SyncState || "");
  const p25StationName = !isP25
    ? ""
    : String(
        p25SelectedTalkgroup?.alpha_tag
        || (channel?.p25_talkgroup_decimal ? channel?.name : null)
        || channel?.department
        || channel?.category
        || currentService
        || "--",
      ).trim();
  const p25Department = !isP25
    ? ""
    : String(
        channel?.department
        || channel?.category
        || currentService
        || currentBank
        || "--",
      ).trim();
  const p25RecentRadio = !isP25
    ? null
    : [...p25RecentRadios].reverse().find((item) => {
        const radioValue = Number(item?.radio);
        if (!Number.isFinite(radioValue) || radioValue <= 0) {
          return false;
        }
        if (!Number.isFinite(Number(p25Talkgroup)) || Number(p25Talkgroup) <= 0) {
          return true;
        }
        return Number(item?.group) === Number(p25Talkgroup);
      }) || [...p25RecentRadios].reverse().find((item) => {
        const radioValue = Number(item?.radio);
        return Number.isFinite(radioValue) && radioValue > 0;
      }) || null;
  const p25RecentRadioId = p25RecentRadio?.radio != null ? String(p25RecentRadio.radio).trim() : null;
  const p25DisplayTargetId = isP25 && p25TargetId && String(p25TargetId) !== String(p25Talkgroup || "")
    ? String(p25TargetId).trim()
    : null;
  const p25RadioId = isP25 ? String(p25SourceId || p25RecentRadioId || p25DisplayTargetId || "--").trim() : "";
  const p25MetaItems = !isP25
    ? []
    : [
        p25Talkgroup ? ["TGID", String(p25Talkgroup)] : null,
        currentBank ? ["Bank", currentBank] : null,
        receiverMode ? ["Receiver", receiverMode] : null,
        mutedText ? ["Audio", mutedText] : null,
        p25SyncState ? ["Sync", p25SyncState] : null,
        p25VoiceFrequencyHz ? ["Voice", `${formatFrequencyValue(p25VoiceFrequencyHz)} MHz`] : null,
        p25ControlFrequencyHz ? ["Control", `${formatFrequencyValue(p25ControlFrequencyHz)} MHz`] : null,
        p25DisplayTargetId && p25DisplayTargetId !== p25RadioId ? ["Target", p25DisplayTargetId] : null,
        p25Phase ? ["Phase", p25Phase] : null,
        p25Nac ? ["NAC", p25Nac] : null,
      ].filter(Boolean);
  const p25BusyDevices = Array.isArray(decoderRuntime?.busy_device_numbers)
    ? decoderRuntime.busy_device_numbers
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value) && value > 0)
    : [];
  const p25DiagnosticRows = !isP25
    ? []
    : [
        decoderRuntime?.health ? ["Health", titleCase(decoderRuntime.health)] : null,
        Number.isFinite(Number(decoderRuntime?.device_count)) && Number(decoderRuntime.device_count) > 0
          ? ["RTL Devices", String(Number(decoderRuntime.device_count))]
          : null,
        p25BusyDevices.length ? ["Busy Devices", p25BusyDevices.map((value) => `#${value}`).join(", ")] : null,
        Number.isFinite(Number(decoderRuntime?.selected_device_number)) && Number(decoderRuntime.selected_device_number) > 0
          ? ["Chosen Device", `#${Number(decoderRuntime.selected_device_number)}`]
          : null,
        decoderRuntime?.selected_serial ? ["Chosen Serial", String(decoderRuntime.selected_serial)] : null,
        decoderRuntime?.audio_output_name ? ["DSD+ Audio", String(decoderRuntime.audio_output_name)] : null,
        Number.isFinite(Number(decoderRuntime?.audio_output_device)) && Number(decoderRuntime.audio_output_device) > 0
          ? ["DSD+ Output", `#${Number(decoderRuntime.audio_output_device)}`]
          : null,
        decoderRuntime?.failing_serial ? ["Failing Serial", String(decoderRuntime.failing_serial)] : null,
      ].filter(Boolean);
  const canLockChannel = Boolean(channel && !unavailable && typeof onLockChannel === "function");
  const isLocked = Boolean(status?.is_holding || status?.state === "manual_tune");
  const lockPrompt = !canLockChannel
    ? ""
    : isLocked
      ? (isP25 ? "Talkgroup locked" : "Channel locked")
      : (isP25 ? "Click display to lock this talkgroup" : "Click display to lock this channel");
  const detailRows = isP25
    ? []
    : [
        ["Bank", currentBank],
        ["Service", currentService],
        ["Receiver", receiverMode],
        ["Audio", mutedText],
        ...(decoderLabel ? [["Decoder", decoderLabel]] : []),
      ];

  return (
    <section className="scanner-housing rounded-[30px] p-[1px] shadow-[0_26px_90px_rgba(0,0,0,0.42)]">
      <div className="scanner-bezel rounded-[29px] p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-triCoreGreen/25 bg-black/30 text-triCoreGreen shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
              <Radio className="h-5 w-5" />
            </div>
            <div>
              <div className="scanner-eyebrow">Now Listening</div>
              <div className="scanner-caption">Field monitor front panel</div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="scanner-indicator is-neutral">{titleCase(state)}</span>
            <span className={`scanner-indicator ${status?.is_muted ? "is-warn" : ""}`}>{mutedText}</span>
            <span className="scanner-indicator is-neutral">{receiverMode}</span>
          </div>
        </div>

        {(unavailable || status?.error_message) && (
          <div className="mt-4 flex items-start gap-2 rounded-2xl border border-triCoreAmber/30 bg-[rgba(74,48,8,0.45)] px-3 py-2 text-sm text-triCoreAmber">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{unavailable ? "Unavailable channel skipped." : status.error_message}</span>
          </div>
        )}

        <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_260px]">
          <button
            type="button"
            disabled={!canLockChannel}
            onClick={() => onLockChannel?.()}
            title={lockPrompt}
            className={`scanner-display w-full text-left ${canLockChannel ? "cursor-pointer transition hover:-translate-y-[1px] hover:shadow-[0_0_0_1px_rgba(182,255,132,0.14)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#b6ff84]/35" : "cursor-default"}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="scanner-display-label">Dispatch Display</div>
                <div className="scanner-display-system truncate">{systemName}</div>
              </div>
              <div className="flex items-center gap-2">
                {canLockChannel ? (
                  <span className={`scanner-indicator ${isLocked ? "is-warn" : "is-neutral"}`}>{isLocked ? "Locked" : "Click To Lock"}</span>
                ) : null}
                <div className="scanner-mode-window">{modulation}</div>
              </div>
            </div>

            {isP25 ? (
              <>
                <div className="scanner-frequency break-words">
                  <span>{p25StationName}</span>
                </div>

                <div className="mt-4 grid gap-3">
                  <div className="rounded-2xl border border-white/10 bg-black/20 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Department</div>
                    <div className="mt-1 break-words text-xl font-semibold text-white">{p25Department}</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-black/20 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Radio ID</div>
                    <div className="mt-1 break-words font-mono text-xl font-semibold text-white">{p25RadioId}</div>
                  </div>
                </div>

                {p25MetaItems.length ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {p25MetaItems.map(([label, value]) => (
                      <div key={label} className="min-w-[110px] rounded-xl border border-white/8 bg-black/20 px-3 py-2">
                        <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
                        <div className="mt-1 break-words text-sm font-semibold text-[#f5ffd8]">{value}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <div className="scanner-frequency">
                  <span>{formatFrequencyValue(frequencyHz)}</span>
                  <small>MHz</small>
                </div>

                <div className="mt-4 min-w-0">
                  <div className="scanner-channel truncate">{channel?.name || "No Channel Selected"}</div>
                  <div className="scanner-system-line truncate">{currentBank} • {currentService}</div>
                </div>
              </>
            )}

            {(p25SyncNote || decoderSummary) ? (
              <div className="mt-4 rounded-2xl border border-[#b6ff84]/15 bg-black/20 px-3 py-2 text-xs font-medium text-[#e8ffd6]">
                {p25SyncNote ? (
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[#b6ff84]">{p25SyncNote}</div>
                ) : null}
                {decoderSummary ? (
                  <div className={p25SyncNote ? "mt-1" : ""}>{decoderSummary}</div>
                ) : null}
              </div>
            ) : null}

            {(p25TunerDetail || p25DiagnosticRows.length) ? (
              <div className="mt-3 rounded-2xl border border-triCoreAmber/25 bg-[rgba(74,48,8,0.32)] px-3 py-3 text-xs text-[#ffe6ad]">
                <div className="text-[11px] uppercase tracking-[0.16em] text-triCoreAmber">P25 Tuner Diagnostics</div>
                {p25TunerDetail ? (
                  <div className="mt-2 leading-5 text-[#fff4d7]">{p25TunerDetail}</div>
                ) : null}
                {p25DiagnosticRows.length ? (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {p25DiagnosticRows.map(([label, value]) => (
                      <div key={label} className="rounded-xl border border-white/8 bg-black/20 px-2 py-2">
                        <div className="text-[10px] uppercase tracking-[0.14em] text-slate-400">{label}</div>
                        <div className="mt-1 break-words text-[13px] font-semibold text-white">{value}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {detailRows.length ? (
              <div className="scanner-readout-grid">
                {detailRows.map(([label, value]) => (
                  <div key={label} className="scanner-readout-row">
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
            ) : null}
          </button>

          <aside className="scanner-sidecar">
            <div className="scanner-speaker-grill" aria-hidden="true">
              {Array.from({ length: 7 }, (_, index) => <span key={index} />)}
            </div>
            <div className="scanner-speaker-label">Speaker</div>

            <div className="scanner-meter-panel">
              <MeterRow
                label="RF"
                value={sUnitFromDb(signalLevel)}
                note={signalLevel >= squelchLevel ? "Open" : "Quiet"}
                bars={signalBars(signalLevel)}
                active={signalLevel >= squelchLevel}
              />
              <MeterRow
                label="Audio"
                value={`${voicePercent}%`}
                note={voiceActive ? "Voice" : "Standby"}
                bars={voiceBars(audioLevel)}
                color="blue"
                active={voiceActive}
              />

              <div className="scanner-dial-row">
                <div className="scanner-dial">
                  <span>Gain</span>
                  <strong>{gainText}</strong>
                </div>
                <div className="scanner-dial">
                  <span>Squelch</span>
                  <strong>{squelchLevel.toFixed(0)} dB</strong>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </section>
  );
}
