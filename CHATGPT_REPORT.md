# TriCore Progress Report

Date: 2026-05-18

## Current Mission

TriCore is now operating as a standalone scanner-appliance foundation with a working backend/frontend build, Demo fallback mode, and a real RTL-SDR receiver path behind the existing abstraction. This build still intentionally excludes logging, transcription, Smart Import, database storage, and real P25 trunking.

- Scanner Core
- Frequency Manager
- SDR Receiver abstraction
- Demo receiver
- RTL-SDR receiver engine with clean fallback to Demo mode
- Decoder abstraction
- Analog NFM, WFM, AM decoder placeholders
- P25/trunking placeholders for later
- Scanner-style React UI

## Progress This Pass

Implemented the real RTL-SDR backend path without changing the scanner architecture:

- RTL-SDR device detection
- RTL-SDR open/close lifecycle
- Frequency tuning through the receiver abstraction
- Manual gain and auto gain handling
- Sample acquisition through `pyrtlsdr`
- Basic relative signal/RSSI measurement
- Receiver status reporting through the existing API
- Friendly hardware/library error messages
- Clean automatic fallback to Demo mode when RTL-SDR is unavailable
- Windows DLL discovery/bootstrap so `pyrtlsdr` can find `librtlsdr` in bundled/runtime locations

## Foundation Already In Place

Backend structure in place:

- `backend/core/scanner_core.py`
- `backend/core/scanner_state.py`
- `backend/core/scanner_actions.py`
- `backend/radio/models.py`
- `backend/radio/banks.py`
- `backend/radio/bandplans.py`
- `backend/radio/frequency_manager.py`
- `backend/sdr/base_receiver.py`
- `backend/sdr/demo_receiver.py`
- `backend/sdr/rtl_sdr_receiver.py`
- `backend/sdr/signal_meter.py`
- `backend/decoders/*`
- `backend/api/scanner_routes.py`
- `backend/api/frequency_routes.py`
- `backend/api/receiver_routes.py`
- `backend/data/default_banks.json`
- `backend/data/bandplans.json`

Frontend scanner appliance UI in place:

- `frontend/src/App.jsx`
- `frontend/src/components/NowListeningCard.jsx`
- `frontend/src/components/scanner/TopStatusBar.jsx`
- `frontend/src/components/scanner/BankPanel.jsx`
- `frontend/src/components/scanner/ChannelChart.jsx`
- `frontend/src/components/scanner/ScannerKeypad.jsx`
- `frontend/src/components/scanner/SignalMeter.jsx`
- `frontend/src/components/scanner/ReceiverPanel.jsx`
- `frontend/src/components/scanner/SearchPanel.jsx`

## Backend API Surface

Working scanner routes:

- `GET /api/scanner/status`
- `POST /api/scanner/start`
- `POST /api/scanner/stop`
- `POST /api/scanner/pause`
- `POST /api/scanner/resume`
- `POST /api/scanner/hold`
- `POST /api/scanner/release`
- `POST /api/scanner/release-hold`
- `POST /api/scanner/clear-hold`
- `POST /api/scanner/next`
- `POST /api/scanner/skip`
- `POST /api/scanner/lockout`
- `POST /api/scanner/priority`
- `POST /api/scanner/manual-tune`
- `POST /api/scanner/search/start`
- `POST /api/scanner/search/stop`
- `POST /api/scanner/squelch`
- `POST /api/scanner/gain`
- `POST /api/scanner/mute`
- `POST /api/scanner/receiver-mode`

Working frequency/receiver routes:

- `GET /api/banks`
- `POST /api/banks/{bank_id}/enable`
- `POST /api/banks/{bank_id}/disable`
- `GET /api/channels`
- `GET /api/bandplans`
- `GET /api/receiver/status`
- `POST /api/receiver/mode`
- `GET /api/status` compatibility alias
- `GET /api/health`

Receiver behavior now verified:

- `GET /api/receiver/status` reports Demo or RTL-SDR through the existing receiver API
- `POST /api/receiver/mode` can request Demo or RTL-SDR mode
- If RTL-SDR is unavailable, the backend stays usable in Demo mode and returns a clear error
- Frontend does not know about `pyrtlsdr` or hardware details directly

## Default Banks

The app now ships with 9 default banks:

- Public Safety
- Fire / EMS
- Railroad
- Airband
- Marine
- NOAA Weather
- FM Broadcast
- Business / Local
- Custom

## Default Bandplans

The app now ships with 7 bandplans:

- FM Broadcast, 88-108 MHz, WFM
- NOAA Weather, 162.400-162.550 MHz, NFM
- Airband, 118-137 MHz, AM
- Marine VHF, 156-162 MHz, NFM
- Railroad AAR, 160-161.995 MHz, NFM
- Public Safety VHF placeholder
- Public Safety UHF placeholder

## Verified Test Results

Backend health:

- `GET /api/health` returned `ok: true`
- `logging: false`
- `transcription: false`
- `smart_import: false`
- `p25_trunking: placeholder`

Scanner/API smoke results:

- banks: 9
- channels: 88
- bandplans: 7
- receiver: Demo
- start: scanning
- hold: holding
- release: scanning
- next: scanning
- NOAA search: searching
- stop: stopped

RTL-SDR receiver validation:

- `pyrtlsdr` imports successfully in the backend venv
- Windows DLL bootstrap now discovers RTL-SDR runtime folders before receiver open
- Live receiver probe reported hardware available in this environment
- Demo fallback tests still pass when hardware or libraries are unavailable
- Manual gain and auto gain paths were both validated in tests

Backend tests:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_scanner_api.py
```

Result:

```text
10 passed in 4.33s
```

Frontend production build:

```powershell
cd frontend
npm run build
```

Result:

```text
vite build completed successfully
```

Browser UI smoke:

- Opened `http://127.0.0.1:5173/`
- Verified visible UI sections:
  - TriCore Scanner
  - Banks
  - Now Listening
  - Station Chart
  - Scanner Keypad
  - Receiver
  - Search / Manual
- Clicked `Scan`
- Verified scanner shows active scanning/listening state
- Clicked `Stay Here`
- Verified holding/stay-here state
- Screenshot saved at:
  - `tricore-ui-smoke.png`

## Current Run URLs

Backend:

```text
http://127.0.0.1:8000
```

Frontend:

```text
http://127.0.0.1:5173/
```

## Commands To Run

Run backend:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner"
backend\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Run frontend:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm run dev
```

Run backend tests:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner"
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Run frontend build:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm run build
```

## Important Limitations

- Demo receiver still simulates signal activity and scanner motion when live hardware is unavailable.
- Analog NFM/WFM/AM decoders are placeholders behind clean interfaces.
- P25 decoder is a placeholder only.
- Trunking controller is a placeholder only.
- No external popup decoder apps are launched from the new scanner path.
- Encrypted channels are treated as Unavailable and skipped.
- Logging was not added.
- Transcription was not added.
- Smart Import was not added.
- Database storage was not added.
- RadioReference scraping was not added.

## Repo Update

Repository remote:

- `origin` -> `https://github.com/mimhoff25-svg/TriCore`

Current intent for repo updates:

- Keep generated runtime/cache artifacts out of Git
- Keep scanner architecture stable
- Continue implementing hardware capabilities behind backend abstractions only

## Recommended Next Build Step

Next should stay within the existing architecture and move to the next scanner capability without adding logging/import/transcription/trunking prematurely. A reasonable next step is expanding live receiver-backed analog decode behavior while keeping Demo fallback intact.

1. Harden receiver mode switching under repeated scan/start/stop cycles.
2. Expand analog decoder behavior behind the existing decoder interfaces.
3. Keep encrypted or unavailable channels skipped.
4. Keep all hardware handling behind backend receiver abstractions.

