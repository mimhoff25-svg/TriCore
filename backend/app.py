from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.frequency_routes import router as frequency_router
from .api.receiver_routes import router as receiver_router
from .api.scanner_routes import router as scanner_router
from .api.shared import scanner_core


app = FastAPI(title="TriCore SDR Scanner", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scanner_router)
app.include_router(frequency_router)
app.include_router(receiver_router)


@app.get("/api/status")
def legacy_status():
    return scanner_core.status()


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "app": "TriCore",
        "mode": "standalone SDR scanner foundation",
        "logging": False,
        "transcription": False,
        "smart_import": False,
        "p25_trunking": "placeholder",
    }

