import React, { useEffect, useMemo, useRef } from "react";

function formatTime(isoString) {
  if (!isoString) return "";
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatFreq(hz) {
  if (!hz) return "";
  return (hz / 1_000_000).toFixed(4) + " MHz";
}

export default function RadioLog({ transcripts, transcriptStatus, onStart, onStop, onClear }) {
  const bottomRef = useRef(null);

  const rankedTranscripts = useMemo(() => {
    const list = Array.isArray(transcripts) ? [...transcripts] : [];
    return list.sort((a, b) => {
      const prioA = Number(a?.priority || 1);
      const prioB = Number(b?.priority || 1);
      if (prioA !== prioB) return prioB - prioA;
      return String(b?.timestamp || "").localeCompare(String(a?.timestamp || ""));
    });
  }, [transcripts]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcripts?.length]);

  const running = transcriptStatus?.running;
  const current = transcriptStatus?.current_channel;
  const error = transcriptStatus?.error;

  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-white/10 bg-[#0d1b2a]/70 p-4 backdrop-blur-md">
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-widest text-triCoreAmber">
            Radio Log
          </span>
          {running && (
            <span className="flex items-center gap-1 rounded-full bg-triCoreGreen/15 px-2 py-0.5 text-[10px] font-medium text-triCoreGreen">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-triCoreGreen" />
              {current ? current : "Listening"}
            </span>
          )}
          {error && (
            <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">
              {error}
            </span>
          )}
        </div>
        <div className="flex gap-2">
          {!running ? (
            <button
              onClick={onStart}
              className="rounded-lg bg-triCoreGreen/20 px-3 py-1 text-xs font-semibold text-triCoreGreen transition hover:bg-triCoreGreen/30 active:scale-95"
            >
              Start
            </button>
          ) : (
            <button
              onClick={onStop}
              className="rounded-lg bg-red-500/20 px-3 py-1 text-xs font-semibold text-red-400 transition hover:bg-red-500/30 active:scale-95"
            >
              Stop
            </button>
          )}
          <button
            onClick={onClear}
            className="rounded-lg bg-white/5 px-3 py-1 text-xs font-semibold text-white/50 transition hover:bg-white/10 active:scale-95"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Transcript list */}
      <div className="flex max-h-52 flex-col gap-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-white/10">
        {(!rankedTranscripts || rankedTranscripts.length === 0) && (
          <p className="py-4 text-center text-xs text-white/30">
            {running ? "Waiting for voice traffic…" : "Start transcription to log radio chatter."}
          </p>
        )}
        {rankedTranscripts?.map((entry, i) => (
          <div key={i} className="flex flex-col gap-0.5 rounded-lg bg-white/[0.03] px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-semibold text-triCoreBlue">
                {entry.channel_name}
              </span>
              <span className="text-[10px] text-white/30">
                {formatFreq(entry.frequency_hz)} &middot; {formatTime(entry.timestamp)}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-1">
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${Number(entry.priority || 1) >= 4 ? "bg-red-500/20 text-red-300" : Number(entry.priority || 1) >= 3 ? "bg-triCoreAmber/20 text-triCoreAmber" : "bg-white/10 text-white/60"}`}>
                P{entry.priority || 1}
              </span>
              {entry.call_type && (
                <span className="rounded-full bg-triCoreBlue/15 px-2 py-0.5 text-[10px] font-semibold text-triCoreBlue">
                  {String(entry.call_type).replace(/_/g, " ")}
                </span>
              )}
              {Array.isArray(entry.tags) && entry.tags.slice(0, 2).map((tag) => (
                <span key={`${entry.timestamp}-${tag}`} className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/60">
                  {tag}
                </span>
              ))}
            </div>
            <p className="text-xs leading-snug text-white/80">{entry.text}</p>
            {entry.summary && (
              <p className="text-[10px] text-white/45">{entry.summary}</p>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
