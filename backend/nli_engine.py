"""Real On-Premise Zero-Shot NLI Neural Classifier (MoritzLaurer/mDeBERTa-v3-base-mnli-xnli).

Runs 100% locally on CUDA fp16 (565 MB VRAM) or CPU fallback with local_files_only=True.
Classifies arbitrary free-form Kazakh and Russian emergency reports across 7 operational
classes without relying on hardcoded keywords, returning real neural probability scores.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from .config import WHISPER_LOCAL_ONLY

logger = logging.getLogger("qyran.nli")

NLI_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"

NLI_CLASSES: list[tuple[str, str, str]] = [
    ("drone", "БПЛА / Дрон", "беспилотник, квадрокоптер или летающий дрон в воздухе"),
    ("fire_smoke", "Пожар / Дым", "пожар, огонь, возгорание, пламя, дым или запах гари"),
    ("infrastructure", "Авария инфраструктуры", "авария электросети, подстанции, скачок напряжения, утечка газа или хладагента"),
    ("casualties", "Пострадавшие / 103", "раненые или пострадавшие люди, потеря сознания, нужна скорая медицинская помощь"),
    ("crowd", "Скопление людей", "большое скопление людей, толпа или массовое собрание, нужна полиция"),
    ("armed", "Угроза безопасности", "вооруженные люди, нападение, стрельба или заложники в здании"),
    ("neutralized", "Отбой / Локализовано", "угроза устранена, пожар потушен или локализован, дрон посажен, отбой тревоги"),
]


class LocalNLIClassifier:
    """Thread-safe local mDeBERTa-v3 multilingual zero-shot classifier (Kazakh + Russian)."""

    def __init__(self, model_id: str = NLI_MODEL_ID, local_only: bool = WHISPER_LOCAL_ONLY) -> None:
        self.model_id = model_id
        self.local_only = local_only
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self._lock = threading.Lock()
        self._tokenizer: Any = None
        self._model: Any = None
        self._ent_idx = 0
        self._con_idx = 2
        self.loaded = False
        self.load_time_sec: float | None = None
        self.load_error: str | None = None
        self.last_latency_ms: int = 0
        self.total_inferences: int = 0

    def ensure_loaded(self) -> None:
        if self.loaded:
            return
        with self._lock:
            if self.loaded:
                return
            t0 = time.perf_counter()
            try:
                logger.info("Loading local NLI model %s on %s...", self.model_id, self.device)
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=self.local_only)
                self._model = (
                    AutoModelForSequenceClassification.from_pretrained(
                        self.model_id,
                        dtype=self.dtype,
                        local_files_only=self.local_only,
                    )
                    .to(self.device)
                    .eval()
                )
                id2label = getattr(self._model.config, "id2label", {}) or {}
                for k, v in id2label.items():
                    if "entail" in str(v).lower():
                        self._ent_idx = int(k)
                    elif "contra" in str(v).lower():
                        self._con_idx = int(k)
                self.load_time_sec = round(time.perf_counter() - t0, 2)
                self.loaded = True
                logger.info("Loaded %s in %.2fs on %s", self.model_id, self.load_time_sec, self.device)
            except Exception as exc:
                self.load_error = str(exc)
                logger.warning("Local NLI model unavailable: %s", exc)
                raise

    def status(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "device": self.device,
            "dtype": str(self.dtype).replace("torch.", ""),
            "loaded": self.loaded,
            "load_time_sec": self.load_time_sec,
            "last_latency_ms": self.last_latency_ms,
            "total_inferences": self.total_inferences,
            "error": self.load_error,
        }

    def classify(self, text: str) -> dict[str, Any]:
        """Run real mDeBERTa-v3 zero-shot classification and return normalized scores per class."""
        clean = (text or "").strip()
        if not clean:
            return {"available": False, "top_kind": "other", "top_score": 0.0, "scores": [], "latency_ms": 0}

        try:
            self.ensure_loaded()
        except Exception:
            return {"available": False, "top_kind": "other", "top_score": 0.0, "scores": [], "latency_ms": 0}

        t0 = time.perf_counter()
        with self._lock:
            premises = [clean] * len(NLI_CLASSES)
            hyps = [f"В этом сообщении говорится про: {desc}." for _, _, desc in NLI_CLASSES]
            enc = self._tokenizer(
                premises,
                hyps,
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt",
            ).to(self.device)
            with torch.no_grad():
                logits = self._model(**enc).logits.float()

            # Compute both independent entailment-vs-contradiction confidence and relative distribution
            ent_logits = logits[:, self._ent_idx]
            con_logits = logits[:, self._con_idx]
            margin = ent_logits - con_logits
            indep_probs = torch.sigmoid(margin).cpu().tolist()
            rel_probs = torch.softmax(margin * 0.55, dim=0).cpu().tolist()

        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        self.last_latency_ms = latency_ms
        self.total_inferences += 1

        ranked = []
        for idx, (kind, label_ru, _) in enumerate(NLI_CLASSES):
            ranked.append({
                "kind": kind,
                "label_ru": label_ru,
                "prob": round(float(rel_probs[idx]), 4),
                "entailment": round(float(indep_probs[idx]), 4),
            })
        ranked.sort(key=lambda x: x["entailment"], reverse=True)
        top = ranked[0]

        return {
            "available": True,
            "model_id": self.model_id,
            "device": self.device,
            "latency_ms": latency_ms,
            "top_kind": top["kind"],
            "top_label_ru": top["label_ru"],
            "top_entailment": top["entailment"],
            "top_score": top["prob"],
            "scores": ranked,
        }
