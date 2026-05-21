from fastapi.testclient import TestClient
from backend.app import app
import json

client = TestClient(app)

def test_audio(freq, mode):
    params = {'frequency': freq, 'mode': mode}
    response = client.get('/api/audio/live', params=params)
    print(f'Freq: {freq}, Mode: {mode}')
    print(f'Status: {response.status_code}')
    print(f'Detail: {json.dumps(response.json())}')
    print('---')

test_audio(162550000, 'nfm')
test_audio(120500000, 'am')
