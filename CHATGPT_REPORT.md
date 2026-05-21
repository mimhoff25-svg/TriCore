# TriCore Scanner — Full System Report

Date: 2026-05-20

---

## 1. Project Summary

TriCore is a Windows-native SDR scanner built on FastAPI (Python backend) and React/Electron (frontend). It supports both conventional analog scanning and managed P25 Phase II trunked scanning of the Greater Austin/Travis Regional Radio System (GATRRS) on 851–855 MHz. One RTL-SDR dongle serves both modes; device handoff is managed through subprocess lifecycle.

---

## 2. Architecture Overview

```
[React/Electron Frontend]
        |
    HTTP + SSE
        |
[FastAPI Backend — uvicorn on 127.0.0.1:8000]
        |
        +-- scanner_core.py  (state machine: scan/hold/tune/search)
        |       |
        |       +-- FrequencyManager      (channel catalog, scan list, P25 config)
        |       +-- RtlSdrReceiver        (pyrtlsdr wrapper, open_device=False)
        |       +-- ManagedP25Decoder     (wraps HeadlessP25Runtime)
        |       +-- decoders: nfm/wfm/am  (conventional — rtl_fm subprocess)
        |
        +-- Transcriber     (reads audio from rtl_fm pipe or DSDPlus WAV)
        |       |
        |       +-- PublishQueue          (PCM chunks → live audio SSE subscribers)
        |
        +-- HeadlessP25Runtime    (manages DSDPlus.exe + FMP24.exe subprocesses)
```

**Data sources:**
- Conventional frequencies: `configs/frequencies/sample_frequencies.json`
- GATRRS P25 trunked system: `configs/trunked/gatrrs_travis_county.json`
- Bank metadata and priorities: `backend/data/default_banks.json`

---

## 3. P25 Trunking — How It Works

### 3.1 GATRRS System

- **System**: Greater Austin/Travis Regional Radio System (P25 Phase II)
- **WACN**: BEE09, **System ID**: 13E
- **Site**: Austin Travis — Control Channels: 851.3875, 851.1375, 851.2875, 851.3125 MHz
- **Voice Channels**: 29 channels from 851.0375 to 855.7125 MHz
- **Starter talkgroups** (TCSO): 2403, 2404, 2405, 2406

### 3.2 DSDPlus + FMP24 Pipeline

P25 decoding uses two Windows executables managed as subprocesses:

- **FMP24.exe**: SDR front-end, tunes the RTL-SDR dongle and pipes I/Q to DSDPlus.
- **DSDPlus.exe**: P25 Phase II decoder; follows control channel OSP messages and voice-grants; writes decoded audio to `1R-DSDPlus.wav`.

`HeadlessP25Runtime` (`backend/headless_p25_runtime.py`) manages both processes:
- Starts FMP24 + DSDPlus with a `.groups` file listing monitored talkgroups.
- Polls DSDPlus's `DSDPlus.stat` snapshot file (every 1 second) for health, current voice frequency, talkgroup ID, radio IDs, NAC, and phase.
- Implements control-channel failover: rotates to the next channel after 12 seconds without P25 data.
- Writes `DSDPlus.groups` at start with enabled talkgroup decimals to filter what gets decoded.

### 3.3 Scan Chain — End to End

The P25 scan path is:

```
FrequencyManager.__init__()
    → _talkgroup_scan_overrides = {2403: True, 2404: True, 2405: True, 2406: True}
    → _load_channels()
    → _sync_trunked_bank_enabled_state()          (sets gatrrs-p25 bank enabled=True)

scan_candidates()
    → filters self.channels (excludes p25_placeholder modulation channels)
    → calls trunked_scan_channel()
        → enabled_trunked_talkgroup_targets() → [(2403,"..."), (2404,"..."), ...]
        → returns synthetic Channel(id="trunked-scan-gatrrs", modulation="p25_placeholder",
                                    p25_control_channels_hz=[851387500, ...])
    → appends trunked-scan-gatrrs to candidates list

scanner_core._tune_channel(channel)
    [if modulation == "p25_placeholder"]
    → release_rtl_receiver_for_external_audio()
    → ManagedP25Decoder.tune(channel) or scan_talkgroups(...)
        → HeadlessP25Runtime.start()
            → launches FMP24.exe + DSDPlus.exe
            → DSDPlus locks control channel, follows voice grants
```

### 3.4 Audio Routing for P25

Web player audio for P25 works through the transcriber pipeline:

```
DSDPlus.exe → writes 1R-DSDPlus.wav (continuously updated WAV)
                ↓
Transcriber._listen_p25_channel()  reads WAV file in chunks
                ↓
PublishQueue  pushes PCM chunks to all subscribers
                ↓
GET /api/audio/live  (SSE stream)
                ↓
React <audio> element  (MediaSource API)
```

For conventional channels, the same `GET /api/audio/live` stream is fed by `rtl_fm` piping to the transcriber instead.

**Key constraint**: The transcriber must be running with the correct audio source before `/api/audio/live` will produce sound. After selecting a P25 talkgroup, the frontend calls `POST /api/transcriber/start` unconditionally to wire up the DSDPlus WAV path.

---

## 4. RTL-SDR Device Management

**Rule**: Only one consumer may hold the RTL-SDR at a time. The two consumers are:
- `rtl_fm` subprocess (conventional scanning audio)
- `FMP24.exe` subprocess (P25 trunking)

`RtlSdrReceiver` is created with `open_device=False`, so pyrtlsdr never holds the hardware. The actual "exclusive access" is determined by which subprocess is running.

**Conventional → P25 handoff** (`_stop_analog_audio_for_p25()` in `p25_routes.py`):
1. `stop_live_audio_process()` — kills `rtl_fm` subprocess.
2. `transcriber.stop()` if running — stops PCM streaming.
3. `release_rtl_receiver_for_external_audio()` — clears any pyrtlsdr handle.
4. DSDPlus/FMP24 can now open the device.

**P25 → Conventional handoff** (`_tune_channel()` in `scanner_core.py`):
1. `shutdown_managed_p25_runtime()` — calls `ManagedP25Decoder.stop()` which calls `HeadlessP25Runtime.stop()`.
2. `HeadlessP25Runtime.stop()` terminates DSDPlus + FMP24 with `process.terminate()` + `process.wait(timeout=5)`.
3. `RtlSdrReceiver.tune()` — starts `rtl_fm` subprocess.

Both transitions are blocking on the stop side (≤5s for DSDPlus termination) to ensure clean device handoff.

---

## 5. Bugs Found and Fixed (This Session)

### Bug 1 — P25 scan channels never appear in scan loop [CRITICAL]

**Root cause**: `FrequencyManager.__init__` initialized `_talkgroup_scan_overrides = {}` (empty dict). This meant:
- `talkgroup_scan_enabled()` returned `False` for all talkgroups.
- `enabled_trunked_talkgroup_targets()` returned `[]`.
- `trunked_scan_channel()` returned `None`.
- `scan_candidates()` never included the trunked scan channel.
- 800 MHz P25 channels were invisible to the scan loop from first boot.

**Fix** (`backend/radio/frequency_manager.py`, `__init__`):
```python
# Before:
self._talkgroup_scan_overrides: dict[int, bool] = {}
self.channels: list[Channel] = self._load_channels()

# After:
self._talkgroup_scan_overrides: dict[int, bool] = {decimal: True for decimal in STARTER_TCSO_TALKGROUP_DECIMALS}
self.channels: list[Channel] = self._load_channels()
self._sync_trunked_bank_enabled_state()
```

`STARTER_TCSO_TALKGROUP_DECIMALS = {2403, 2404, 2405, 2406}` was already defined at module level but never used.

### Bug 2 — Clicking a talkgroup plays no audio in web player [CRITICAL]

**Root cause**: `selectTalkgroup()` in `App.jsx` only restarted the transcriber `if (wasTranscribing)`. If the user had not previously used the transcriber, the DSDPlus WAV pipeline was never connected and `/api/audio/live` streamed silence.

**Fix** (`frontend/src/App.jsx`, `selectTalkgroup`):
```javascript
// Before:
if (wasTranscribing) {
    const started = await api("/api/transcriber/start", "POST");
    ...
}

// After:
const started = await api("/api/transcriber/start", "POST");
setTranscriptStatus(started);
setTranscripts(started.transcripts || []);
setAudioStreamVersion((v) => v + 1);
```

The backend `POST /api/transcriber/start` already auto-detects P25 context: if the active channel has `modulation == "p25_placeholder"`, it passes `audio_wav_path()` from the decoder (pointing to `1R-DSDPlus.wav`) to the transcriber automatically.

### Bug 3 — DSDPlus `.groups` file written every second [PERFORMANCE]

**Root cause**: `ManagedP25Decoder.status()` called `_set_monitored_talkgroups()` on every 1-second poll. This wrote the DSDPlus `.groups` file to disk on every status check.

**Fix** (`backend/decoders/p25_decoder.py`, `status()`):
```python
# Before:
def status(self) -> DecoderStatus:
    self._set_monitored_talkgroups(list(self._monitored_talkgroups))  # file I/O every second
    return self._status_from_snapshot(self._runtime.status(force_probe=False))

# After:
def status(self) -> DecoderStatus:
    return self._status_from_snapshot(self._runtime.status(force_probe=False))
```

The `.groups` file is written correctly in `_start_with_talkgroups()`, which calls `_set_monitored_talkgroups()` twice: before and after `runtime.start()` to handle a race where DSDPlus starts before the file is written.

### Bug 4 — `_decimal_from_payload` crashes on talkgroupId lookup [CRASH]

**Root cause**: `int(item.get("decimal"))` throws `TypeError` if `decimal` key is absent from the talkgroup dict (returns `None`).

**Fix** (`backend/api/p25_routes.py`, `_decimal_from_payload`):
```python
# Before:
return int(item.get("decimal"))

# After:
try:
    return int(item.get("decimal"))
except (TypeError, ValueError):
    return None
```

### Bug 5 — P25 status goes stale between scanner polls [UX]

**Root cause**: `p25Status` was only refreshed on mount and after `tuneChannel`. Between events, the displayed talkgroup, voice frequency, and sync state could be 30+ seconds out of date.

**Fix** (`frontend/src/App.jsx`, `useEffect`):
```javascript
const p25Timer = setInterval(() => refreshP25Status().catch(() => null), 2500);
// cleanup: clearInterval(p25Timer)
```

### Bug 6 — `selectTalkgroup` silently fails on 404/409 [UX]

**Root cause**: No try-catch around the `POST /api/p25/select-talkgroup` call. Audio was faded to 0 but no error message appeared if the request failed (e.g., talkgroup encrypted or not found).

**Fix** (`frontend/src/App.jsx`):
```javascript
} catch (error) {
    setAudioMonitorError(String(error?.message || error));
}
```

---

## 6. Seamless P25 ↔ Conventional Switching

The full switching sequence when the scanner auto-advances from a P25 scan channel to a conventional channel (or vice versa):

**P25 → Conventional:**
1. `scanner_core._tune_channel(new_conventional_channel)` detects previous decoder is P25.
2. Calls `previous_decoder.stop()` → `HeadlessP25Runtime.stop()` → terminates DSDPlus + FMP24 (blocks ≤5s).
3. Calls `RtlSdrReceiver.tune(new_channel)` → starts `rtl_fm` subprocess.
4. `_sync_transcriber_to_status()` restarts transcriber with rtl_fm pipe as audio source.
5. `/api/audio/live` immediately starts streaming conventional audio.

**Conventional → P25** (user clicks talkgroup or scan reaches trunked-scan-gatrrs):
1. `_stop_analog_audio_for_p25()` → kills `rtl_fm`, stops transcriber.
2. `scanner_core.tune_p25_talkgroup(decimal)` or `_tune_channel(trunked-scan-gatrrs)`.
3. `ManagedP25Decoder.tune(channel)` → `HeadlessP25Runtime.start()` → launches DSDPlus + FMP24.
4. Frontend calls `POST /api/transcriber/start` → connects DSDPlus WAV audio path.
5. `GET /api/audio/live` starts streaming P25 decoded audio.

No manual steps are required. The scan loop handles both directions automatically.

---

## 7. Active Talkgroup Monitoring

### How talkgroup scan state is persisted

`_talkgroup_scan_overrides` (a `dict[int, bool]`) in `FrequencyManager` is the single source of truth for which talkgroups are scan-enabled. On initialization it is pre-populated with the four TCSO starter talkgroups (2403–2406). The user can modify this through `POST /api/scan-selection`.

### How the trunked scan channel is constructed

`trunked_scan_channel()` dynamically builds a synthetic `Channel` at query time:
- `p25_control_channels_hz` = all control channels from `gatrrs_travis_county.json`
- `scan_enabled = True` (always, since the method checks `enabled_trunked_talkgroup_targets()` before returning)
- The scanner tunes this channel and passes all enabled talkgroup targets to `ManagedP25Decoder.scan_talkgroups()`

### Talkgroup filtering in DSDPlus

`ManagedP25Decoder._start_with_talkgroups()` calls `_set_monitored_talkgroups()` which writes `DSDPlus.groups` — a list of decimal talkgroup IDs. DSDPlus uses this list to filter which voice-grant follow events it acts on. Without this file, DSDPlus follows every voice grant (scanner mode).

---

## 8. Frontend State Flow

```
App.jsx state:
  status          — scanner status (polled every 2s)
  p25Status       — P25 decoder status (polled every 2.5s)
  transcriptStatus— transcriber status
  audioStreamVersion — bumped to force audio element reload
  
Key flows:
  tuneChannel()     → POST /api/scanner/tune → refreshStatus/Receiver
  selectTalkgroup() → POST /api/p25/select-talkgroup
                    → POST /api/transcriber/start   (always, not conditional)
                    → bump audioStreamVersion
  startScanner()    → POST /api/scanner/start
```

**Audio element modulation logic** (`browserAudioModulation`):
- When `transcriptStatus.running && currentModulation === "p25_placeholder"`: audio plays from transcriber SSE stream (DSDPlus WAV path).
- When `transcriptStatus.running && currentModulation` is nfm/am/wfm: audio plays from transcriber SSE stream (rtl_fm pipe path).
- When transcriber is not running: audio element falls back to direct rtl_fm stream (P25 is not supported here; 400 is returned for p25_placeholder in this path).

---

## 9. Key File Map

| File | Role |
|---|---|
| `backend/app.py` | FastAPI app, router mounting |
| `backend/core/scanner_core.py` | Main scanner state machine (scan/hold/tune/search) |
| `backend/radio/frequency_manager.py` | Channel catalog, P25 config, scan candidates |
| `backend/radio/models.py` | Channel, Bank, DecoderStatus, ScannerStatus models |
| `backend/decoders/p25_decoder.py` | ManagedP25Decoder wrapping HeadlessP25Runtime |
| `backend/headless_p25_runtime.py` | DSDPlus + FMP24 subprocess management |
| `backend/transcriber.py` | Audio PCM streaming (rtl_fm pipe or DSDPlus WAV) |
| `backend/api/scanner_routes.py` | Scanner control endpoints |
| `backend/api/p25_routes.py` | P25 talkgroup select/start/stop/status |
| `backend/api/audio_routes.py` | Live audio SSE stream + rtl_fm subprocess |
| `backend/api/transcriber_routes.py` | Transcriber start/stop/status |
| `backend/api/trunked_routes.py` | GATRRS talkgroup catalog endpoints |
| `frontend/src/App.jsx` | All React state, API calls, audio element |
| `frontend/src/components/scanner/ScanFoldersPanel.jsx` | Scan tree with talkgroup selection |
| `configs/trunked/gatrrs_travis_county.json` | GATRRS P25 Phase II system definition |
| `configs/frequencies/sample_frequencies.json` | Conventional channel list |
| `backend/data/default_banks.json` | Bank definitions and priorities |

---

## 10. API Reference

### Scanner Control
| Endpoint | Method | Description |
|---|---|---|
| `/api/scanner/status` | GET | Full scanner state snapshot |
| `/api/scanner/start` | POST | Start scan loop |
| `/api/scanner/stop` | POST | Stop scan loop |
| `/api/scanner/hold` | POST | Hold current channel |
| `/api/scanner/release` | POST | Release hold, resume scan |
| `/api/scanner/skip` | POST | Skip current channel |
| `/api/scanner/next` | POST | Advance to next channel |
| `/api/scanner/manual-tune` | POST | Tune to arbitrary frequency |
| `/api/scanner/tune` | POST | Tune to known channel by ID |
| `/api/scanner/squelch` | POST | Set squelch threshold (dB) |
| `/api/scanner/gain` | POST | Set tuner gain (dB) |
| `/api/scanner/mute` | POST | Toggle mute |
| `/api/scanner/receiver-mode` | POST | Switch receiver mode (RTL-SDR / Demo) |

### P25 / Trunked
| Endpoint | Method | Description |
|---|---|---|
| `/api/p25/status` | GET | P25 decoder snapshot |
| `/api/p25/start` | POST | Start managed P25 runtime on GATRRS |
| `/api/p25/stop` | POST | Stop managed P25 runtime |
| `/api/p25/select-talkgroup` | POST | Lock onto a specific talkgroup decimal |
| `/api/trunked/systems` | GET | GATRRS system definition |
| `/api/trunked/talkgroups` | GET | Full talkgroup catalog |
| `/api/trunked/categories` | GET | Talkgroup category tree |
| `/api/trunked/status` | GET | Trunking health and site info |

### Audio and Transcriber
| Endpoint | Method | Description |
|---|---|---|
| `/api/audio/live` | GET (SSE) | Live PCM audio stream |
| `/api/audio/stop` | POST | Stop rtl_fm audio subprocess |
| `/api/transcriber/status` | GET | Transcriber state and transcripts |
| `/api/transcriber/start` | POST | Start transcriber (auto-detects P25 vs analog) |
| `/api/transcriber/stop` | POST | Stop transcriber |
| `/api/transcriber/clear` | POST | Clear transcript history |

### Frequency / Banks
| Endpoint | Method | Description |
|---|---|---|
| `/api/banks` | GET | All scan banks with enabled state |
| `/api/banks/{id}/enable` | POST | Enable a bank |
| `/api/banks/{id}/disable` | POST | Disable a bank |
| `/api/channels` | GET | All channels (conventional + trunked) |
| `/api/scan-selection` | POST | Bulk update scan-enabled state |
| `/api/bandplans` | GET | Search range definitions |

---

## 11. Known Gaps

1. **Voice-follow observation window**: The trunked scan successfully reaches `control_lock` on 851.3875 MHz, but voice-follow behavior (DSDPlus switching to a granted voice channel mid-call) has not been observed over a sustained active-traffic window. This is a real-world observation gap, not a code bug.

2. **Playwright smoke tests are stale**: Existing desktop e2e specs still target the retired Bearcat playlist UI and will fail. They need to be rewritten for the current ScanFoldersPanel + API set.

3. **Single-RTL device constraint**: The architecture requires one RTL-SDR dongle for both P25 and analog. Monitoring P25 while simultaneously scanning conventional channels is not possible without a second dongle. No multi-device abstraction is implemented.

4. **P25 audio latency**: DSDPlus writes `1R-DSDPlus.wav` to disk; the transcriber reads it in chunks. This creates ~1–2 second latency compared to a streaming pipeline. A named-pipe approach would reduce this but is not implemented.

5. **DSDPlus license requirement**: DSDPlus FastLane license is required for P25 Phase II (TDMA) decoding. The headless runtime validates this at startup (`health: missing_runtime` if DSDPlus is absent or unlicensed).

6. **Multiple uvicorn processes**: Running more than one `uvicorn backend.app:app` instance in the same workspace causes port conflicts and test confusion. Always verify only one backend is running on 127.0.0.1:8000.

---

## 12. Run Commands

**Backend:**
```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner"
backend\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

**Frontend (dev):**
```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm run dev
```

**Frontend (Electron desktop):**
```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm run electron
```

**Backend regression suite:**
```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner"
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_scanner_api.py
```

**Frontend production build:**
```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm run build
```

---

## 13. Change Summary (This Session)

| File | Change |
|---|---|
| `backend/radio/frequency_manager.py` | Pre-populate `_talkgroup_scan_overrides` with TCSO starter TGs; call `_sync_trunked_bank_enabled_state()` at init |
| `frontend/src/App.jsx` | `selectTalkgroup` always starts transcriber (not conditional on wasTranscribing); added 2.5s P25 status poll timer |
| `backend/decoders/p25_decoder.py` | Removed file I/O from `status()` — groups file now only written at start |
| `backend/api/p25_routes.py` | Fixed `_decimal_from_payload` crash on None decimal; added try/except |
| `frontend/src/App.jsx` | Added error handling in `selectTalkgroup` with `setAudioMonitorError` on failure |
