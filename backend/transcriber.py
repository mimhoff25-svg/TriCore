from __future__ import annotations

import logging
import json
import math
import queue
import subprocess
import sys
import threading
import tempfile
import time
import wave
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from .radio.models import Channel
from .decoder_runtime import (
    _creation_flags,
    _hidden_startupinfo,
    probe_rtl_sdr_device,
    runtime_subprocess_env,
)
from .windows_rtlsdr_tools import find_runtime_tool

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK_SECONDS = 8
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_SECONDS
SILENCE_THRESHOLD = 200  # int16 RMS below this = skip
TRANSCRIBE_TIMEOUT_SECONDS = 75
AUDIO_SUBSCRIBER_MAX_CHUNKS = 128
TRANSCRIPTION_QUEUE_MAX_CHUNKS = 8

_model = None
_model_lock = threading.Lock()


def _get_model(model_size: str = "base"):
    global _model
    with _model_lock:
        if _model is None:
            try:
                import httpx
                from huggingface_hub.utils import set_client_factory
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "Voice-to-text requires faster-whisper. Install backend requirements, then restart TriCore."
                ) from exc
            set_client_factory(lambda: httpx.Client(follow_redirects=True, timeout=None))
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
        "talkgroup_decimal",
        "selected_talkgroup_decimal",
        "source_radio_id",
        "target_radio_id",
        "radio_id",
        "radio_label",
        "voice_frequency_hz",
        "system_name",
        "category",
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
        metadata: dict[str, Any] | None = None,
    ):
        metadata = metadata or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.text = text
        self.call_type = call_type
        self.priority = priority
        self.confidence = confidence
        self.tags = tags
        self.summary = summary
        self.talkgroup_decimal = metadata.get("talkgroup_decimal")
        self.selected_talkgroup_decimal = metadata.get("selected_talkgroup_decimal")
        self.source_radio_id = metadata.get("source_radio_id")
        self.target_radio_id = metadata.get("target_radio_id")
        self.radio_id = metadata.get("radio_id")
        self.radio_label = metadata.get("radio_label")
        self.voice_frequency_hz = metadata.get("voice_frequency_hz")
        self.system_name = metadata.get("system_name")
        self.category = metadata.get("category")

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
            "talkgroup_decimal": self.talkgroup_decimal,
            "selected_talkgroup_decimal": self.selected_talkgroup_decimal,
            "source_radio_id": self.source_radio_id,
            "target_radio_id": self.target_radio_id,
            "radio_id": self.radio_id,
            "radio_label": self.radio_label,
            "voice_frequency_hz": self.voice_frequency_hz,
            "system_name": self.system_name,
            "category": self.category,
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
        self._audio_subscribers: set[queue.Queue[bytes]] = set()
        self._audio_subscribers_lock = threading.Lock()
        self._transcription_queue: queue.Queue[tuple[bytes, Channel, dict[str, Any]] | None] = queue.Queue(
            maxsize=TRANSCRIPTION_QUEUE_MAX_CHUNKS,
        )
        self._transcription_thread: Optional[threading.Thread] = None
        self._p25_audio_path: Optional[Path] = None
        self._metadata_provider: Optional[Callable[[Channel], dict[str, Any]]] = None
        self._last_metadata: dict[str, Any] = {}
        self._last_stream_signal_db = -100.0
        self._last_stream_audio_level = 0.0

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(
        self,
        channels: list[Channel],
        p25_audio_path: str | Path | None = None,
        metadata_provider: Callable[[Channel], dict[str, Any]] | None = None,
    ) -> dict:
        conventional_channels = [
            c for c in channels
            if str(c.modulation or "nfm").lower() in {"nfm", "am"}
        ]
        self._p25_audio_path = Path(p25_audio_path) if p25_audio_path else None
        p25_channels = [
            c for c in channels
            if self._is_p25_channel(c) and self._p25_audio_path is not None
        ]
        transcribable_channels = [*conventional_channels, *p25_channels]
        if not transcribable_channels:
            self.error = "No transcribable channels available (NFM/AM/P25)."
            return {"ok": False, "error": self.error}

        rtl_fm = None
        if conventional_channels:
            rtl_fm = find_runtime_tool("rtl_fm")
            if rtl_fm is None:
                self.error = "rtl_fm.exe not found. Check runtime tools."
                self._p25_audio_path = None
                return {"ok": False, "error": self.error}

        if self.running:
            self.error = "Transcriber already running."
            self._p25_audio_path = None
            return {"ok": False, "error": self.error}

        self._stop_event.clear()
        self.error = None
        self._metadata_provider = metadata_provider
        self._last_metadata = {}
        self._transcription_queue = queue.Queue(maxsize=TRANSCRIPTION_QUEUE_MAX_CHUNKS)
        self.running = True
        self._transcription_thread = threading.Thread(
            target=self._transcription_loop,
            daemon=True,
            name="transcriber-worker",
        )
        self._transcription_thread.start()
        self._thread = threading.Thread(
            target=self._scan_loop,
            args=(transcribable_channels, str(rtl_fm) if rtl_fm is not None else None, self._p25_audio_path),
            daemon=True,
            name="transcriber",
        )
        self._thread.start()
        return {"ok": True, "channels": len(transcribable_channels)}

    def stop(self):
        self._stop_event.set()
        self._kill_proc()
        self._signal_transcription_worker_stop()
        self.running = False
        self.current_channel = None
        self._p25_audio_path = None
        self._metadata_provider = None
        self._last_metadata = {}
        self._last_stream_signal_db = -100.0
        self._last_stream_audio_level = 0.0

    def get_transcripts(self) -> list[dict]:
        return [e.to_dict() for e in self.transcripts]

    def clear_transcripts(self):
        self.transcripts.clear()

    def subscribe_audio(self) -> queue.Queue[bytes]:
        subscriber: queue.Queue[bytes] = queue.Queue(maxsize=AUDIO_SUBSCRIBER_MAX_CHUNKS)
        with self._audio_subscribers_lock:
            self._audio_subscribers.add(subscriber)
        return subscriber

    def unsubscribe_audio(self, subscriber: queue.Queue[bytes]) -> None:
        with self._audio_subscribers_lock:
            self._audio_subscribers.discard(subscriber)

    def status(self) -> dict:
        with self._channel_lock:
            ch = self.current_channel
        return {
            "running": self.running,
            "error": self.error,
            "transcript_count": len(self.transcripts),
            "current_channel": ch.name if ch else None,
            "current_frequency_hz": ch.frequency_hz if ch else None,
            "current_modulation": ch.modulation if ch else None,
            "current_signal_level": self._last_stream_signal_db,
            "current_audio_level": self._last_stream_audio_level,
            "current_radio_id": self._last_metadata.get("radio_id"),
            "current_source_radio_id": self._last_metadata.get("source_radio_id"),
            "current_target_radio_id": self._last_metadata.get("target_radio_id"),
            "current_talkgroup_decimal": self._last_metadata.get("talkgroup_decimal"),
            "current_voice_frequency_hz": self._last_metadata.get("voice_frequency_hz"),
        }

    def _is_p25_channel(self, channel: Channel) -> bool:
        return str(getattr(channel, "modulation", "") or "").lower().strip() == "p25_placeholder"

    def _normalize_audio_samples(
        self,
        raw_bytes: bytes,
        channel_count: int,
        sample_rate: int,
    ) -> tuple[bytes, bytes]:
        if channel_count <= 0 or sample_rate <= 0:
            raise RuntimeError("Audio source reported an invalid PCM format.")

        frame_width = channel_count * 2
        usable_length = len(raw_bytes) - (len(raw_bytes) % frame_width)
        usable = raw_bytes[:usable_length]
        remainder = raw_bytes[usable_length:]
        if not usable:
            return b"", remainder

        samples = np.frombuffer(usable, dtype=np.int16)
        if channel_count > 1:
            samples = samples.reshape(-1, channel_count).astype(np.int32).mean(axis=1).astype(np.int16)

        if sample_rate != SAMPLE_RATE and samples.size:
            ratio = SAMPLE_RATE / float(sample_rate)
            target_count = max(1, int(round(samples.size * ratio)))
            if abs(ratio - round(ratio)) < 1e-6:
                samples = np.repeat(samples, int(round(ratio))).astype(np.int16)
            else:
                source_index = np.arange(samples.size, dtype=np.float32)
                target_index = np.linspace(0, samples.size - 1, num=target_count, dtype=np.float32)
                samples = np.interp(target_index, source_index, samples).astype(np.int16)

        return samples.astype(np.int16).tobytes(), remainder

    def _p25_audio_params(self, audio_path: Path) -> tuple[int, int, int]:
        deadline = time.monotonic() + 2.5
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            if not audio_path.exists():
                time.sleep(0.1)
                continue
            try:
                with wave.open(str(audio_path), "rb") as wav_file:
                    channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    sample_rate = wav_file.getframerate()
            except (OSError, wave.Error):
                time.sleep(0.1)
                continue
            if sample_width != 2:
                raise RuntimeError("Managed P25 audio WAV must be 16-bit PCM.")
            return channels, sample_width, sample_rate

        raise RuntimeError("Managed P25 audio WAV is not available.")

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _kill_proc(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=0.25)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _signal_transcription_worker_stop(self) -> None:
        try:
            self._transcription_queue.put_nowait(None)
        except queue.Full:
            try:
                self._transcription_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._transcription_queue.put_nowait(None)
            except queue.Full:
                pass

    def _publish_audio(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._update_stream_meter(chunk)
        with self._audio_subscribers_lock:
            subscribers = list(self._audio_subscribers)

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(chunk)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(chunk)
                except queue.Empty:
                    pass

    def _update_stream_meter(self, chunk: bytes) -> None:
        if len(chunk) < 2:
            return
        usable = chunk if len(chunk) % 2 == 0 else chunk[:-1]
        if not usable:
            return
        samples = np.frombuffer(usable, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return
        rms = float(np.sqrt(np.mean(samples ** 2)))
        if not math.isfinite(rms) or rms <= 0:
            signal_db = -100.0
            audio_level = 0.0
        else:
            dbfs = 20.0 * math.log10(rms / 32768.0)
            signal_db = round(max(-100.0, min(0.0, dbfs)), 1)
            audio_level = round(max(0.0, min(1.0, rms / 9000.0)), 3)
        self._last_stream_signal_db = signal_db
        self._last_stream_audio_level = audio_level

    def _scan_loop(self, channels: list[Channel], rtl_fm_path: str | None, p25_audio_path: Optional[Path]):
        idx = 0
        while not self._stop_event.is_set():
            channel = channels[idx % len(channels)]
            idx += 1
            with self._channel_lock:
                self.current_channel = channel

            try:
                if self._is_p25_channel(channel):
                    self._listen_p25_channel(channel, p25_audio_path)
                else:
                    if rtl_fm_path is None:
                        raise RuntimeError("rtl_fm.exe not found. Check runtime tools.")
                    self._listen_channel(channel, rtl_fm_path)
            except Exception as exc:
                message = str(exc)
                if self._is_p25_channel(channel) and message == "Managed P25 audio WAV is not available.":
                    self.error = None
                    self._last_stream_signal_db = -100.0
                    self._last_stream_audio_level = 0.0
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.5)
                    continue

                logger.warning("Transcriber error on %s: %s", channel.name, exc)
                self.error = message
                lowered = message.lower()
                if (
                    "access denied" in lowered
                    or "usb_open" in lowered
                    or "no supported devices found" in lowered
                    or "rtl_fm exited" in lowered
                ):
                    self.running = False
                    break
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        self.running = False
        self._signal_transcription_worker_stop()
        with self._channel_lock:
            self.current_channel = None

    def _listen_p25_channel(self, channel: Channel, audio_path: Optional[Path]):
        if audio_path is None:
            raise RuntimeError("Managed P25 audio source is not configured.")

        channel_count, sample_width, sample_rate = self._p25_audio_params(audio_path)
        data_offset = 44
        input_bytes_per_chunk = int(CHUNK_SECONDS * sample_rate * channel_count * sample_width)
        bytes_per_chunk = CHUNK_SAMPLES * 2
        audio_buf = bytearray()
        pending_source_bytes = b""
        chunk_metadata: dict[str, Any] = {}

        try:
            initial_stat = audio_path.stat()
            initial_size = initial_stat.st_size
            recently_updated = (time.time() - initial_stat.st_mtime) <= 1.5
        except OSError:
            initial_size = data_offset
            recently_updated = False

        if recently_updated:
            offset = max(data_offset, initial_size - input_bytes_per_chunk)
        else:
            offset = max(data_offset, initial_size)

        while not self._stop_event.is_set():
            try:
                stat = audio_path.stat()
            except OSError:
                time.sleep(0.1)
                continue

            if stat.st_size < data_offset:
                time.sleep(0.1)
                continue

            if stat.st_size < offset:
                offset = data_offset
                pending_source_bytes = b""
                audio_buf.clear()

            if stat.st_size == offset:
                time.sleep(0.1)
                continue

            try:
                with audio_path.open("rb") as handle:
                    handle.seek(offset)
                    raw = handle.read(stat.st_size - offset)
            except OSError:
                time.sleep(0.1)
                continue

            offset = stat.st_size
            if not raw:
                time.sleep(0.05)
                continue

            normalized, pending_source_bytes = self._normalize_audio_samples(
                pending_source_bytes + raw,
                channel_count=channel_count,
                sample_rate=sample_rate,
            )
            if not normalized:
                continue

            self._publish_audio(normalized)
            latest_metadata = self._metadata_for_channel(channel)
            if latest_metadata.get("voice_frequency_hz") or latest_metadata.get("source_radio_id") or latest_metadata.get("radio_id"):
                chunk_metadata.update({
                    key: value
                    for key, value in latest_metadata.items()
                    if value is not None
                })
            audio_buf.extend(normalized)

            while len(audio_buf) >= bytes_per_chunk:
                chunk = bytes(audio_buf[:bytes_per_chunk])
                del audio_buf[:bytes_per_chunk]
                self._queue_transcribe_chunk(chunk, channel, metadata=chunk_metadata or None)
                chunk_metadata = {}

    def _listen_channel(self, channel: Channel, rtl_fm_path: str):
        modulation = str(getattr(channel, "modulation", "nfm") or "nfm").lower().strip()
        rtl_mode = "am" if modulation == "am" else "fm"
        freq_mhz = float(channel.frequency_hz) / 1_000_000
        cmd = [
            rtl_fm_path,
            "-f", f"{freq_mhz:.6f}M",
            "-M", rtl_mode,
            "-s", str(SAMPLE_RATE),
            "-r", str(SAMPLE_RATE),
            "-l", "0",
        ]
        if modulation == "nfm":
            cmd.extend(["-A", "fast", "-E", "offset", "-E", "deemp"])
        if modulation == "am":
            cmd.extend(["-A", "std"])
        logger.debug("rtl_fm cmd: %s", " ".join(cmd))

        dwell = max(float(getattr(channel, "delay_seconds", 4.0) or 4.0), CHUNK_SECONDS + 1.0)
        deadline = time.monotonic() + dwell

        rtl_path = Path(rtl_fm_path)
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(rtl_path.parent),
            env=runtime_subprocess_env(rtl_path.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=_hidden_startupinfo(),
            creationflags=_creation_flags(),
            bufsize=0,
        )

        time.sleep(0.05)
        if self._proc.poll() is not None:
            stderr = ""
            if self._proc.stderr is not None:
                stderr = self._proc.stderr.read().decode("utf-8", errors="replace").strip()
            detail = stderr or f"rtl_fm exited with code {self._proc.returncode}."
            raise RuntimeError(detail)

        audio_buf = bytearray()
        bytes_per_chunk = CHUNK_SAMPLES * 2  # int16 = 2 bytes

        try:
            while not self._stop_event.is_set() and time.monotonic() < deadline:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                self._publish_audio(chunk)
                audio_buf.extend(chunk)

                while len(audio_buf) >= bytes_per_chunk:
                    raw = bytes(audio_buf[:bytes_per_chunk])
                    audio_buf = audio_buf[bytes_per_chunk:]
                    self._queue_transcribe_chunk(raw, channel)
        finally:
            self._kill_proc()

    def _queue_transcribe_chunk(self, raw_int16: bytes, channel: Channel, metadata: dict[str, Any] | None = None) -> None:
        if self._stop_event.is_set():
            return
        latest_metadata = self._metadata_for_channel(channel)
        chunk_metadata = dict(metadata or {})
        chunk_metadata.update({
            key: value
            for key, value in latest_metadata.items()
            if value is not None and (key not in chunk_metadata or chunk_metadata.get(key) in (None, ""))
        })
        radio_id = chunk_metadata.get("source_radio_id") or chunk_metadata.get("target_radio_id")
        if radio_id:
            chunk_metadata["radio_id"] = str(radio_id)
        try:
            self._transcription_queue.put_nowait((raw_int16, channel, chunk_metadata))
        except queue.Full:
            try:
                self._transcription_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._transcription_queue.put_nowait((raw_int16, channel, chunk_metadata))
            except queue.Full:
                logger.debug("Dropping transcriber chunk for %s because the queue is full.", channel.name)

    def _metadata_for_channel(self, channel: Channel) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "system_name": getattr(channel, "system_name", None),
            "category": getattr(channel, "category", None),
        }
        if channel.p25_talkgroup_decimal is not None:
            metadata["selected_talkgroup_decimal"] = int(channel.p25_talkgroup_decimal)
            metadata["talkgroup_decimal"] = int(channel.p25_talkgroup_decimal)
        provider = self._metadata_provider
        if provider is not None:
            try:
                provided = provider(channel)
                if isinstance(provided, dict):
                    metadata.update({key: value for key, value in provided.items() if value is not None})
            except Exception as exc:
                logger.debug("Transcriber metadata provider failed for %s: %s", channel.name, exc)
        radio_id = metadata.get("source_radio_id") or metadata.get("target_radio_id")
        if radio_id:
            metadata["radio_id"] = str(radio_id)
        self._last_metadata = dict(metadata)
        return metadata

    def _transcription_loop(self) -> None:
        while True:
            try:
                item = self._transcription_queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue

            if item is None:
                break

            raw_int16, channel, metadata = item
            try:
                self._transcribe_chunk(raw_int16, channel, metadata)
            except Exception as exc:
                logger.warning("Voice-to-text worker failed on %s: %s", channel.name, exc)
                self.error = str(exc)

    def _transcribe_chunk(self, raw_int16: bytes, channel: Channel, metadata: dict[str, Any] | None = None):
        arr = np.frombuffer(raw_int16, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(arr ** 2)))
        if rms * 32768 < SILENCE_THRESHOLD:
            return  # silence — skip

        words = self._transcribe_via_worker(raw_int16)
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
                metadata=metadata,
            )
            self.transcripts.append(entry)
            logger.info("[%s] %s", channel.name, words)

    def _transcribe_via_worker(self, raw_int16: bytes) -> str:
        worker_path = Path(__file__).with_name("transcribe_chunk_worker.py")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as handle:
            wav_path = Path(handle.name)

        try:
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(raw_int16)

            completed = subprocess.run(
                [sys.executable, str(worker_path), str(wav_path), self.model_size],
                capture_output=True,
                text=True,
                timeout=TRANSCRIBE_TIMEOUT_SECONDS,
                cwd=str(worker_path.parent.parent),
                env=runtime_subprocess_env(worker_path.parent),
                startupinfo=_hidden_startupinfo(),
                creationflags=_creation_flags(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Voice-to-text worker timed out.") from exc
        finally:
            wav_path.unlink(missing_ok=True)

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Voice-to-text worker failed.").strip()
            raise RuntimeError(detail)

        payload = json.loads((completed.stdout or "{}").strip() or "{}")
        return str(payload.get("text") or "").strip()

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
        elif service in {"weather", "noaa_weather", "railroad"}:
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
