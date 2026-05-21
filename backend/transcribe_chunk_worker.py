from __future__ import annotations

import json
import sys

import httpx
from faster_whisper import WhisperModel
from huggingface_hub.utils import set_client_factory


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing WAV path."}))
        return 2

    wav_path = sys.argv[1]
    model_size = sys.argv[2] if len(sys.argv) > 2 else "base"

    set_client_factory(lambda: httpx.Client(follow_redirects=True, timeout=None, verify=False))
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        wav_path,
        language="en",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=1,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    print(json.dumps({"text": text}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
