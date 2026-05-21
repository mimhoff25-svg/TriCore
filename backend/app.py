from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.audio_routes import router as audio_router, stop_live_audio_process
from .api.frequency_routes import router as frequency_router
from .api.p25_routes import router as p25_router
from .api.receiver_routes import router as receiver_router
from .api.scanner_routes import router as scanner_router
from .api.shared import scanner_core
from .api.transcriber_routes import router as transcriber_router
from .api.trunked_routes import router as trunked_router
from .transcriber import transcriber


def stop_runtime_services() -> None:
    stop_live_audio_process()
    try:
        transcriber.stop()
    except Exception:
        pass
    try:
        scanner_core.stop()
    except Exception:
        pass
    try:
        scanner_core.stop_p25_decoder()
    except Exception:
        pass
    try:
        scanner_core.receiver.close()
    except Exception:
        pass


def _schedule_process_exit(delay_seconds: float = 0.1) -> None:
    def exit_later() -> None:
        time.sleep(delay_seconds)
        os._exit(0)

    thread = threading.Thread(target=exit_later, daemon=True)
    thread.start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop_runtime_services()
    yield
    stop_runtime_services()


app = FastAPI(title="TriCore SDR Scanner", version="0.2.0", lifespan=lifespan)

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
app.include_router(audio_router)
app.include_router(transcriber_router)
app.include_router(trunked_router)
app.include_router(p25_router)


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
        "transcription": True,
        "smart_import": False,
        "p25_trunking": "managed",
    }


@app.post("/api/system/shutdown")
def shutdown_system(background_tasks: BackgroundTasks):
    stop_runtime_services()
    background_tasks.add_task(_schedule_process_exit)
    return {"ok": True}
