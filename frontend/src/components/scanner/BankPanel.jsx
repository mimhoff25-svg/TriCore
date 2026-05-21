import { Check, ChevronDown, FolderOpen, Radio, X } from "lucide-react";

function formatMHz(frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Number.isFinite(parsed) || parsed <= 0) return "--.----";
  return (parsed / 1_000_000).toFixed(4);
}

function channelCountLabel(channels) {
  const available = channels.filter((channel) => !channel.unavailable && !channel.encrypted).length;
  return `${available}/${channels.length}`;
}

export default function BankPanel({
  banks = [],
  channels = [],
  activeChannel,
  onEnable,
  onDisable,
  onTune,
}) {
  const channelsByBank = new Map();
  for (const channel of channels) {
    const list = channelsByBank.get(channel.bank_id) || [];
    list.push(channel);
    channelsByBank.set(channel.bank_id, list);
  }

  return (
    <aside className="rounded-lg border border-white/10 bg-[#101720]">
      <div className="border-b border-white/10 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
          <FolderOpen className="h-4 w-4 text-triCoreBlue" />
          Scan Bins
        </div>
        <div className="mt-1 text-xs text-slate-500">Open a bin, then pick a channel.</div>
      </div>

      <div className="max-h-[36vh] overflow-y-auto p-2">
        {banks.map((bank) => {
          const bankChannels = (channelsByBank.get(bank.id) || [])
            .slice()
            .sort((a, b) => Number(a.frequency_hz) - Number(b.frequency_hz) || a.name.localeCompare(b.name));
          const activeInBank = bankChannels.some((channel) => channel.id === activeChannel?.id);

          return (
            <details
              key={bank.id}
              open={activeInBank}
              className={`mb-2 rounded-lg border ${bank.enabled ? "border-triCoreGreen/25 bg-triCoreGreen/5" : "border-white/10 bg-black/20 opacity-75"}`}
            >
              <summary className="flex cursor-pointer list-none items-center gap-2 p-3">
                <ChevronDown className="h-4 w-4 shrink-0 text-slate-500" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-semibold text-white">{bank.name}</div>
                    <div className="font-mono text-[11px] text-slate-500">{channelCountLabel(bankChannels)}</div>
                  </div>
                  <div className="mt-1 truncate text-xs text-slate-500">{bank.description}</div>
                </div>
                <button
                  type="button"
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    (bank.enabled ? onDisable : onEnable)?.(bank.id);
                  }}
                  aria-label={bank.enabled ? `Disable ${bank.name}` : `Enable ${bank.name}`}
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded border ${bank.enabled ? "border-triCoreGreen/30 bg-triCoreGreen/10 text-triCoreGreen" : "border-white/10 bg-white/5 text-slate-300"}`}
                >
                  {bank.enabled ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
                </button>
              </summary>

              <div className="border-t border-white/10 p-2">
                <select
                  value={activeInBank ? activeChannel.id : ""}
                  onChange={(event) => event.target.value && onTune?.(event.target.value)}
                  className="mb-2 w-full rounded-md border border-white/10 bg-[#0a0f18] px-2 py-2 text-sm text-slate-100 outline-none focus:border-triCoreGreen/50"
                >
                  <option value="">Select {bank.name}</option>
                  {bankChannels.map((channel) => (
                    <option key={channel.id} value={channel.id} disabled={channel.unavailable || channel.encrypted || channel.locked_out}>
                      {formatMHz(channel.frequency_hz)} - {channel.name}
                    </option>
                  ))}
                </select>

                <div className="grid gap-1">
                  {bankChannels.map((channel) => {
                    const active = channel.id === activeChannel?.id;
                    const disabled = channel.unavailable || channel.encrypted || channel.locked_out;
                    return (
                      <button
                        key={channel.id}
                        type="button"
                        disabled={disabled}
                        onClick={() => onTune?.(channel.id)}
                        className={`flex items-center gap-2 rounded-md border px-2 py-2 text-left transition ${
                          active
                            ? "border-triCoreGreen/60 bg-triCoreGreen/20 text-white"
                            : disabled
                              ? "border-white/5 bg-black/10 text-slate-600"
                              : "border-transparent bg-black/10 text-slate-300 hover:border-white/15 hover:bg-white/5"
                        }`}
                      >
                        <Radio className={`h-3.5 w-3.5 shrink-0 ${active ? "text-triCoreGreen" : "text-slate-500"}`} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs font-semibold">{channel.name}</div>
                          <div className="font-mono text-[11px] text-slate-500">{formatMHz(channel.frequency_hz)} MHz</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </aside>
  );
}
