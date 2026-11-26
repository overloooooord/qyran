"""In-memory + SQLite-backed Real-Time Operational State Manager for QYRAN 2.0."""
from __future__ import annotations

import copy
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .audit import AuditDatabase
from .compliance import build_dual_marking, evaluate_compliance_checklist, redact_pii
from .config import KZ_AI_LAW_PROFILE
from .exporters import dispatch_telegram_alert
from .routing import compute_road_route, select_best_unit
from .scenarios import build_scenarios


class OperationalState:
    """Coordinates live incidents, units, tasks, HITL queue, building state & audit chain."""

    def __init__(self, db: AuditDatabase) -> None:
        self.db = db
        self.scenarios = build_scenarios()
        self.strict_hitl = True
        self.pii_redaction = True
        self.cloud_ai_calls = 0
        self.operator_name = KZ_AI_LAW_PROFILE["operator_default"]
        self.last_benchmark: dict[str, Any] | None = None
        self.activate_scenario("astana_expo")

    def activate_scenario(self, scenario_id: str) -> dict[str, Any]:
        if scenario_id not in self.scenarios:
            raise KeyError(f"Unknown scenario: {scenario_id}")
        self.scenario_id = scenario_id
        self.scenario = self.scenarios[scenario_id]
        self.session_id = f"{scenario_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.sim_time = self.scenario["start_time"]
        self.transmissions: list[dict[str, Any]] = []
        self.incidents: list[dict[str, Any]] = []
        self.tasks: list[dict[str, Any]] = []
        self.recommendations: list[dict[str, Any]] = []
        self.dispatches: list[dict[str, Any]] = []
        self.vision_analyses: list[dict[str, Any]] = []
        self.dynamic_routes: dict[str, dict[str, Any]] = {}
        self.units: dict[str, dict[str, Any]] = copy.deepcopy(self.scenario["units"])
        self.drone_track: list[list[float]] = []
        self.hot_squares: list[int] = []
        self.perimeter_zones: list[dict[str, Any]] = []
        self.building_state: dict[str, Any] = {
            **copy.deepcopy(self.scenario["building"]),
            "evacuated": False,
            "evacuated_count": 0,
            "smoke_active": False,
            "armed_count": 2 if scenario_id == "almaty_zenkova" else 0,
            "remaining_inside": self.scenario["building"]["initial_people"],
        }
        self._inc_seq = 0
        self._task_seq = 0
        self._rec_seq = 0

        self.db.append_audit(
            self.session_id,
            self.sim_time,
            "SYSTEM",
            "SESSION_START",
            f"Активирован сценарий: {self.scenario['title_ru']}",
            {"scenario_id": scenario_id, "strict_hitl": self.strict_hitl},
        )
        return self.snapshot()

    def _now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _bump_sim_time(self, explicit_time: str | None = None) -> str:
        if explicit_time:
            self.sim_time = explicit_time
            return self.sim_time
        try:
            h, m, s = [int(x) for x in self.sim_time.split(":")]
            total = h * 3600 + m * 60 + s + 14
            self.sim_time = f"{(total // 3600) % 24:02d}:{(total // 60) % 60:02d}:{total % 60:02d}"
        except Exception:
            self.sim_time = datetime.now().strftime("%H:%M:%S")
        return self.sim_time

    def ingest_processed_message(
        self,
        *,
        nlp: dict[str, Any],
        source: str,
        asr_latency_ms: int,
        asr_confidence: float,
        asr_rtf: float | None = None,
        asr_model_id: str | None = None,
        hallucination_recovered: bool = False,
        rescore_note: str | None = None,
        snr_db: float | None = None,
        duration_sec: float | None = None,
        waveform: list[float] | None = None,
        audio_url: str | None = None,
        sim_time: str | None = None,
        clip_id: str | None = None,
    ) -> dict[str, Any]:
        """Commit an ASR + NLP result into operational state, HITL queue, map, and SHA-256 audit chain."""
        st = self._bump_sim_time(sim_time)
        tx_id = f"TX-{len(self.transmissions) + 1:03d}"

        provenance = build_dual_marking(
            artifact_type="RadioTransmissionAnalysis",
            payload={
                "tx_id": tx_id,
                "raw_asr": nlp["raw_asr"],
                "repaired_text": nlp["repaired_text"],
                "kind": nlp["kind"],
                "location": nlp["location_label"],
                "priority": nlp["priority"],
            },
            ai_assisted=True,
            human_verified=False,
            model_id=asr_model_id,
            confidence=nlp["confidence"],
            nlp_engine=nlp["repair_engine"],
        )

        tx_record: dict[str, Any] = {
            "id": tx_id,
            "clip_id": clip_id,
            "session_id": self.session_id,
            "scenario_id": self.scenario_id,
            "ts_utc": self._now_utc(),
            "sim_time": st,
            "source": source,
            "audio_url": audio_url,
            "asr_latency_ms": asr_latency_ms,
            "asr_confidence": asr_confidence,
            "asr_rtf": asr_rtf,
            "hallucination_recovered": hallucination_recovered,
            "rescore_note": rescore_note,
            "snr_db": snr_db,
            "duration_sec": duration_sec,
            "waveform": waveform or [],
            **nlp,
            "provenance": provenance,
        }
        self.transmissions.append(tx_record)
        self.db.save_transmission(tx_record)

        self.db.append_audit(
            self.session_id,
            st,
            f"ASR/NLP ({nlp['from_callsign']})",
            "RADIO_INGEST",
            f"[{nlp['detected_lang'].upper()} · P{nlp['priority']}] {nlp['summary_ru']}",
            {
                "tx_id": tx_id,
                "source": source,
                "asr_latency_ms": asr_latency_ms,
                "repaired_count": nlp["repaired_count"],
                "confidence": nlp["confidence"],
                "sensor_status": nlp["sensor_status"],
            },
        )

        # Apply spatial, incident, task, and building updates
        created_incident: dict[str, Any] | None = None
        created_task: dict[str, Any] | None = None
        created_rec: dict[str, Any] | None = None
        tg_receipt: dict[str, Any] | None = None

        kind = nlp["kind"]
        if kind == "ack":
            # Auto-acknowledge most recent 'new' task
            for k in reversed(self.tasks):
                if k["status"] == "new":
                    k["status"] = "go"
                    k["history"].append({"time": st, "status": "ack", "note": f"Квитанция в эфире ({tx_id})"})
                    k["history"].append({"time": st, "status": "go", "note": "Подразделение приступило"})
                    if k["unit"] in self.units:
                        self.units[k["unit"]]["status"] = "выполняет задачу"
                    self.db.append_audit(
                        self.session_id,
                        st,
                        nlp["from_callsign"],
                        "TASK_ACK_VOICE",
                        f"Голосовое подтверждение задачи {k['id']} ({k['unit']})",
                        {"task_id": k["id"], "tx_id": tx_id},
                    )
                    break
        elif kind == "order":
            target_unit = nlp["to_callsign"]
            if target_unit not in self.units:
                for uname in self.units:
                    if uname.lower().split("-")[0] in nlp["repaired_text"].lower():
                        target_unit = uname
                        break
            created_task = self.create_task(
                unit=target_unit,
                text=nlp["translation_ru"],
                source=f"Голосовой приказ ({tx_id})",
                priority=nlp["priority"],
            )
        elif kind == "neutralized":
            # Mark active drone/fire incidents resolved & update evacuation if mentioned
            for inc in self.incidents:
                if inc["status"] == "active" and inc["kind"] in ("drone", "fire_smoke"):
                    inc["status"] = "resolved"
                    inc["resolved_time"] = st
            self.hot_squares = []
            if nlp.get("coords"):
                self.drone_track.append(nlp["coords"])
            if nlp.get("count") and nlp["count"] >= 5:
                self.building_state["evacuated"] = True
                self.building_state["evacuated_count"] = nlp["count"]
                self.building_state["remaining_inside"] = max(0, self.building_state["initial_people"] - nlp["count"])
                self.building_state["smoke_active"] = False
            for k in self.tasks:
                if k["status"] in ("go", "on") and any(w in k["text"].lower() for w in ("бпла", "дрон", "пожар", "эвакуа")):
                    k["status"] = "done"
                    k["history"].append({"time": st, "status": "done", "note": f"Закрыто по эфиру ({tx_id})"})
            self.db.append_audit(
                self.session_id,
                st,
                nlp["from_callsign"],
                "INCIDENT_RESOLVED",
                f"Угроза снята / локализована: {nlp['summary_ru']}",
                {"tx_id": tx_id},
            )
        elif kind == "evacuated":
            cnt = nlp.get("count") or self.building_state["initial_people"]
            self.building_state["evacuated"] = True
            self.building_state["evacuated_count"] = cnt
            self.building_state["remaining_inside"] = max(
                self.building_state.get("armed_count", 0),
                self.building_state["initial_people"] - cnt,
            )
            for k in self.tasks:
                if k["status"] in ("new", "go", "on"):
                    k["status"] = "done"
                    k["history"].append({"time": st, "status": "done", "note": f"Выведено {cnt} чел."})
                    break
        else:
            # Create or update geospatial incident
            if kind == "drone":
                existing_drone = next(
                    (i for i in reversed(self.incidents) if i["kind"] == "drone" and i["status"] == "active"),
                    None,
                )
                if existing_drone:
                    existing_drone["coords"] = nlp["coords"]
                    existing_drone["location_label"] = nlp["location_label"]
                    existing_drone["square"] = nlp["square"]
                    existing_drone["heading_deg"] = nlp["heading_deg"] or existing_drone.get("heading_deg")
                    existing_drone["direction_ru"] = nlp["direction_ru"] or existing_drone.get("direction_ru")
                    existing_drone["summary_ru"] = nlp["summary_ru"]
                    existing_drone["updated_time"] = st
                    created_incident = existing_drone
                else:
                    created_incident = self._add_incident(tx_record, nlp, st)
                self.drone_track.append(nlp["coords"])
            else:
                created_incident = self._add_incident(tx_record, nlp, st)

            if nlp.get("square") and nlp["square"] not in self.hot_squares:
                self.hot_squares.append(nlp["square"])

            if kind == "fire_smoke":
                self.building_state["smoke_active"] = True
                if nlp.get("floor"):
                    self.building_state["hot_floor"] = nlp["floor"]
            if kind in ("armed", "fire_smoke", "infrastructure"):
                radius = 250 if kind == "fire_smoke" else 300
                self.perimeter_zones.append({
                    "id": f"Z-{len(self.perimeter_zones) + 1}",
                    "center": nlp["coords"],
                    "radius_m": radius,
                    "label": f"Периметр {radius} м · {nlp['location_label']}",
                })

            if nlp["priority"] == 1:
                tg_receipt = dispatch_telegram_alert(nlp["summary_ru"], nlp["translation_ru"], priority=1)

        # Create Mandatory Human-in-the-Loop (HITL) Recommendation when applicable
        if nlp.get("recommended_action_ru"):
            self._rec_seq += 1
            rec_id = f"REC-{self._rec_seq:03d}"
            # Dynamically pick nearest matching unit & compute real OSRM street route + ETA!
            best_unit, _ = select_best_unit(
                kind, nlp["coords"], self.units, preferred_unit=nlp.get("recommended_unit")
            )
            route_preview: dict[str, Any] | None = None
            if best_unit and best_unit in self.units:
                u_obj = self.units[best_unit]
                route_preview = compute_road_route(
                    u_obj["pos"],
                    nlp["coords"],
                    cached_routes=self.scenario.get("routes"),
                    unit_route_key=u_obj.get("route"),
                )
            rec_obj: dict[str, Any] = {
                "id": rec_id,
                "session_id": self.session_id,
                "created_utc": self._now_utc(),
                "sim_time": st,
                "tx_id": tx_id,
                "title": nlp["recommended_action_ru"],
                "title_kk": nlp["recommended_action_kk"],
                "action_type": kind,
                "unit": best_unit or nlp.get("recommended_unit"),
                "priority": nlp["priority"],
                "confidence": nlp["confidence"],
                "needs_recheck": nlp["needs_recheck"],
                "sensor_status": nlp["sensor_status"],
                "sensor_label": nlp["sensor_label"],
                "xai_factors": nlp["xai_factors"],
                "route_eta_min": max(1, round(route_preview["dur"] / 60)) if route_preview else None,
                "route_dist_km": round(route_preview["dist"] / 1000.0, 2) if route_preview else None,
                "route_source": route_preview["source"] if route_preview else None,
                "status": "PENDING",
                "decided_by": None,
                "decided_utc": None,
                "decision_note": None,
                "payload": {
                    "unit": best_unit or nlp.get("recommended_unit"),
                    "location": nlp["location_label"],
                    "coords": nlp["coords"],
                    "route": route_preview,
                },
                "provenance": build_dual_marking(
                    artifact_type="HITLDecisionRecommendation",
                    payload={"rec_id": rec_id, "title": nlp["recommended_action_ru"], "priority": nlp["priority"]},
                    ai_assisted=True,
                    human_verified=False,
                    confidence=nlp["confidence"],
                ),
            }
            self.recommendations.append(rec_obj)
            self.db.save_recommendation(rec_obj)
            self.db.append_audit(
                self.session_id,
                st,
                "AI_ADVISOR",
                "HITL_PROPOSED",
                f"Предложение ИИ {rec_id} (ожидает утверждения человеком): {rec_obj['title']}",
                {"rec_id": rec_id, "priority": nlp["priority"], "strict_hitl": self.strict_hitl, "unit": rec_obj["unit"]},
            )
            created_rec = rec_obj

        return {
            "transmission": tx_record,
            "incident": created_incident,
            "task": created_task,
            "recommendation": created_rec,
            "telegram": tg_receipt,
            "state": self.snapshot(),
        }

    def _add_incident(self, tx: dict[str, Any], nlp: dict[str, Any], sim_time: str) -> dict[str, Any]:
        self._inc_seq += 1
        inc = {
            "id": self._inc_seq,
            "tx_id": tx["id"],
            "time": sim_time,
            "updated_time": sim_time,
            "kind": nlp["kind"],
            "kind_label_ru": nlp["kind_label_ru"],
            "kind_label_kk": nlp["kind_label_kk"],
            "color": nlp["color"],
            "priority": nlp["priority"],
            "status": "active",
            "location_ref": nlp["location_ref"],
            "location_label": nlp["location_label"],
            "coords": nlp["coords"],
            "square": nlp["square"],
            "floor": nlp["floor"],
            "count": nlp["count"],
            "altitude_m": nlp["altitude_m"],
            "direction": nlp["direction"],
            "direction_ru": nlp["direction_ru"],
            "heading_deg": nlp["heading_deg"],
            "target_coords": nlp["target_coords"],
            "target_label": nlp["target_label"],
            "source_callsign": nlp["from_callsign"],
            "summary_ru": nlp["summary_ru"],
            "summary_kk": nlp["summary_kk"],
            "sensor_status": nlp["sensor_status"],
            "sensor_label": nlp["sensor_label"],
            "confidence": nlp["confidence"],
            "needs_recheck": nlp["needs_recheck"],
            "xai_factors": nlp["xai_factors"],
        }
        self.incidents.append(inc)
        return inc

    def create_task(self, unit: str, text: str, source: str, priority: int = 2) -> dict[str, Any]:
        self._task_seq += 1
        tid = f"T-{self._task_seq:02d}"
        t = {
            "id": tid,
            "unit": unit,
            "text": text,
            "source": source,
            "priority": priority,
            "status": "new",
            "born_ts": time.time(),
            "created_time": self.sim_time,
            "history": [{"time": self.sim_time, "status": "new", "note": source}],
        }
        self.tasks.append(t)
        self.db.append_audit(
            self.session_id,
            self.sim_time,
            "TASK_ENGINE",
            "TASK_CREATED",
            f"Создана задача {tid} → {unit}: {text}",
            {"task_id": tid, "unit": unit, "source": source},
        )
        return t

    def decide_recommendation(
        self, rec_id: str, decision: str, operator: str | None = None, note: str | None = None
    ) -> dict[str, Any]:
        rec = next((r for r in self.recommendations if r["id"] == rec_id), None)
        if not rec:
            raise KeyError(f"Recommendation not found: {rec_id}")
        op = (operator or self.operator_name).strip() or self.operator_name
        dec = decision.upper()
        if dec not in ("APPROVED", "REJECTED"):
            raise ValueError("Decision must be APPROVED or REJECTED")

        rec["status"] = dec
        rec["decided_by"] = op
        rec["decided_utc"] = self._now_utc()
        rec["decision_note"] = note or ("Утверждено оператором" if dec == "APPROVED" else "Отклонено оператором")
        rec["provenance"] = build_dual_marking(
            artifact_type="HITLDecisionRecord",
            payload={"rec_id": rec_id, "decision": dec, "operator": op, "note": rec["decision_note"]},
            ai_assisted=True,
            human_verified=(dec == "APPROVED"),
            human_operator=op,
            confidence=rec.get("confidence"),
        )
        self.db.save_recommendation(rec)

        created_task = None
        dispatched_unit = None
        if dec == "APPROVED" and rec.get("unit"):
            unit_name = rec["unit"]
            created_task = self.create_task(
                unit=unit_name,
                text=rec["title"],
                source=f"HITL утверждено ({op})",
                priority=rec["priority"],
            )
            created_task["status"] = "go"
            created_task["history"].append({"time": self.sim_time, "status": "go", "note": f"Направлен ({op})"})
            if unit_name in self.units:
                self.units[unit_name]["status"] = "в пути по маршруту"
                dyn_route = (rec.get("payload") or {}).get("route")
                if dyn_route and dyn_route.get("coords"):
                    dyn_key = f"dyn_{rec_id}"
                    self.dynamic_routes[dyn_key] = dyn_route
                    self.units[unit_name]["active_route"] = dyn_key
                    dispatched_unit = {
                        "unit": unit_name,
                        "route_key": dyn_key,
                        "route": dyn_route,
                    }
                else:
                    route_key = self.units[unit_name].get("route")
                    if route_key and route_key in self.scenario["routes"]:
                        self.units[unit_name]["active_route"] = route_key
                        dispatched_unit = {
                            "unit": unit_name,
                            "route_key": route_key,
                            "route": self.scenario["routes"][route_key],
                        }

        self.db.append_audit(
            self.session_id,
            self.sim_time,
            op,
            f"HITL_{dec}",
            f"{'✔ УТВЕРЖДЕНО' if dec == 'APPROVED' else '✖ ОТКЛОНЕНО'} {rec_id}: {rec['title']}",
            {"rec_id": rec_id, "decision": dec, "operator": op, "note": rec["decision_note"]},
        )
        return {
            "recommendation": rec,
            "task": created_task,
            "dispatched_unit": dispatched_unit,
            "state": self.snapshot(),
        }

    def update_task_status(self, task_id: str, status: str, note: str | None = None) -> dict[str, Any]:
        t = next((k for k in self.tasks if k["id"] == task_id), None)
        if not t:
            raise KeyError(f"Task not found: {task_id}")
        t["status"] = status
        t["history"].append({"time": self.sim_time, "status": status, "note": note or status})
        self.db.append_audit(
            self.session_id,
            self.sim_time,
            self.operator_name,
            "TASK_STATUS",
            f"Задача {task_id} ({t['unit']}) → {status}",
            {"task_id": task_id, "status": status, "note": note},
        )
        return t

    def ping_silent_task(self, task_id: str) -> dict[str, Any]:
        t = next((k for k in self.tasks if k["id"] == task_id), None)
        if not t:
            raise KeyError(f"Task not found: {task_id}")
        t["born_ts"] = time.time()
        t["history"].append({"time": self.sim_time, "status": t["status"], "note": "Повторный вызов по рации"})
        self.db.append_audit(
            self.session_id,
            self.sim_time,
            self.operator_name,
            "SILENCE_PING",
            f"Повторный вызов подразделения {t['unit']} по задаче {task_id}",
            {"task_id": task_id, "unit": t["unit"]},
        )
        return t

    def resolve_incident(self, inc_id: int) -> dict[str, Any]:
        inc = next((i for i in self.incidents if i["id"] == inc_id), None)
        if not inc:
            raise KeyError(f"Incident not found: {inc_id}")
        inc["status"] = "resolved"
        inc["resolved_time"] = self.sim_time
        self.db.append_audit(
            self.session_id,
            self.sim_time,
            self.operator_name,
            "INCIDENT_MANUAL_RESOLVE",
            f"Инцидент #{inc_id} ({inc['kind_label_ru']}) закрыт оператором",
            {"incident_id": inc_id},
        )
        return inc

    def dispatch_service(self, service: str, channel: str, note: str | None = None) -> dict[str, Any]:
        latest = next((i for i in reversed(self.incidents) if i["status"] == "active"), None)
        reg_no = f"№{1040 + len(self.dispatches) + 1}"
        loc = latest["location_label"] if latest else self.scenario["title_ru"]
        coords = latest["coords"] if latest else self.scenario["center"]
        what = latest["summary_ru"] if latest else (note or "Проверка оперативной обстановки")
        rec = {
            "reg_no": reg_no,
            "time": self.sim_time,
            "service": service,
            "channel": channel,
            "location": loc,
            "coords": coords,
            "summary": what,
            "status": "ПРИНЯТО ДЕЖУРНЫМ",
        }
        self.dispatches.insert(0, rec)
        tg = None
        if channel == "tg":
            tg = dispatch_telegram_alert(f"Вызов {service} ({reg_no})", f"{what} · {loc}", priority=1)
        self.db.append_audit(
            self.session_id,
            self.sim_time,
            self.operator_name,
            "SERVICE_DISPATCH",
            f"Вызов {service} по каналу {channel.upper()} ({reg_no}): {loc}",
            {"reg_no": reg_no, "service": service, "channel": channel, "coords": coords},
        )
        return {"dispatch": rec, "telegram": tg, "state": self.snapshot()}

    def record_vision_analysis(self, result: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "id": f"CV-{len(self.vision_analyses) + 1:02d}",
            "time": self.sim_time,
            **result,
        }
        self.vision_analyses.insert(0, entry)
        # If anomaly confirmed, cross-verify latest unverified incident!
        if result["verdict"] == "ANOMALY_CONFIRMED":
            for inc in reversed(self.incidents):
                if inc["status"] == "active" and inc["sensor_status"] == "unverified":
                    det_lbl = result["detections"][0]["label_ru"]
                    inc["sensor_status"] = "ok"
                    inc["sensor_label"] = f"CV-кадр ({det_lbl}, {int(result['detections'][0]['confidence']*100)}%)"
                    inc["needs_recheck"] = False
                    break
        self.db.append_audit(
            self.session_id,
            self.sim_time,
            "EDGE_VISION",
            "CV_FRAME_ANALYZED",
            f"Анализ кадра {result['filename']}: {result['verdict']} (огонь {result['fire_area_pct']}%, дым {result['smoke_area_pct']}%)",
            {"filename": result["filename"], "verdict": result["verdict"], "detections": len(result["detections"])},
        )
        return {"analysis": entry, "state": self.snapshot()}

    def send_building_plan(self, unit: str, floor: int) -> dict[str, Any]:
        self.db.append_audit(
            self.session_id,
            self.sim_time,
            self.operator_name,
            "SEND_3D_PLAN",
            f"3D-план этажа {floor} ({self.building_state['name']}) передан группе {unit}",
            {"unit": unit, "floor": floor, "remaining_inside": self.building_state["remaining_inside"]},
        )
        return {"sent": True, "unit": unit, "floor": floor, "state": self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        chain_check = self.db.verify_chain()
        pending = sum(1 for r in self.recommendations if r["status"] == "PENDING")
        approved = sum(1 for r in self.recommendations if r["status"] == "APPROVED")
        rejected = sum(1 for r in self.recommendations if r["status"] == "REJECTED")
        compliance = evaluate_compliance_checklist(
            chain_valid=chain_check["valid"],
            chain_blocks=chain_check["total_blocks"],
            pending_hitl=pending,
            approved_hitl=approved,
            rejected_hitl=rejected,
            strict_hitl=self.strict_hitl,
            pii_redaction_active=self.pii_redaction,
            cloud_calls_count=self.cloud_ai_calls,
        )
        now_s = time.time()
        silent_count = sum(
            1 for k in self.tasks if k["status"] == "new" and (now_s - k["born_ts"]) >= 12
        )

        # Live ROI & Analytics telemetry
        msg_cnt = len(self.transmissions)
        avg_ms = int(round(sum(t["asr_latency_ms"] for t in self.transmissions) / max(1, msg_cnt))) if msg_cnt else 0
        manual_sec_per_msg = 135.0  # listen -> write -> find grid square -> plot -> relay
        qyran_sec_per_msg = max(0.35, avg_ms / 1000.0) if msg_cnt else 0.75
        time_saved_sec = int(round(msg_cnt * max(0.0, manual_sec_per_msg - qyran_sec_per_msg)))
        kind_counts: dict[str, int] = {}
        for t in self.transmissions:
            kind_counts[t["kind"]] = kind_counts.get(t["kind"], 0) + 1
        merged_routes = {**self.scenario.get("routes", {}), **self.dynamic_routes}

        return {
            "session_id": self.session_id,
            "scenario": {
                "id": self.scenario["id"],
                "badge": self.scenario["badge"],
                "title_ru": self.scenario["title_ru"],
                "title_kk": self.scenario["title_kk"],
                "subtitle_ru": self.scenario["subtitle_ru"],
                "subtitle_kk": self.scenario["subtitle_kk"],
                "center": self.scenario["center"],
                "zoom": self.scenario["zoom"],
                "pitch": self.scenario["pitch"],
                "bearing": self.scenario["bearing"],
                "grid": self.scenario["grid"],
                "places": self.scenario["places"],
                "routes": merged_routes,
                "clips": self.scenario["clips"],
                "sample_commands": self.scenario["sample_commands"],
            },
            "sim_time": self.sim_time,
            "operator_name": self.operator_name,
            "kpis": {
                "messages": msg_cnt,
                "active_threats": sum(1 for i in self.incidents if i["status"] == "active" and i["priority"] <= 2),
                "total_incidents": len(self.incidents),
                "tasks_total": len(self.tasks),
                "tasks_done": sum(1 for k in self.tasks if k["status"] == "done"),
                "silent_units": silent_count,
                "pending_hitl": pending,
                "kk_share_pct": round(
                    sum(1 for t in self.transmissions if t["detected_lang"] == "kk") * 100 / max(1, msg_cnt)
                ) if msg_cnt else 0,
                "avg_asr_ms": avg_ms,
                "repaired_words_total": sum(t.get("repaired_count", 0) for t in self.transmissions),
                "hallucinations_prevented": sum(1 for t in self.transmissions if t.get("hallucination_recovered")),
            },
            "analytics": {
                "manual_cycle_sec": manual_sec_per_msg,
                "qyran_avg_sec": round(qyran_sec_per_msg, 2),
                "speedup_factor": int(round(manual_sec_per_msg / max(0.3, qyran_sec_per_msg))),
                "time_saved_sec": time_saved_sec,
                "kind_counts": kind_counts,
                "latency_series": [{"id": t["id"], "ms": t["asr_latency_ms"], "lang": t["detected_lang"]} for t in self.transmissions[-14:]],
            },
            "transmissions": self.transmissions[-40:],
            "incidents": self.incidents,
            "tasks": self.tasks,
            "recommendations": self.recommendations,
            "units": self.units,
            "dispatches": self.dispatches[:20],
            "vision_analyses": self.vision_analyses[:8],
            "drone_track": self.drone_track,
            "hot_squares": self.hot_squares,
            "perimeter_zones": self.perimeter_zones,
            "building": self.building_state,
            "audit_log": self.db.get_recent_audit(self.session_id, limit=80),
            "audit_chain": chain_check,
            "compliance": compliance,
            "last_benchmark": self.last_benchmark,
        }
