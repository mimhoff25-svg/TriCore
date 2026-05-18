from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from .models import Channel
from .windows_rtlsdr_tools import find_runtime_tool

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK_SECONDS = 3
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS
SILENCE_THRESHOLD = 200  # int16 RMS below this = skip

_model = None
_model_lock = threading.Lock()


def _get_model(model_size: str = "base"):
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            logger.info("Loading Whisper model '%s'...", model_size)
            _model = WhisperModel(model_size, device="cpu", compute_type="int8")
            logger.info("Whisper model loaded.")
    return _model


class TranscriptEntry:
    __slots__ = (
        "timestamp",
        "channel_name",
        "frequency_hz",
        "text",
        "call_type",
        "priority",
        "confidence",
        "tags",
        "summary",
    )

    def __init__(
        self,
        channel_name: str,
        frequency_hz: int,
        text: str,
        call_type: str,
        priority: int,
        confidence: float,
        tags: list[str],
        summary: str,
    ):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.text = text
        self.call_type = call_type
        self.priority = priority
        self.confidence = confidence
        self.tags = tags
        self.summary = summary

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "channel_name": self.channel_name,
            "frequency_hz": self.frequency_hz,
            "text": self.text,
            "call_type": self.call_type,
            "priority": self.priority,
            "confidence": self.confidence,
            "tags": self.tags,
            "summary": self.summary,
        }


class RadioTranscriber:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self.running = False
        self.current_channel: Optional[Channel] = None
        self.error: Optional[str] = None
        self.transcripts: deque[TranscriptEntry] = deque(maxlen=200)
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._channel_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self, channels: list[Channel]) -> dict:
        nfm_channels = [c for c in channels if c.modulation.lower() != "wfm"]
        if not nfm_channels:
            return {"ok": False, "error": "No NFM channels available to transcribe."}

        rtl_fm = find_runtime_tool("rtl_fm")
        if rtl_fm is None:
            return {"ok": False, "error": "rtl_fm.exe not found. Check runtime tools."}

        if self.running:
            return {"ok": False, "error": "Transcriber already running."}

        self._stop_event.clear()
        self.error = None
        self.running = True
        self._thread = threading.Thread(
            target=self._scan_loop,
            args=(nfm_channels, str(rtl_fm)),
            daemon=True,
            name="transcriber",
        )
        self._thread.start()
        return {"ok": True, "channels": len(nfm_channels)}

    def stop(self):
        self._stop_event.set()
        self._kill_proc()
        self.running = False
        self.current_channel = None

    def get_transcripts(self) -> list[dict]:
        return [e.to_dict() for e in self.transcripts]

    def clear_transcripts(self):
        self.transcripts.clear()

    def status(self) -> dict:
        with self._channel_lock:
            ch = self.current_channel
        return {
            "running": self.running,
            "error": self.error,
            "transcript_count": len(self.transcripts),
            "current_channel": ch.name if ch else None,
            "current_frequency_hz": ch.frequency_hz if ch else None,
        }

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _kill_proc(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    def _scan_loop(self, channels: list[Channel], rtl_fm_path: str):
        model = _get_model(self.model_size)
        idx = 0
        while not self._stop_event.is_set():
            channel = channels[idx % len(channels)]
            idx += 1
            with self._channel_lock:
                self.current_channel = channel

            try:
                self._listen_channel(channel, rtl_fm_path, model)
            except Exception as exc:
                logger.warning("Transcriber error on %s: %s", channel.name, exc)
                self.error = str(exc)
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        self.running = False
        with self._channel_lock:
            self.current_channel = None

    def _listen_channel(self, channel: Channel, rtl_fm_path: str, model):
        cmd = [
            rtl_fm_path,
            "-f", str(channel.frequency_hz),
            "-M", "fm",
            "-s", str(SAMPLE_RATE),
            "-r", str(SAMPLE_RATE),
            "-g", "40",
            "-",
        ]
        logger.debug("rtl_fm cmd: %s", " ".join(cmd))

        dwell = max(channel.delay_seconds, 4.0)
        deadline = time.monotonic() + dwell

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

        audio_buf = bytearray()
        bytes_per_chunk = CHUNK_SAMPLES * 2  # int16 = 2 bytes

        try:
            while not self._stop_event.is_set() and time.monotonic() < deadline:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                audio_buf.extend(chunk)

                while len(audio_buf) >= bytes_per_chunk:
                    raw = bytes(audio_buf[:bytes_per_chunk])
                    audio_buf = audio_buf[bytes_per_chunk:]
                    self._transcribe_chunk(raw, channel, model)
        finally:
            self._kill_proc()

    def _transcribe_chunk(self, raw_int16: bytes, channel: Channel, model):
        arr = np.frombuffer(raw_int16, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(arr ** 2)))
        if rms * 32768 < SILENCE_THRESHOLD:
            return  # silence — skip

        segments, _ = model.transcribe(
            arr,
            language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            beam_size=1,
        )
        words = " ".join(s.text.strip() for s in segments).strip()
        if words:
            triage = self._triage_call(words, channel)
            entry = TranscriptEntry(
                channel_name=channel.name,
                frequency_hz=channel.frequency_hz,
                text=words,
                call_type=triage["call_type"],
                priority=triage["priority"],
                confidence=triage["confidence"],
                tags=triage["tags"],
                summary=triage["summary"],
            )
            self.transcripts.append(entry)
            logger.info("[%s] %s", channel.name, words)

    def _triage_call(self, text: str, channel: Channel) -> dict:
        lowered = text.lower()
        tags: list[str] = []
        score = 20
        call_type = "routine"

        critical_keywords = (
            "officer down",
            "shots fired",
            "active shooter",
            "mayday",
            "structure fire",
            "working fire",
            "cardiac arrest",
            "not breathing",
            "man down",
        )
        urgent_keywords = (
            "pursuit",
            "fight",
            "assault",
            "robbery",
            "burglary",
            "wreck",
            "accident",
            "injury",
            "overdose",
            "priority",
            "backup",
            "code 3",
        )
        service = str(channel.service_type or "").lower()

        if any(keyword in lowered for keyword in critical_keywords):
            call_type = "critical_incident"
            score += 65
            tags.append("critical")

        if any(keyword in lowered for keyword in urgent_keywords):
            if call_type == "routine":
                call_type = "urgent_incident"
            score += 35
            tags.append("urgent")

        if service in {"police", "fire", "ems", "interop"}:
            score += 15
            tags.append(service)
        elif service in {"weather", "railroad"}:
            score += 5
            tags.append(service)
        elif service in {"fm_radio", "am_radio", "shortwave"}:
            score -= 10
            tags.append("broadcast")
            if call_type == "routine":
                call_type = "broadcast_audio"

        priority = max(1, min(5, int(round(score / 20))))
        confidence = max(0.4, min(0.98, 0.5 + (priority * 0.08)))
        summary = f"{call_type.replace('_', ' ').title()} on {channel.name}"

        # Keep tags deterministic and compact for frontend sorting/filtering.
        tags = sorted(set(tags))[:5]

        return {
            "call_type": call_type,
            "priority": priority,
            "confidence": round(confidence, 2),
            "tags": tags,
            "summary": summary,
        }


transcriber = RadioTranscriber(model_size="base")
