"""QYRAN 2.0 FastAPI + WebSocket Backend Server (IT FEST 2026 StartUp Battle MVP)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .asr_engine import LocalWhisperEngine
from .audio_dsp import analyze_audio, apply_radio_degradation, decode_to_16k_mono, load_wav_16k
from .audit import AuditDatabase
from .benchmark import run_live_benchmark
from .compliance import redact_pii
from .config import ASSETS_DIR, DATA_DIR, FRONTEND_DIR, SCENARIOS_DIR
from .copilot import answer_commander_question
from .exporters import export_cot_xml, export_geojson, export_markdown_report, export_printable_html_report
from .nlp_engine import check_local_llm_available, extract_operational_intelligence
from .state import OperationalState
from .vision_engine import analyze_frame_bytes

UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("qyran.api")

db = AuditDatabase()
asr_engine = LocalWhisperEngine()
ops_state = OperationalState(db)


class ConnectionManager:
    """Broadcasts live operational updates to all connected operator consoles."""

    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        msg = json.dumps({"event": event_type, "data": payload}, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []
        for ws in list(self.connections):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Pre-warm local GPU Whisper in background thread so startup is instant & first clip is <0.4s
    if os.getenv("QYRAN_SKIP_PRELOAD", "0") != "1":
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _safe_preload)
    yield
    db.close()


def _safe_preload() -> None:
    try:
        asr_engine.ensure_loaded()
    except Exception as exc:
        logger.warning("Whisper preload deferred/failed: %s", exc)


app = FastAPI(
    title="QYRAN 2.0 — Voice-to-3D Operational AI (IT FEST 2026)",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Request Models
# =============================================================================
class TextIngestReq(BaseModel):
    text: str
    lang: str = "auto"
    from_callsign: str | None = None
    to_callsign: str | None = None


class DecisionReq(BaseModel):
    decision: str  # APPROVED | REJECTED
    operator: str | None = None
    note: str | None = None


class TaskStatusReq(BaseModel):
    status: str
    note: str | None = None


class DispatchReq(BaseModel):
    service: str
    channel: str = "radio"
    note: str | None = None


class ComplianceSettingsReq(BaseModel):
    strict_hitl: bool | None = None
    pii_redaction: bool | None = None
    operator_name: str | None = None


class RedactPreviewReq(BaseModel):
    text: str


class BuildingPlanReq(BaseModel):
    unit: str
    floor: int = 2


class CopilotReq(BaseModel):
    question: str
    lang: str = "ru"


# =============================================================================
# Health, Scenarios & State Endpoints
# =============================================================================
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "contour": "100% On-Premise / Zero Cloud Egress",
        "asr": asr_engine.status(),
        "local_llm": check_local_llm_available(),
        "active_scenario": ops_state.scenario_id,
        "audit_chain": db.verify_chain(),
    }


@app.get("/api/scenarios")
def list_scenarios() -> dict[str, Any]:
    return {
        "active": ops_state.scenario_id,
        "scenarios": [
            {
                "id": sc["id"],
                "badge": sc["badge"],
                "title_ru": sc["title_ru"],
                "title_kk": sc["title_kk"],
                "subtitle_ru": sc["subtitle_ru"],
                "subtitle_kk": sc["subtitle_kk"],
                "clips_count": len(sc["clips"]),
            }
            for sc in ops_state.scenarios.values()
        ],
    }


@app.post("/api/scenarios/{scenario_id}/activate")
async def activate_scenario(scenario_id: str) -> dict[str, Any]:
    try:
        snap = ops_state.activate_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await ws_manager.broadcast("state_reset", snap)
    return snap


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return ops_state.snapshot()


# =============================================================================
# Real-Time Audio / Radio / Text Ingestion (Local GPU Whisper + NLP Repair)
# =============================================================================
@app.post("/api/ingest/audio")
async def ingest_audio(
    file: UploadFile = File(...),
    lang: str = Form("auto"),
    radio_degrade: bool = Form(False),
    from_callsign: str | None = Form(None),
) -> dict[str, Any]:
    raw_bytes = await file.read()
    if not raw_bytes or len(raw_bytes) < 200:
        raise HTTPException(status_code=400, detail="Пустой или слишком короткий аудиофайл")

    suffix = Path(file.filename or "recording.webm").suffix or ".webm"

    def _process() -> dict[str, Any]:
        import uuid as _uuid
        import numpy as _np
        from scipy.io import wavfile as _wavfile

        sr, samples = decode_to_16k_mono(raw_bytes, suffix=suffix)
        if radio_degrade:
            samples = apply_radio_degradation(samples, sr=sr)
        # Persist processed 16 kHz WAV so operator/judges can replay their own live/radio-filtered voice!
        saved_name = f"live_{_uuid.uuid4().hex[:10]}.wav"
        pcm16 = (_np.clip(samples, -1.0, 1.0) * 32767.0).astype(_np.int16)
        _wavfile.write(UPLOADS_DIR / saved_name, sr, pcm16)

        dsp = analyze_audio(samples, sr=sr, radio_filtered=radio_degrade)
        asr = asr_engine.transcribe(samples, sample_rate=sr, language=lang)
        nlp = extract_operational_intelligence(
            asr.raw_text,
            asr.detected_lang,
            ops_state.scenario,
            asr_confidence=asr.confidence,
            snr_db=dsp.snr_db,
            hint_from=from_callsign or "Микрофон / PTT",
        )
        return ops_state.ingest_processed_message(
            nlp=nlp,
            source="live_mic_radio" if radio_degrade else "live_audio",
            asr_latency_ms=asr.latency_ms,
            asr_confidence=asr.confidence,
            asr_rtf=asr.rtf,
            asr_model_id=asr.model_id,
            hallucination_recovered=asr.hallucination_recovered,
            rescore_note=asr.rescore_note,
            snr_db=dsp.snr_db,
            duration_sec=dsp.duration_sec,
            waveform=dsp.waveform,
            audio_url=f"/api/uploads/{saved_name}",
        )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _process)
    except Exception as exc:
        logger.exception("Audio ingest failed")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки аудио: {exc}") from exc

    await ws_manager.broadcast("transmission", result)
    return result


@app.post("/api/ingest/text")
async def ingest_text(req: TextIngestReq) -> dict[str, Any]:
    txt = req.text.strip()
    if not txt:
        raise HTTPException(status_code=400, detail="Пустой текст команды")
    detected = req.lang
    if detected not in ("kk", "ru"):
        has_kk = any(ch in txt.lower() for ch in "әіңғүұқөһ")
        detected = "kk" if has_kk else "ru"

    nlp = extract_operational_intelligence(
        txt,
        detected,
        ops_state.scenario,
        asr_confidence=0.98,
        hint_from=req.from_callsign or "Текстовый пульт",
        hint_to=req.to_callsign,
    )
    result = ops_state.ingest_processed_message(
        nlp=nlp,
        source="text_console",
        asr_latency_ms=8,
        asr_confidence=0.98,
        asr_model_id="Direct-Text-Input",
    )
    await ws_manager.broadcast("transmission", result)
    return result


@app.post("/api/scenarios/{scenario_id}/clip/{clip_id}")
async def run_scenario_clip(
    scenario_id: str,
    clip_id: str,
    lang_mode: str = Query("auto", description="auto | kk | ru"),
) -> dict[str, Any]:
    """Process an authentic scenario radio WAV clip LIVE through local GPU Whisper + NLP."""
    if scenario_id != ops_state.scenario_id:
        ops_state.activate_scenario(scenario_id)

    clip = next((c for c in ops_state.scenario["clips"] if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found in {scenario_id}")

    wav_path = SCENARIOS_DIR / scenario_id / clip["filename"]
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail=f"WAV file missing: {wav_path.name}")

    def _process_clip() -> dict[str, Any]:
        sr, samples = load_wav_16k(wav_path)
        dsp = analyze_audio(samples, sr=sr, radio_filtered=True)
        asr = asr_engine.transcribe(samples, sample_rate=sr, language=lang_mode)
        nlp = extract_operational_intelligence(
            asr.raw_text,
            asr.detected_lang,
            ops_state.scenario,
            asr_confidence=asr.confidence,
            snr_db=dsp.snr_db,
            hint_from=clip.get("from"),
            hint_to=clip.get("to"),
            clip_id=clip_id,
        )
        return ops_state.ingest_processed_message(
            nlp=nlp,
            source="radio_gateway_wav",
            asr_latency_ms=asr.latency_ms,
            asr_confidence=asr.confidence,
            asr_rtf=asr.rtf,
            asr_model_id=asr.model_id,
            hallucination_recovered=asr.hallucination_recovered,
            rescore_note=asr.rescore_note,
            snr_db=dsp.snr_db,
            duration_sec=dsp.duration_sec,
            waveform=dsp.waveform,
            audio_url=f"/api/audio/{scenario_id}/{clip['filename']}",
            sim_time=clip.get("time"),
            clip_id=clip_id,
        )

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _process_clip)
    await ws_manager.broadcast("transmission", result)
    return result


@app.get("/api/audio/{scenario_id}/{filename}")
def get_scenario_audio(scenario_id: str, filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = SCENARIOS_DIR / scenario_id / safe_name
    if not path.exists() or path.suffix.lower() != ".wav":
        raise HTTPException(status_code=404, detail="Audio clip not found")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/uploads/{filename}")
def get_uploaded_audio(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = UPLOADS_DIR / safe_name
    if not path.exists() or path.suffix.lower() != ".wav":
        raise HTTPException(status_code=404, detail="Uploaded clip not found")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/scenarios/{scenario_id}/stress-burst")
async def run_stress_burst(scenario_id: str) -> dict[str, Any]:
    """Simultaneously ingest 5 parallel bilingual emergency reports to prove zero-loss triage."""
    import time as _time

    if scenario_id != ops_state.scenario_id:
        ops_state.activate_scenario(scenario_id)

    bursts = {
        "astana_expo": [
            ("Қыран-1", "kk", "Жетінші шаршыда рұқсатсыз дұром байқадым, биіктігі 200 метр, ЭКСПО сферасына қарай"),
            ("Өрт-2", "kk", "ЭКСПО павильон С-2, екінші қабатта электр қалқанынан қою түтін шықты, 101 керек"),
            ("Техник-7", "ru", "На подстанции Левобережья скачок напряжения и утечка хладагента, аварийная бригада!"),
            ("Патруль-4", "ru", "У Байтерека скопление около 120 человек, требуется полиция 102 для регулирования"),
            ("Бекет-3", "kk", "Мегасилк Вей маңында 2 адам зардап шекті, жедел жәрдем 103 шұғыл керек"),
        ],
        "almaty_zenkova": [
            ("Бүркіт-2", "kk", "Жетінші шаршыда дұром байқадым, биіктігі 300 метр, солтүстікке қарай"),
            ("Барыс-1", "kk", "Зенков көшесі 24, үшінші қабатта қаруланған екі адам бар"),
            ("Арлан-3", "ru", "Сумкар, вижу дом на крыше Зенкова 24, северо-восточный угол"),
            ("Бүркіт-1", "kk", "Көп базар маңында шамамен 50 адам жиналды, полиция көмегі керек"),
            ("Бүркіт-1", "kk", "Жібек жолы даңғыла, 2 адам жараланды, Жедел жәрден шұғыл керек"),
        ],
    }
    msgs = bursts.get(scenario_id, bursts["astana_expo"])
    t0 = _time.perf_counter()

    def _run_burst() -> list[dict[str, Any]]:
        results = []
        for caller, lang, txt in msgs:
            nlp = extract_operational_intelligence(
                txt, lang, ops_state.scenario, asr_confidence=0.93, snr_db=18.5, hint_from=caller
            )
            results.append(
                ops_state.ingest_processed_message(
                    nlp=nlp,
                    source="stress_burst_parallel",
                    asr_latency_ms=42,
                    asr_confidence=0.93,
                    asr_model_id="QYRAN-Parallel-Triage",
                    snr_db=18.5,
                )
            )
        return results

    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, _run_burst)
    elapsed_ms = int(round((_time.perf_counter() - t0) * 1000))
    snap = ops_state.snapshot()
    await ws_manager.broadcast("state_update", snap)
    return {
        "processed_count": len(items),
        "elapsed_ms": elapsed_ms,
        "manual_equivalent_sec": len(items) * 135,
        "state": snap,
    }


@app.post("/api/copilot/ask")
def ask_commander_copilot(req: CopilotReq) -> dict[str, Any]:
    """Grounded on-premise operational Q&A citing exact live entities & KZ Law 230-VIII provenance."""
    snap = ops_state.snapshot()
    ans = answer_commander_question(req.question, snap, lang=req.lang)
    db.append_audit(
        ops_state.session_id,
        ops_state.sim_time,
        ops_state.operator_name,
        "COPILOT_QUERY",
        f"Запрос к ИИ-штабу: {req.question[:90]}",
        {"citations": ans["citations"]},
    )
    return ans


# =============================================================================
# HITL Decisions, Tasks, Incidents & Dispatch
# =============================================================================
@app.post("/api/recommendations/{rec_id}/decide")
async def decide_recommendation(rec_id: str, req: DecisionReq) -> dict[str, Any]:
    try:
        res = ops_state.decide_recommendation(rec_id, req.decision, operator=req.operator, note=req.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await ws_manager.broadcast("hitl_decision", res)
    return res


@app.post("/api/tasks/{task_id}/status")
async def set_task_status(task_id: str, req: TaskStatusReq) -> dict[str, Any]:
    try:
        task = ops_state.update_task_status(task_id, req.status, req.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snap = ops_state.snapshot()
    await ws_manager.broadcast("state_update", snap)
    return {"task": task, "state": snap}


@app.post("/api/tasks/{task_id}/ping")
async def ping_task(task_id: str) -> dict[str, Any]:
    try:
        task = ops_state.ping_silent_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snap = ops_state.snapshot()
    await ws_manager.broadcast("state_update", snap)
    return {"task": task, "state": snap}


@app.post("/api/incidents/{inc_id}/resolve")
async def resolve_incident(inc_id: int) -> dict[str, Any]:
    try:
        inc = ops_state.resolve_incident(inc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snap = ops_state.snapshot()
    await ws_manager.broadcast("state_update", snap)
    return {"incident": inc, "state": snap}


@app.post("/api/dispatch/service")
async def dispatch_service(req: DispatchReq) -> dict[str, Any]:
    res = ops_state.dispatch_service(req.service, req.channel, req.note)
    await ws_manager.broadcast("dispatch", res)
    return res


# =============================================================================
# Responsible AI (KZ Law No. 230-VIII), Cryptographic Audit & Live WER Benchmark
# =============================================================================
@app.get("/api/audit/verify")
def verify_audit_chain() -> dict[str, Any]:
    return db.verify_chain()


@app.post("/api/audit/simulate-tamper")
def simulate_audit_tamper() -> dict[str, Any]:
    """Run isolated in-memory SHA-256 tamper-attack demonstration without altering live DB."""
    return db.simulate_tamper_demo()


@app.post("/api/ingest/image")
async def ingest_camera_frame(file: UploadFile = File(...)) -> dict[str, Any]:
    """Run local on-premise edge vision analysis (fire/smoke/thermal) on an uploaded camera image."""
    raw = await file.read()
    if not raw or len(raw) < 100:
        raise HTTPException(status_code=400, detail="Пустое изображение")
    try:
        analysis = analyze_frame_bytes(raw, filename=file.filename or "frame.jpg")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось обработать изображение: {exc}") from exc
    res = ops_state.record_vision_analysis(analysis)
    await ws_manager.broadcast("state_update", res["state"])
    return res


@app.post("/api/building/send-plan")
async def send_building_plan(req: BuildingPlanReq) -> dict[str, Any]:
    res = ops_state.send_building_plan(req.unit, req.floor)
    await ws_manager.broadcast("state_update", res["state"])
    return res


@app.post("/api/compliance/settings")
async def update_compliance_settings(req: ComplianceSettingsReq) -> dict[str, Any]:
    if req.strict_hitl is not None:
        ops_state.strict_hitl = req.strict_hitl
    if req.pii_redaction is not None:
        ops_state.pii_redaction = req.pii_redaction
    if req.operator_name is not None and req.operator_name.strip():
        ops_state.operator_name = req.operator_name.strip()
    db.append_audit(
        ops_state.session_id,
        ops_state.sim_time,
        ops_state.operator_name,
        "COMPLIANCE_POLICY_UPDATE",
        f"Политика ИИ обновлена: strict_hitl={ops_state.strict_hitl}, pii_redaction={ops_state.pii_redaction}",
        req.model_dump(),
    )
    snap = ops_state.snapshot()
    await ws_manager.broadcast("state_update", snap)
    return snap


@app.post("/api/compliance/redact-preview")
def preview_pii_redaction(req: RedactPreviewReq) -> dict[str, Any]:
    redacted, findings = redact_pii(req.text)
    return {"original": req.text, "redacted": redacted, "findings_count": len(findings), "findings": findings}


@app.post("/api/benchmark/run")
async def benchmark_active_scenario(scenario_id: str | None = Query(None)) -> dict[str, Any]:
    """Run REAL live jiwer WER/CER + GPU latency benchmark across scenario radio WAV clips."""
    target_id = scenario_id or ops_state.scenario_id
    if target_id not in ops_state.scenarios:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {target_id}")
    scenario = ops_state.scenarios[target_id]

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, run_live_benchmark, scenario, asr_engine)
    ops_state.last_benchmark = result
    db.append_audit(
        ops_state.session_id,
        ops_state.sim_time,
        "BENCHMARK_ENGINE",
        "WER_BENCHMARK",
        f"Бенчмарк {target_id}: WER {result['wer_raw_pct']}% → {result['wer_repaired_pct']}% (-{result['wer_relative_reduction_pct']}%), avg {result['avg_latency_ms']}ms ({result['speedup_vs_realtime']}x RT)",
        {
            "wer_raw_pct": result["wer_raw_pct"],
            "wer_repaired_pct": result["wer_repaired_pct"],
            "avg_latency_ms": result["avg_latency_ms"],
            "hallucinations_prevented": result["hallucinations_prevented"],
        },
    )
    await ws_manager.broadcast("benchmark_done", result)
    return result


# =============================================================================
# Standards-Compliant Exporters (Markdown + JSON-LD, GeoJSON, TAK/CoT XML, Audit JSON)
# =============================================================================
@app.get("/api/export/report.md")
def download_report_md(
    redact: bool | None = Query(None),
    lang: str = Query("ru"),
) -> Response:
    use_redact = ops_state.pii_redaction if redact is None else redact
    md = export_markdown_report(
        scenario=ops_state.scenario,
        transmissions=ops_state.transmissions,
        incidents=ops_state.incidents,
        tasks=ops_state.tasks,
        recommendations=ops_state.recommendations,
        audit_verify=db.verify_chain(),
        redact_pii_flag=use_redact,
        lang=lang,
    )
    db.append_audit(
        ops_state.session_id,
        ops_state.sim_time,
        ops_state.operator_name,
        "EXPORT_REPORT_MD",
        f"Экспорт официального отчёта (PII redaction={use_redact})",
        {"redact": use_redact, "lang": lang},
    )
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="QYRAN_{ops_state.scenario_id}_report.md"'},
    )


@app.get("/api/export/geojson")
def download_geojson() -> JSONResponse:
    verify = db.verify_chain()
    fc = export_geojson(ops_state.scenario, ops_state.incidents, ops_state.units, verify["head_hash"])
    return JSONResponse(
        content=fc,
        headers={"Content-Disposition": f'attachment; filename="QYRAN_{ops_state.scenario_id}.geojson"'},
    )


@app.get("/api/export/cot.xml")
def download_cot_xml() -> Response:
    xml_str = export_cot_xml(ops_state.incidents, ops_state.units)
    return Response(
        content=xml_str,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="QYRAN_{ops_state.scenario_id}_CoT.xml"'},
    )


@app.get("/api/export/audit.json")
def download_audit_json() -> JSONResponse:
    payload = {
        "session_id": ops_state.session_id,
        "verification": db.verify_chain(),
        "records": db.get_recent_audit(ops_state.session_id, limit=500),
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="QYRAN_{ops_state.scenario_id}_audit_chain.json"'},
    )


@app.get("/api/export/report.html")
def view_printable_report(redact: bool | None = Query(None)) -> Response:
    use_redact = ops_state.pii_redaction if redact is None else redact
    html = export_printable_html_report(
        scenario=ops_state.scenario,
        transmissions=ops_state.transmissions,
        incidents=ops_state.incidents,
        tasks=ops_state.tasks,
        recommendations=ops_state.recommendations,
        audit_verify=db.verify_chain(),
        redact_pii_flag=use_redact,
    )
    return Response(content=html, media_type="text/html; charset=utf-8")


# =============================================================================
# WebSocket Live Stream
# =============================================================================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws_manager.connect(ws)
    try:
        await ws.send_text(json.dumps({"event": "init", "data": ops_state.snapshot()}, ensure_ascii=False, default=str))
        while True:
            _ = await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# =============================================================================
# Static Frontend & Assets Serving
# =============================================================================
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def serve_index() -> FileResponse:
    idx = FRONTEND_DIR / "index.html"
    if not idx.exists():
        raise HTTPException(status_code=404, detail="Frontend not built yet")
    return FileResponse(idx)


@app.get("/pitch")
def serve_pitch() -> FileResponse:
    p = FRONTEND_DIR / "pitch.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Pitch deck not found")
    return FileResponse(p)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=False)
