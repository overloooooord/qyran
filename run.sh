#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
echo "============================================================"
echo "  QYRAN 2.0 — Voice-to-3D Operational AI (IT FEST 2026)"
echo "  100% On-Premise | Whisper GPU/CPU | KZ Law No. 230-VIII"
echo "  Open: http://localhost:${PORT}"
echo "============================================================"
exec python3 -m uvicorn backend.app:app --host 0.0.0.0 --port "${PORT}"
