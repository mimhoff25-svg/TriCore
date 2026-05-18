function formatMHz(frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Number.isFinite(parsed) || parsed <= 0) return "--.----";
  return (parsed / 1_000_000).toFixed(4);
}

function channelStatus(channel) {
  if (channel.unavailable || channel.encrypted) return "Unavailable";
  if (channel.locked_out) return "Hidden";
  return "Ready";
}

export default function ChannelChart({ channels = [], banks = [], activeChannel, onTune }) {
  const bankNames = new Map(banks.map((bank) => [bank.id, bank.name]));

  return (
    <section className="rounded-lg border border-white/10 bg-[#101720]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">Station Chart</div>
          <div className="mt-1 text-xs text-slate-500">{channels.length} configured channels</div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-black/25 text-xs uppercase tracking-[0.12em] text-slate-500">
            <tr>
              <th className="px-3 py-2">Bank</th>
              <th className="px-3 py-2">Service</th>
              <th className="px-3 py-2">Channel</th>
              <th className="px-3 py-2">Frequency</th>
              <th className="px-3 py-2">Modulation</th>
              <th className="px-3 py-2">Signal</th>
              <th className="px-3 py-2">Priority</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((channel) => {
              const active = activeChannel?.id === channel.id;
              const status = channelStatus(channel);
              return (
                <tr
                  key={channel.id}
                  onClick={() => onTune?.(channel.id)}
                  className={`cursor-pointer border-t border-white/5 hover:bg-white/5 ${active ? "bg-triCoreGreen/10" : ""}`}
                >
                  <td className="px-3 py-2 text-slate-300">{bankNames.get(channel.bank_id) || channel.bank_id}</td>
                  <td className="px-3 py-2 text-slate-400">{channel.service_type}</td>
                  <td className="px-3 py-2 font-semibold text-white">{channel.name}</td>
                  <td className="px-3 py-2 font-mono text-slate-200">{formatMHz(channel.frequency_hz)} MHz</td>
                  <td className="px-3 py-2 uppercase text-slate-400">{channel.modulation}</td>
                  <td className="px-3 py-2 font-mono text-slate-400">{Number(channel.signal_level ?? -100).toFixed(1)} dB</td>
                  <td className="px-3 py-2 text-slate-400">{channel.priority ? "Priority" : ""}</td>
                  <td className={`px-3 py-2 font-semibold ${status === "Ready" ? "text-triCoreGreen" : status === "Hidden" ? "text-triCoreAmber" : "text-red-300"}`}>
                    {status}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

