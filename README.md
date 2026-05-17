# TriCore Scanner

TriCore Scanner is a Windows-first RTL-SDR scanner proof-of-concept with a clean scanner-appliance dashboard. Phase 1 focuses on conventional frequency scanning. It does not bypass encryption; encrypted channels must be marked `Unavailable`, muted, and skipped.

The app starts in demo receiver mode, so the dashboard can scan and show activity without an RTL-SDR dongle connected. Real RTL-SDR mode can be enabled later after Zadig, `rtl_test.exe`, and the RTL-SDR DLLs are working.

## Starter Plan

1. Prove the RTL-SDR dongle works on Windows with Zadig and `rtl_test.exe`.
2. Run the FastAPI backend and confirm `/api/status` responds.
3. Add lawful local conventional frequencies to `configs/frequencies/sample_frequencies.json`.
4. Start scanning from the React dashboard.
5. Try manual gain values if the dongle works but the scanner does not stop on signals.
6. Later phases can add SQLite logging, Smart Import, SDRTrunk reference behavior, and Linux backend nodes.

## Project Layout

```text
tricore-scanner/
  backend/
    app.py
    scanner_controller.py
    sdr_device.py
    conventional_scanner.py
    windows_rtlsdr_tools.py
    database.py
    models.py
  frontend/
    src/
      App.jsx
      components/
        TopBar.jsx
        SystemList.jsx
        NowListeningCard.jsx
        ScannerControls.jsx
        RecentCallTicker.jsx
  configs/frequencies/sample_frequencies.json
  sql/sql_create_scanner_tables.sql
  data/recordings/
  data/logs/
```

## Windows Setup

Run these commands in PowerShell where possible.

### 1. Install Python 3

Install Python 3 from <https://www.python.org/downloads/windows/> and check "Add python.exe to PATH".

```powershell
python --version
pip --version
```

### 2. Install Git

Install Git from <https://git-scm.com/download/win>.

```powershell
git --version
```

### 3. Install Node.js LTS

Install Node.js LTS from <https://nodejs.org/>.

```powershell
node --version
npm --version
```

### 4. Install Zadig

Download Zadig from <https://zadig.akeo.ie/>. Plug in the RTL-SDR dongle before opening Zadig.

### 5. Replace the RTL-SDR Driver With WinUSB

1. Open Zadig as Administrator.
2. Select `Options > List All Devices`.
3. Choose `Bulk-In, Interface (Interface 0)` or the RTL-SDR device.
4. Select `WinUSB`.
5. Click `Replace Driver` or `Install Driver`.

Do not select your keyboard, mouse, webcam, or audio device. If unsure, unplug the RTL-SDR, reopen Zadig, then plug it back in and look for the new device.

### 6. Install RTL-SDR Command-Line Tools

One simple Windows layout is:

```powershell
New-Item -ItemType Directory -Force C:\rtl-sdr
```

Download a Windows RTL-SDR tools ZIP that includes `rtl_test.exe`, extract it, and place the EXE/DLL files in:

```text
C:\rtl-sdr
```

Then add `C:\rtl-sdr` to your user PATH, or run tools with the full path.

### 7. Test the Dongle

```powershell
C:\rtl-sdr\rtl_test.exe -t
```

Expected signs:

```text
Found 1 device(s)
Using device 0
Found Rafael Micro R820T tuner
```

If that works, the Windows driver and dongle are ready.

### 8. Install Python Dependencies

```powershell
cd "D:\Scanner SDR\SDRTrunk\tricore-scanner\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 9. Run the Backend

```powershell
cd "D:\Scanner SDR\SDRTrunk\tricore-scanner\backend"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/api/status
```

To start scanning from PowerShell:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/scanner/start
```

The default receiver mode is simulated, so this works without the dongle.

To try gain now:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/scanner/gain -ContentType "application/json" -Body '{"gain_db":28}'
```

To switch back to auto gain:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/scanner/gain -ContentType "application/json" -Body '{"gain_db":null}'
```

To switch to real RTL-SDR mode later, stop scanning first and run:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/scanner/receiver-mode -ContentType "application/json" -Body '{"simulated":false}'
```

To switch back to demo mode:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/scanner/receiver-mode -ContentType "application/json" -Body '{"simulated":true}'
```

### 10. Run the Frontend

```powershell
cd "D:\Scanner SDR\SDRTrunk\tricore-scanner\frontend"
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Frequency Config

Edit:

```text
D:\Scanner SDR\SDRTrunk\tricore-scanner\configs\frequencies\sample_frequencies.json
```

Use frequencies in Hz:

```json
{
  "id": "noaa-weather-demo",
  "name": "NOAA Weather Demo",
  "system": "Local Weather Radio",
  "frequency_hz": 162550000,
  "modulation": "nfm",
  "encrypted": false,
  "favorite": true
}
```

## Troubleshooting

### Zadig / WinUSB

If `rtl_test.exe` says no supported devices found, the RTL-SDR probably still has the wrong driver. Reopen Zadig as Administrator, enable `List All Devices`, choose the RTL-SDR bulk interface, and install `WinUSB`.

### Device Not Found

Check:

```powershell
C:\rtl-sdr\rtl_test.exe -t
```

Close SDR#, SDRTrunk, or any other app using the dongle. Only one program can usually use the RTL-SDR at a time.

### Python Dependency Problems

If `pip install -r requirements.txt` fails, upgrade pip first:

```powershell
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

If `pyrtlsdr` imports but cannot find RTL-SDR DLLs, put the RTL-SDR DLL files in `C:\rtl-sdr` and add that folder to PATH before starting PowerShell.

### Weak Signals or Scanner Never Stops

Try gain values from the dashboard or API:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/scanner/gain -ContentType "application/json" -Body '{"gain_db":36.4}'
```

Also adjust `signal_threshold` in `backend/scanner_controller.py`. A lower threshold stops more often; a higher threshold ignores weak activity.

## User-Friendly Label Mapping

| Technical Term | TriCore Label |
| --- | --- |
| Talkgroup | Channel |
| TGID | Channel ID |
| Lockout | Hide Channel |
| Encryption | Unavailable |
| Control Channel | System Signal |
| Trunked System | Radio System |
| Hold | Stay Here |

## Smart Import Direction

TriCore should not scrape RadioReference pages. Later Smart Import should use the official RadioReference Web Service with the user's own login, CSV import, or manual entry. Raw imported data stays separate from cleaned scanner-ready tables.

## Trunking Direction

Do not implement trunking decoding from scratch in Phase 1. Windows can reference SDRTrunk behavior later. Linux or Raspberry Pi nodes can eventually run OP25 or other lawful decoders while the Windows app remains the clean UI.

## Next Steps

- Replace demo frequencies with lawful local conventional frequencies.
- Confirm `rtl_test.exe -t` works.
- Run backend and frontend.
- Try gain values: auto, `19.7`, `28`, `36.4`, `49.6`.
- Tune the signal threshold for your local RF environment.
- Add SQLite logging using `sql/sql_create_scanner_tables.sql`.
- Add WebSocket status updates.
- Add Smart Import CSV preview.
- Design SDRTrunk/Linux backend integration after the conventional scanner proof works.
