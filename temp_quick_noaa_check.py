from fastapi.testclient import TestClient
from backend.app import app
from backend.api.shared import scanner_core

client = TestClient(app)
scanner_core.manual_tune(frequency_hz=162550000, modulation='nfm', name='NOAA 162.550')
r = client.get('/api/audio/live', params={'frequency_hz':162550000,'modulation':'nfm','squelch_db':-68})
print('status=', r.status_code)
try:
    print('detail=', r.json().get('detail', 'ok'))
except Exception:
    print('detail=', 'non-json response')
