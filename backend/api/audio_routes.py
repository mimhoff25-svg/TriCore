from __future__ import annotations

import struct
import subprocess
import queue
import threading
import time
from array import array
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..decoder_runtime import _creation_flags, _hidden_startupinfo, runtime_subprocess_env
from ..windows_rtlsdr_tools import find_runtime_tool
from .shared import scanner_core


router = APIRouter(prefix="/api/audio", tags=["audio"])
FIRST_AUDIO_CHUNK_TIMEOUT_SECONDS = 4.0
WFM_PLAYBACK_RATE = 32000
WFM_OUTPUT_GAIN = 1.35
WFM_DC_ALPHA = 0.0008
WFM_LOW_PASS_ALPHA = 0.78
NFM_OUTPUT_GAIN = 1.15
NFM_DC_ALPHA = 0.0012
NFM_LOW_PASS_ALPHA = 0.46
NFM_GATE_FLOOR = 320.0
NFM_GATE_OPEN = 1250.0
NFM_GATE_ATTACK = 0.08
NFM_GATE_RELEASE = 0.018
NFM_LIMIT = 18500.0
VOICE_GATE_FLOOR = 450.0
VOICE_GATE_OPEN = 1350.0
VOICE_GATE_ATTACK = 0.28
VOICE_GATE_RELEASE = 0.04
RTL_HANDLE_RELEASE_WAIT_SECONDS = 0.08
DEFAULT_AUDIO_SQUELCH_DB = -65.0
_ACTIVE_AUDIO_LOCK = threading.Lock()
_ACTIVE_AUDIO_PROCESS: subprocess.Popen | None = None
_STREAM_START_LOCK = threading.Lock()


def _terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        process.kill()


def _replace_active_process(process: subprocess.Popen) -> None:
    global _ACTIVE_AUDIO_PROCESS
    with _ACTIVE_AUDIO_LOCK:
        previous = _ACTIVE_AUDIO_PROCESS
        _ACTIVE_AUDIO_PROCESS = process
    if previous is not None and previous is not process:
        _terminate_process(previous)


def _clear_active_process(process: subprocess.Popen) -> None:
    global _ACTIVE_AUDIO_PROCESS
    with _ACTIVE_AUDIO_LOCK:
        if _ACTIVE_AUDIO_PROCESS is process:
            _ACTIVE_AUDIO_PROCESS = None


def stop_live_audio_process() -> None:
    global _ACTIVE_AUDIO_PROCESS
    with _ACTIVE_AUDIO_LOCK:
        previous = _ACTIVE_AUDIO_PROCESS
        _ACTIVE_AUDIO_PROCESS = None
    if previous is not None:
        _terminate_process(previous)


def _stop_active_process() -> None:
    stop_live_audio_process()


@router.post("/stop")
def stop_live_audio():
    stop_live_audio_process()
    scanner_core.restore_rtl_receiver_after_external_audio()
    return {"ok": True}


def _read_stdout_chunk(process: subprocess.Popen, timeout_seconds: float) -> bytes:
    if process.stdout is None:
        return b""

    chunks: queue.Queue[bytes] = queue.Queue(maxsize=1)

    def read_chunk() -> None:
        chunks.put(process.stdout.read(4096))

    thread = threading.Thread(target=read_chunk, daemon=True)
    thread.start()
    try:
        return chunks.get(timeout=timeout_seconds)
    except queue.Empty:
        return b""


def _wav_header(sample_rate: int, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    # Streamed WAV uses a large placeholder data size.
    data_size = 0x7FFFFFFF
    riff_size = 36 + data_size
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )


class WfmAudioCleaner:
    def __init__(self) -> None:
        self.dc_estimate = 0.0
        self.low_pass = 0.0

    def process(self, chunk: bytes) -> bytes:
        if not chunk:
            return b""
        if len(chunk) % 2:
            chunk = chunk[:-1]
        if not chunk:
            return b""

        samples = array("h")
        samples.frombytes(chunk)
        if struct.pack("=h", 1) != struct.pack("<h", 1):
            samples.byteswap()

        for index, sample in enumerate(samples):
            value = float(sample)
            self.dc_estimate += WFM_DC_ALPHA * (value - self.dc_estimate)
            value -= self.dc_estimate
            self.low_pass += WFM_LOW_PASS_ALPHA * (value - self.low_pass)
            value = self.low_pass * WFM_OUTPUT_GAIN
            samples[index] = int(max(-32768, min(32767, value)))

        if struct.pack("=h", 1) != struct.pack("<h", 1):
            samples.byteswap()
        return samples.tobytes()


class NfmAudioCleaner:
    def __init__(self) -> None:
        self.dc_estimate = 0.0
        self.low_pass = 0.0
        self.envelope = 0.0
        self.gate = 0.0

    def process(self, chunk: bytes) -> bytes:
        if not chunk:
            return b""
        if len(chunk) % 2:
            chunk = chunk[:-1]
        if not chunk:
            return b""

        samples = array("h")
        samples.frombytes(chunk)
        if struct.pack("=h", 1) != struct.pack("<h", 1):
            samples.byteswap()

        for index, sample in enumerate(samples):
            value = float(sample)
            self.dc_estimate += NFM_DC_ALPHA * (value - self.dc_estimate)
            value -= self.dc_estimate

            self.low_pass += NFM_LOW_PASS_ALPHA * (value - self.low_pass)
            value = self.low_pass

            magnitude = abs(value)
            self.envelope = (self.envelope * 0.985) + (magnitude * 0.015)
            if self.envelope <= NFM_GATE_FLOOR:
                target_gate = 0.0
            elif self.envelope >= NFM_GATE_OPEN:
                target_gate = 1.0
            else:
                target_gate = (self.envelope - NFM_GATE_FLOOR) / (NFM_GATE_OPEN - NFM_GATE_FLOOR)

            gate_speed = NFM_GATE_ATTACK if target_gate > self.gate else NFM_GATE_RELEASE
            self.gate += gate_speed * (target_gate - self.gate)

            value *= self.gate * NFM_OUTPUT_GAIN
            if value > NFM_LIMIT:
                value = NFM_LIMIT + ((value - NFM_LIMIT) * 0.2)
            elif value < -NFM_LIMIT:
                value = -NFM_LIMIT + ((value + NFM_LIMIT) * 0.2)

            samples[index] = int(max(-32768, min(32767, value)))

        if struct.pack("=h", 1) != struct.pack("<h", 1):
            samples.byteswap()
        return samples.tobytes()


class VoiceAudioGate:
    def __init__(self, output_gain: float = 1.0) -> None:
        self.dc_estimate = 0.0
        self.envelope = 0.0
        self.gate = 0.0
        self.output_gain = output_gain

    def process(self, chunk: bytes) -> bytes:
        if not chunk:
            return b""
        if len(chunk) % 2:
            chunk = chunk[:-1]
        if not chunk:
            return b""

        samples = array("h")
        samples.frombytes(chunk)
        if struct.pack("=h", 1) != struct.pack("<h", 1):
            samples.byteswap()

        for index, sample in enumerate(samples):
            value = float(sample)
            self.dc_estimate += 0.001 * (value - self.dc_estimate)
            value -= self.dc_estimate

            magnitude = abs(value)
            self.envelope = (self.envelope * 0.99) + (magnitude * 0.01)
            if self.envelope <= VOICE_GATE_FLOOR:
                target_gate = 0.0
            elif self.envelope >= VOICE_GATE_OPEN:
                target_gate = 1.0
            else:
                target_gate = (self.envelope - VOICE_GATE_FLOOR) / (VOICE_GATE_OPEN - VOICE_GATE_FLOOR)

            gate_speed = VOICE_GATE_ATTACK if target_gate > self.gate else VOICE_GATE_RELEASE
            self.gate += gate_speed * (target_gate - self.gate)
            value *= self.gate * self.output_gain
            samples[index] = int(max(-32768, min(32767, value)))

        if struct.pack("=h", 1) != struct.pack("<h", 1):
            samples.byteswap()
        return samples.tobytes()


def _rtl_fm_squelch_level(modulation: str, squelch_db: float | None) -> int:
    if modulation == "wfm":
        return 0
    parsed = DEFAULT_AUDIO_SQUELCH_DB if squelch_db is None else float(squelch_db)
    # Map scanner-style dB threshold (-100..-40) to rtl_fm squelch scale.
    return max(0, min(60, round((parsed + 100.0) / 2.0)))


def _should_force_open_squelch(
    frequency_hz: int,
    modulation: str,
    service_type: str | None,
) -> bool:
    if modulation == "wfm":
        return True
    if modulation != "nfm":
        return False

    normalized_service = str(service_type or "").lower().strip()
    if normalized_service in {"weather", "noaa_weather"}:
        return True

    return frequency_hz in {
        162_400_000,
        162_425_000,
        162_450_000,
        162_475_000,
        162_500_000,
        162_525_000,
        162_550_000,
    }


def _rtl_fm_args(
    frequency_hz: int,
    modulation: str,
    gain_db: float | None,
    squelch_db: float | None,
    service_type: str | None = None,
) -> tuple[list[str], int, int]:
    modulation_map = {
        "wfm": ("wbfm", WFM_PLAYBACK_RATE, WFM_PLAYBACK_RATE),
        "nfm": ("fm", 24000, 24000),
        "am": ("am", 24000, 24000),
    }
    if modulation not in modulation_map:
        raise HTTPException(status_code=400, detail=f"Unsupported modulation for live audio: {modulation}")

    rtl_mode, input_rate, output_rate = modulation_map[modulation]
    freq_mhz = frequency_hz / 1_000_000

    if modulation == "wfm":
        args = [
            "-f", f"{freq_mhz:.6f}M",
            "-M", rtl_mode,
            "-l", "0",
            "-E", "dc",
        ]
        if gain_db is not None:
            args.extend(["-g", str(gain_db)])
        return args, output_rate, 0

    squelch_level = 0 if _should_force_open_squelch(frequency_hz, modulation, service_type) else _rtl_fm_squelch_level(modulation, squelch_db)

    args = [
        "-f", f"{freq_mhz:.6f}M",
        "-M", rtl_mode,
        "-s", str(input_rate),
        "-r", str(output_rate),
        "-l", str(squelch_level),
    ]
    if modulation == "nfm":
        args.extend(["-A", "fast", "-E", "offset"])
    if modulation in {"wfm", "nfm"}:
        args.extend(["-E", "deemp"])
    if modulation == "am":
        args.extend(["-A", "std"])

    if gain_db is not None:
        args.extend(["-g", str(gain_db)])

    return args, output_rate, squelch_level


@router.get("/live")
def live_audio(
    frequency_hz: int | None = Query(default=None, gt=0),
    modulation: str | None = Query(default=None),
    gain_db: float | None = Query(default=None),
    squelch_db: float | None = Query(default=None),
    stream_id: str | None = Query(default=None),
):
    from ..transcriber import SAMPLE_RATE, transcriber

    if transcriber.running:
        requested_modulation = (modulation or "nfm").lower().strip()
        if requested_modulation not in {"nfm", "am", "p25_placeholder"}:
            raise HTTPException(
                status_code=409,
                detail="Live audio monitor can share voice-to-text audio only for NFM/AM/P25 channels.",
            )

        subscriber = transcriber.subscribe_audio()

        def stream_transcriber_audio_as_wav():
            cleaner = NfmAudioCleaner() if requested_modulation == "nfm" else VoiceAudioGate(output_gain=1.35)
            try:
                yield _wav_header(SAMPLE_RATE)
                while transcriber.running:
                    try:
                        chunk = subscriber.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    chunk = cleaner.process(chunk)
                    if chunk:
                        yield chunk
            finally:
                transcriber.unsubscribe_audio(subscriber)

        return StreamingResponse(
            stream_transcriber_audio_as_wav(),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store", "X-TriCore-Audio": "transcriber"},
        )

    active_channel = scanner_core.current_channel
    requested_modulation = (modulation or (active_channel.modulation if active_channel is not None else "nfm")).lower().strip()
    if requested_modulation == "p25_placeholder":
        decoder = scanner_core.decoders.get("p25_placeholder")
        decoder_status = None
        if decoder is not None:
            try:
                decoder_status = decoder.status()
            except Exception:
                decoder_status = None
        runtime_engine = str((decoder_status.runtime or {}).get("engine") or "").lower() if decoder_status is not None else ""
        if runtime_engine == "sdrtrunk":
            raise HTTPException(
                status_code=409,
                detail="SDRTrunk fallback is handling P25 audio from the workspace playlist. In-app live audio is unavailable in fallback mode.",
            )
    if requested_modulation != "p25_placeholder":
        scanner_core.shutdown_managed_p25_runtime(clear_current=False)

    scanner_core.release_rtl_receiver_for_external_audio()
    _stop_active_process()
    time.sleep(0.03)
    try:
        if frequency_hz is None:
            if active_channel is None:
                raise HTTPException(status_code=400, detail="No active channel to stream audio from.")
            frequency_hz = int(active_channel.frequency_hz)

        if not modulation:
            modulation = requested_modulation

        modulation = modulation.lower().strip()
        effective_gain = scanner_core.settings.gain_db if gain_db is None else gain_db
        effective_squelch = scanner_core.settings.squelch_db if squelch_db is None else squelch_db

        rtl_fm_path = find_runtime_tool("rtl_fm")
        if rtl_fm_path is None:
            raise HTTPException(status_code=500, detail="rtl_fm.exe not found in runtime tools.")

        channel_service_type = active_channel.service_type if active_channel is not None else None
        args, output_rate, rtl_squelch_level = _rtl_fm_args(
            frequency_hz,
            modulation,
            effective_gain,
            effective_squelch,
            service_type=channel_service_type,
        )
        command = [str(rtl_fm_path), *args]
    except HTTPException:
        scanner_core.restore_rtl_receiver_after_external_audio()
        raise

    with _STREAM_START_LOCK:
        _stop_active_process()
        time.sleep(RTL_HANDLE_RELEASE_WAIT_SECONDS)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path(rtl_fm_path).parent),
                env=runtime_subprocess_env(Path(rtl_fm_path).parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=_hidden_startupinfo(),
                creationflags=_creation_flags(),
            )
        except OSError as exc:
            scanner_core.restore_rtl_receiver_after_external_audio()
            raise HTTPException(status_code=500, detail=f"Failed to start rtl_fm: {exc}") from exc

        _replace_active_process(process)

    time.sleep(0.08)
    if process.poll() is not None:
        stderr = ""
        if process.stderr is not None:
            stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        _terminate_process(process)
        _clear_active_process(process)
        scanner_core.restore_rtl_receiver_after_external_audio()
        detail = stderr or f"rtl_fm exited with code {process.returncode}."
        raise HTTPException(status_code=503, detail=f"rtl_fm could not start live FM audio: {detail}")

    first_chunk = b"" if rtl_squelch_level > 0 else _read_stdout_chunk(process, FIRST_AUDIO_CHUNK_TIMEOUT_SECONDS)
    if not first_chunk and rtl_squelch_level <= 0:
        stderr = ""
        _terminate_process(process)
        _clear_active_process(process)
        if process.stderr is not None:
            stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        scanner_core.restore_rtl_receiver_after_external_audio()
        detail = stderr or "rtl_fm opened the tuner but did not produce audio samples."
        raise HTTPException(status_code=503, detail=f"rtl_fm produced no live FM audio: {detail}")

    def stream_pcm_as_wav():
        cleaner = None
        if modulation == "wfm":
            cleaner = WfmAudioCleaner()
        elif modulation == "nfm":
            cleaner = NfmAudioCleaner()

        def prepare_chunk(chunk: bytes) -> bytes:
            if cleaner is None:
                return chunk
            return cleaner.process(chunk)

        try:
            yield _wav_header(output_rate)
            prepared = prepare_chunk(first_chunk)
            if prepared:
                yield prepared
            if process.stdout is None:
                return
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                prepared = prepare_chunk(chunk)
                if prepared:
                    yield prepared
        finally:
            _terminate_process(process)
            _clear_active_process(process)
            scanner_core.restore_rtl_receiver_after_external_audio()

    return StreamingResponse(
        stream_pcm_as_wav(),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store", "X-TriCore-Audio": "rtl_fm"},
    )
