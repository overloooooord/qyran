"""Real Text-to-Speech (TTS) Engine for Kazakh and Russian Radio Dispatch.

Generates genuine spoken WAV audio using neural Kazakh/Russian voices via edge-tts
with automatic offline fallback to local espeak-ng, plus optional 300-3400 Hz VHF/UHF
radio channel passband filtering so commander broadcasts sound like authentic radio traffic.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import wavfile

from .audio_dsp import apply_radio_degradation
from .config import DATA_DIR

logger = logging.getLogger("qyran.tts")

TTS_DIR = DATA_DIR / "tts_cache"
TTS_DIR.mkdir(parents=True, exist_ok=True)

VOICES: dict[str, dict[str, str]] = {
    "kk_male": {"id": "kk-KZ-DauletNeural", "lang": "kk", "label": "Қазақша (Daulet, муж.)"},
    "kk_female": {"id": "kk-KZ-AigulNeural", "lang": "kk", "label": "Қазақша (Aigul, жен.)"},
    "ru_male": {"id": "ru-RU-DmitryNeural", "lang": "ru", "label": "Русский (Dmitry, муж.)"},
    "ru_female": {"id": "ru-RU-SvetlanaNeural", "lang": "ru", "label": "Русский (Svetlana, жен.)"},
}


class TTSEngine:
    """Synthesizes Kazakh/Russian speech WAV clips with optional analog radio filtering."""

    def __init__(self) -> None:
        self.last_latency_ms: int = 0
        self.total_syntheses: int = 0
        self.last_backend: str = "neural-edge-tts + espeak-ng offline fallback"

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "voices": VOICES,
            "last_backend": self.last_backend,
            "last_latency_ms": self.last_latency_ms,
            "total_syntheses": self.total_syntheses,
        }

    def synthesize(
        self,
        text: str,
        *,
        voice_key: str = "auto",
        radio_effect: bool = False,
    ) -> dict[str, Any]:
        clean = (text or "").strip()
        if not clean:
            raise ValueError("Пустой текст для синтеза речи")

        if voice_key not in VOICES:
            has_kk = any(ch in clean.lower() for ch in "әіңғүұқөһ")
            voice_key = "kk_male" if has_kk else "ru_male"

        vinfo = VOICES[voice_key]
        t0 = time.perf_counter()
        out_name = f"tts_{uuid.uuid4().hex[:10]}.wav"
        out_path = TTS_DIR / out_name
        backend_used = "neural-tts"

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mp3_path = td_path / "raw.mp3"
            raw_wav = td_path / "raw_16k.wav"

            neural_ok = False
            try:
                res = subprocess.run(
                    [
                        "uvx",
                        "--from",
                        "edge-tts",
                        "edge-tts",
                        "--voice",
                        vinfo["id"],
                        "--text",
                        clean,
                        "--write-media",
                        str(mp3_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=14,
                )
                if res.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 400:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-i",
                            str(mp3_path),
                            "-ar",
                            "16000",
                            "-ac",
                            "1",
                            "-c:a",
                            "pcm_s16le",
                            str(raw_wav),
                        ],
                        check=True,
                    )
                    neural_ok = True
                    backend_used = f"neural-tts ({vinfo['id']})"
            except Exception as exc:
                logger.debug("Neural TTS unavailable, falling back to offline espeak-ng: %s", exc)

            if not neural_ok:
                es_lang = "ru" if vinfo["lang"] == "ru" else "ky"
                tmp_es = td_path / "es.wav"
                subprocess.run(["espeak-ng", "-v", es_lang, "-s", "150", "-w", str(tmp_es), clean], check=True)
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(tmp_es),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(raw_wav),
                    ],
                    check=True,
                )
                backend_used = f"espeak-ng-offline ({es_lang})"

            sr, pcm = wavfile.read(raw_wav)
            samples = pcm.astype(np.float32) / 32768.0
            if radio_effect:
                samples = apply_radio_degradation(samples, sr=sr, noise_level=0.020)
                # Subtle roger beep at end of radio dispatch
                t_b = np.linspace(0, 0.08, int(sr * 0.08), endpoint=False)
                beep = (0.15 * np.sin(2 * np.pi * 1350 * t_b) * np.hanning(len(t_b))).astype(np.float32)
                pad = np.zeros(int(sr * 0.06), dtype=np.float32)
                samples = np.clip(np.concatenate([samples, pad, beep, pad]), -0.98, 0.98)

            out_pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
            wavfile.write(out_path, sr, out_pcm)
            dur = round(len(out_pcm) / float(sr), 2)

        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        self.last_latency_ms = latency_ms
        self.total_syntheses += 1
        self.last_backend = backend_used

        return {
            "filename": out_name,
            "audio_url": f"/api/tts/file/{out_name}",
            "path": str(out_path),
            "text": clean,
            "voice_key": voice_key,
            "voice_label": vinfo["label"],
            "lang": vinfo["lang"],
            "radio_effect": radio_effect,
            "duration_sec": dur,
            "latency_ms": latency_ms,
            "backend": backend_used,
        }
