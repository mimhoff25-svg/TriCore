import { Check, Layers, X } from "lucide-react";

export default function BankPanel({ banks = [], onEnable, onDisable }) {
  return (
    <aside className="rounded-lg border border-white/10 bg-[#101720]">
      <div className="border-b border-white/10 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
          <Layers className="h-4 w-4 text-triCoreBlue" />
          Banks
        </div>
      </div>
      <div className="max-h-[64vh] overflow-y-auto p-2">
        {banks.map((bank) => (
          <div key={bank.id} className={`mb-2 rounded-lg border p-3 ${bank.enabled ? "border-triCoreGreen/25 bg-triCoreGreen/5" : "border-white/10 bg-black/20 opacity-70"}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-white">{bank.name}</div>
                <div className="mt-1 line-clamp-2 text-xs text-slate-500">{bank.description}</div>
              </div>
              <button
                onClick={() => (bank.enabled ? onDisable?.(bank.id) : onEnable?.(bank.id))}
                aria-label={bank.enabled ? `Disable ${bank.name}` : `Enable ${bank.name}`}
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded border ${bank.enabled ? "border-triCoreGreen/30 bg-triCoreGreen/10 text-triCoreGreen" : "border-white/10 bg-white/5 text-slate-300"}`}
              >
                {bank.enabled ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

