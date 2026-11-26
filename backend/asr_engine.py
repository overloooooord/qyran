"""Real On-Premise Whisper ASR Engine with Anti-Hallucination & Bilingual KK/RU Rescoring."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

from .config import WHISPER_LOCAL_ONLY, WHISPER_MODEL_ID

logger = logging.getLogger("qyran.asr")

# Known Whisper silence/noise hallucinations across RU/KK/EN radio channels
HALLUCINATION_PATTERNS = [
    r"продолжение следует",
    r"субтитры\s+(?:сделал|создавал|подготовил|добавил)",
    r"спасибо\s+за\s+просмотр",
    r"подписывайтесь\s+на\s+канал",
    r"редактор\s+субтитров",
    r"thank you for watching",
    r"please subscribe",
    r"^\s*[\.\,\-\!\?\…\s]+$",
]
HALLUCINATION_RE = re.compile("|".join(HALLUCINATION_PATTERNS), re.IGNORECASE)


@dataclass
class ASRResult:
    raw_text: str
    detected_lang: str  # "kk" or "ru"
    confidence: float
    latency_ms: int
    rtf: float
    device: str
    model_id: str
    hallucination_recovered: bool = False
    rescore_note: str | None = None


def _is_hallucination(text: str, duration_sec: float) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if HALLUCINATION_RE.search(cleaned):
        return True
    words = re.findall(r"[\wӘәІіҢңҒғҮүҰұҚқӨөҺһ]+", cleaned)
    # Long voiced audio collapsing into 1-2 words is a classic radio-static hallucination
    if duration_sec >= 4.0 and len(words) <= 2:
        return True
    # Repeated token loop detection (e.g. "да да да да да")
    if len(words) >= 6 and len(set(w.lower() for w in words)) <= 2:
        return True
    return False


class LocalWhisperEngine:
    """Thread-safe local Whisper Large v3 Turbo running 100% on-premise (CUDA fp16 / CPU fp32)."""

    def __init__(self, model_id: str = WHISPER_MODEL_ID, local_only: bool = WHISPER_LOCAL_ONLY) -> None:
        self.model_id = model_id
        self.local_only = local_only
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self._lock = threading.Lock()
        self._processor: Any = None
        self._model: Any = None
        self.loaded = False
        self.load_time_sec: float | None = None
        self.load_error: str | None = None

    def ensure_loaded(self) -> None:
        if self.loaded:
            return
        with self._lock:
            if self.loaded:
                return
            t0 = time.perf_counter()
            try:
                logger.info("Loading local ASR model %s on %s (%s)...", self.model_id, self.device, self.dtype)
                self._processor = AutoProcessor.from_pretrained(
                    self.model_id, local_files_only=self.local_only
                )
                self._model = (
                    AutoModelForSpeechSeq2Seq.from_pretrained(
                        self.model_id,
                        dtype=self.dtype,
                        local_files_only=self.local_only,
                    )
                    .to(self.device)
                    .eval()
                )
                # Suppress deprecation/max_length conflicts cleanly
                if hasattr(self._model, "generation_config") and self._model.generation_config is not None:
                    self._model.generation_config.max_length = None
                self.load_time_sec = round(time.perf_counter() - t0, 2)
                self.loaded = True
                logger.info("Loaded %s in %.2fs on %s", self.model_id, self.load_time_sec, self.device)
            except Exception as exc:
                self.load_error = str(exc)
                logger.exception("Failed to load local Whisper model: %s", exc)
                raise

    def status(self) -> dict[str, Any]:
        gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        return {
            "model_id": self.model_id,
            "device": self.device,
            "gpu_name": gpu_name,
            "dtype": str(self.dtype).replace("torch.", ""),
            "loaded": self.loaded,
            "load_time_sec": self.load_time_sec,
            "local_only": self.local_only,
            "error": self.load_error,
        }

    def _decode_once(
        self, feats: torch.Tensor, language: str | None = None
    ) -> tuple[str, str, float]:
        gen_kwargs: dict[str, Any] = {
            "task": "transcribe",
            "max_new_tokens": 180,
            "return_dict_in_generate": True,
            "output_scores": True,
            "no_repeat_ngram_size": 4,
        }
        if language in ("kk", "ru"):
            gen_kwargs["language"] = language

        with torch.no_grad():
            out = self._model.generate(feats, **gen_kwargs)

        seq = out.sequences[0]
        lang_tok = self._processor.tokenizer.decode([int(seq[1])]) if len(seq) > 1 else ""
        detected = "kk" if "kk" in lang_tok else ("ru" if "ru" in lang_tok else (language or "ru"))
        if language in ("kk", "ru"):
            detected = language

        text = self._processor.batch_decode(out.sequences, skip_special_tokens=True)[0].strip()

        # Mean softmax probability over generated tokens -> real calibrated confidence
        if out.scores:
            scores = torch.stack(out.scores, dim=1)[0]
            gen_tokens = seq[-scores.shape[0] :]
            probs = torch.softmax(scores.float(), dim=-1)
            tok_probs = probs[torch.arange(len(gen_tokens), device=probs.device), gen_tokens]
            conf = float(tok_probs.mean().item())
        else:
            conf = 0.80

        return text, detected, round(max(0.0, min(1.0, conf)), 3)

    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int = 16000,
        language: str = "auto",
    ) -> ASRResult:
        """Transcribe 16 kHz mono audio with automatic KK/RU anti-hallucination rescoring."""
        self.ensure_loaded()
        duration = max(0.05, len(samples) / float(sample_rate))
        t0 = time.perf_counter()

        with self._lock:
            inputs = self._processor(samples, sampling_rate=sample_rate, return_tensors="pt")
            feats = inputs.input_features.to(device=self.device, dtype=self.dtype)

            hint = language if language in ("kk", "ru") else None
            text, detected, conf = self._decode_once(feats, language=hint)
            recovered = False
            rescore_note: str | None = None

            # Anti-hallucination & Kazakh/Russian radio-channel dual-hypothesis rescoring
            if hint is None and (_is_hallucination(text, duration) or detected not in ("kk", "ru")):
                cand_kk = self._decode_once(feats, language="kk")
                cand_ru = self._decode_once(feats, language="ru")
                scored = []
                for c_txt, c_lang, c_conf in (cand_kk, cand_ru):
                    pen = -0.5 if _is_hallucination(c_txt, duration) else 0.0
                    # Kazakh specific letters boost Kazakh hypothesis slightly if valid
                    kk_chars = len(re.findall(r"[әіңғүұқөһӘІҢҒҮҰҚӨҺ]", c_txt))
                    bonus = 0.04 if (c_lang == "kk" and kk_chars >= 2) else 0.0
                    scored.append((c_conf + pen + bonus, c_txt, c_lang, c_conf))
                scored.sort(key=lambda x: x[0], reverse=True)
                _, best_txt, best_lang, best_conf = scored[0]
                if not _is_hallucination(best_txt, duration):
                    rescore_note = f"Anti-hallucination KK/RU rescore: recovered '{best_lang}' (raw auto was '{text[:32]}')"
                    text, detected, conf = best_txt, best_lang, best_conf
                    recovered = True
            elif hint in ("kk", "ru") and _is_hallucination(text, duration):
                alt = "ru" if hint == "kk" else "kk"
                alt_txt, alt_lang, alt_conf = self._decode_once(feats, language=alt)
                if not _is_hallucination(alt_txt, duration):
                    rescore_note = f"Fallback language switch {hint}->{alt} avoided hallucination"
                    text, detected, conf = alt_txt, alt_lang, alt_conf
                    recovered = True

        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        rtf = round((latency_ms / 1000.0) / duration, 3)

        return ASRResult(
            raw_text=text,
            detected_lang=detected,
            confidence=conf,
            latency_ms=latency_ms,
            rtf=rtf,
            device=self.device,
            model_id=self.model_id,
            hallucination_recovered=recovered,
            rescore_note=rescore_note,
        )
