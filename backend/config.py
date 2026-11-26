"""Central configuration for QYRAN 2.0 (IT FEST 2026 Edition)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SCENARIOS_DIR = DATA_DIR / "scenarios"
FRONTEND_DIR = BASE_DIR / "frontend"
DOCS_DIR = BASE_DIR / "docs"
ASSETS_DIR = BASE_DIR / "assets"
DB_PATH = DATA_DIR / "qyran_ops.db"

# On-premise ASR model (local HuggingFace cache, zero cloud egress)
WHISPER_MODEL_ID = os.getenv("QYRAN_WHISPER_MODEL", "openai/whisper-large-v3-turbo")
WHISPER_LOCAL_ONLY = os.getenv("QYRAN_LOCAL_ONLY", "1") == "1"

# Optional on-premise OpenAI-compatible LLM (LM Studio / Ollama, e.g. http://localhost:1234/v1)
LOCAL_LLM_URL = os.getenv("QYRAN_LLM_URL", "http://localhost:1234/v1")
LOCAL_LLM_MODEL = os.getenv("QYRAN_LLM_MODEL", "")
LOCAL_LLM_ENABLED = os.getenv("QYRAN_LLM_ENABLED", "1") == "1"

# Optional Telegram Bot P1 Alerting (stays strictly off/dry-run when unset for air-gapped demos)
TG_BOT_TOKEN = os.getenv("QYRAN_TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("QYRAN_TG_CHAT_ID", "")

# Kazakhstan Law No. 230-VIII "On Artificial Intelligence" (signed 17.11.2025, effective 18.01.2026)
KZ_AI_LAW_PROFILE = {
    "system_name": "QYRAN Operational Voice-to-3D Intelligence",
    "version": "2.0.0-itfest2026",
    "law_reference": "Закон Республики Казахстан № 230-VIII «Об искусственном интеллекте» (от 17.11.2025, вступил в силу 18.01.2026)",
    "pdpl_reference": "Закон Республики Казахстан «О персональных данных и их защите» № 94-V",
    "risk_tier": "HIGH",
    "risk_tier_label_ru": "Высокий риск (ст. 17-19: критическая инфраструктура и реагирование на ЧС)",
    "risk_tier_label_kk": "Жоғары тәуекел (17-19-бап: сыни инфрақұрылым және ТЖ әрекет ету)",
    "hitl_policy": "MANDATORY_HUMAN_APPROVAL",
    "dual_marking_article": "Статья 21 (Визуальная + машиночитаемая JSON-LD маркировка)",
    "deployment_contour": "100% On-Premise / Air-Gapped (Zero External Cloud AI Calls)",
    "operator_default": "Дежурный ЦОУ-112 (Астана)",
    "confidence_recheck_threshold": 0.78,
}
