# TriCore Scanner

TriCore is a standalone SDR scanner appliance app.

TriCore makes an RTL-SDR feel like a real scanner radio. It organizes frequencies into banks and service types, supports scanner-style controls, and keeps receiver/decoder logic inside one clean app.

## Current Focus

Phase 1 is the scanner foundation:

- scanner controls
- banks and service types
- bandplans and manual tune
- demo mode with no hardware required
- real RTL-SDR receiver support behind the backend receiver abstraction
- scanner-style UI panels and channel charting

This phase is not focused on logging, transcription, Smart Import, or full P25 trunking.

- logging is not the current focus
- Smart Import is later
- P25/trunking is later
- encrypted or unavailable channels must remain skipped and must never be decoded

## What TriCore Is

TriCore is intended to feel like a real scanner radio rather than a loose collection of SDR helper tools.

The app already includes:

- scanner core foundation
- frequency manager foundation
- SDR receiver abstraction
- Demo receiver
- RTL-SDR receiver implementation
- decoder abstractions and placeholders
- scanner-style React UI
- default banks
- default bandplans
- backend tests
- frontend production build

## Main Architecture

### Backend

The rebuilt backend is organized around the scanner foundation:

```text
backend/
  api/
  core/
  data/
  decoders/
  radio/
  sdr/
  app.py
  requirements.txt
```

Primary areas:

- `backend/core` for scanner state, actions, and orchestration
- `backend/radio` for banks, bandplans, channels, frequency management, and shared models
- `backend/sdr` for the receiver abstraction, Demo receiver, RTL-SDR receiver, and signal helpers
- `backend/decoders` for decoder abstractions and placeholders
- `backend/api` for scanner, frequency, and receiver routes
- `backend/data` for default banks and bandplans

### Frontend

The scanner appliance UI is built around these components:

- `TopStatusBar`
- `BankPanel`
- `NowListeningCard`
- `ChannelChart`
- `ScannerKeypad`
- `SignalMeter`
- `ReceiverPanel`
- `SearchPanel`

## Receiver Modes

TriCore supports two receiver modes.

### Demo Mode

Demo mode works without hardware and is the safe fallback when an RTL-SDR is not available.

Use Demo mode when:

- no RTL-SDR dongle is attached
- RTL-SDR DLLs are not installed yet
- you want to test the scanner UI and backend behavior offline

### RTL-SDR Mode

Real RTL-SDR mode is implemented behind the backend receiver abstraction in `backend/sdr/rtl_sdr_receiver.py`.

The frontend does not depend on `pyrtlsdr` directly and only uses the receiver status API.

On Windows, real RTL-SDR mode requires:

- Zadig
- WinUSB
- a working RTL-SDR dongle
- RTL-SDR DLLs and tools available on the system or in TriCore runtime locations

If no RTL-SDR dongle is detected, or the DLLs cannot be loaded, TriCore should fail gracefully and remain usable in Demo mode.

## Windows Hardware Setup

### 1. Install Zadig and WinUSB

1. Plug in the RTL-SDR dongle.
2. Open Zadig as Administrator.
3. Enable `Options > List All Devices`.
4. Select the RTL-SDR bulk interface.
5. Install or replace the driver with `WinUSB`.

### 2. Provide RTL-SDR tools and DLLs

On Windows, TriCore can discover RTL-SDR DLLs from common runtime folders, including bundled runtime locations and paths such as `C:\rtl-sdr`.

Typical validation command:

```powershell
C:\rtl-sdr\rtl_test.exe -t
```

Expected signs:

```text
Found 1 device(s)
Using device 0
Found Rafael Micro R820T tuner
```

## API Overview

Primary scanner routes:

- `GET /api/scanner/status`
- `POST /api/scanner/start`
- `POST /api/scanner/stop`
- `POST /api/scanner/pause`
- `POST /api/scanner/resume`
- `POST /api/scanner/hold`
- `POST /api/scanner/release`
- `POST /api/scanner/skip`
- `POST /api/scanner/next`
- `POST /api/scanner/lockout`
- `POST /api/scanner/priority`
- `POST /api/scanner/manual-tune`
- `POST /api/scanner/tune`
- `POST /api/scanner/search/start`
- `POST /api/scanner/search/stop`
- `POST /api/scanner/squelch`
- `POST /api/scanner/gain`
- `POST /api/scanner/mute`
- `POST /api/scanner/receiver-mode`

Related frequency and receiver routes:

- `GET /api/banks`
- `POST /api/banks/{bank_id}/enable`
- `POST /api/banks/{bank_id}/disable`
- `GET /api/channels`
- `GET /api/bandplans`
- `GET /api/receiver/status`
- `POST /api/receiver/mode`

Compatibility aliases still exist where useful:

- `GET /api/status`
- `POST /api/scanner/release-hold`
- `POST /api/scanner/clear-hold`

## Scanner Wording

TriCore uses scanner-friendly wording where possible:

| Technical Term | TriCore Label |
| --- | --- |
| Hold | Stay Here |
| Lockout | Hide Channel |
| Encryption | Unavailable |
| Talkgroup | Channel |
| TGID | Channel ID |
| Control Channel | System Signal |
| Trunked System | Radio System |

## Legacy and Transitional Files

The repo still contains earlier or transitional modules such as:

- `backend/scanner_controller.py`
- `backend/sdr_device.py`
- `backend/conventional_scanner.py`
- `backend/windows_rtlsdr_tools.py`

These should not be read as the main architecture of the rebuilt scanner foundation.

- `backend/windows_rtlsdr_tools.py` remains an active support module for Windows RTL-SDR tool and DLL discovery
- `backend/scanner_controller.py`, `backend/sdr_device.py`, and `backend/conventional_scanner.py` are legacy or transitional compatibility modules from earlier iterations

The main scanner-appliance architecture for this phase is the `backend/core`, `backend/radio`, `backend/sdr`, `backend/decoders`, `backend/api`, and `backend/data` layout.

## Experimental and Future Areas

This pass does not expand:

- logging
- transcription
- Smart Import
- RadioReference scraping
- full P25 trunking

If earlier experimental files or endpoints still exist, they should be treated as future or transitional work unless they are needed for startup compatibility.

## Run Commands

Backend:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner"
backend\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Frontend development server:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm install
npm run dev
```

Desktop shell:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm run desktop
```

Backend tests:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner"
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_scanner_api.py
```

Frontend production build:

```powershell
cd "c:\Users\mimho\Documents\GitHub\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm run build
```

## Current Limitations

- analog decoder modules remain placeholders behind the decoder abstraction
- full P25 trunking is not part of this scanner-foundation pass
- logging is not the current focus
- Smart Import is not part of this phase
- transcription is not part of this phase
- encrypted or unavailable channels must remain skipped
- tests do not require real RTL-SDR hardware

## Mission Direction

TriCore is being stabilized as one clean scanner application with banks, service types, scanner controls, Demo mode, real RTL-SDR support behind the receiver abstraction, and clear status for receiver mode, state, signal, squelch, gain, and channel selection.

The current pass is scanner foundation cleanup and stabilization only.
