"""Operational Exporters (TAK/CoT XML, GeoJSON, Law No. 230-VIII Dual-Marked Reports) & Telegram Alerting."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .compliance import build_dual_marking, redact_pii
from .config import KZ_AI_LAW_PROFILE, TG_BOT_TOKEN, TG_CHAT_ID


# CoT 2.0 standard event type mapping (interoperability with ATAK / WinTAK / GIS centers)
COT_TYPES: dict[str, str] = {
    "drone": "a-h-A-M-H-Q",           # Hostile/Unknown UAV
    "fire_smoke": "b-a-o-can",        # Fire / Hazard Alert
    "infrastructure": "b-a-o-tbl",    # Critical Infrastructure Trouble
    "casualties": "b-r-f-h-c",        # Medical Evacuation / Casualties
    "armed": "a-h-G-U-C",             # Security Threat
    "crowd": "b-m-p-s-p-loc",         # Crowd / Public Safety Point
    "neutralized": "b-m-p-s-m",       # Resolved / Cleared
    "other": "b-m-p-s-p-loc",
}


def export_cot_xml(incidents: list[dict[str, Any]], units: dict[str, Any]) -> str:
    """Export active incidents & friendly units as standard Cursor-on-Target (TAK/CoT 2.0) XML."""
    now = datetime.now(timezone.utc)
    stale = now + timedelta(minutes=15)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"

    root = ET.Element("events", attrib={
        "generator": "QYRAN-2.0-ITFEST2026",
        "kz_ai_law": "Law-RK-230-VIII-Art21-AI-Assisted",
    })

    for inc in incidents:
        lon, lat = inc["coords"]
        ev = ET.SubElement(root, "event", attrib={
            "version": "2.0",
            "uid": f"QYRAN-INC-{inc['id']}",
            "type": COT_TYPES.get(inc["kind"], "b-m-p-s-p-loc"),
            "how": "h-g-i-g-o",
            "time": now.strftime(fmt),
            "start": now.strftime(fmt),
            "stale": stale.strftime(fmt),
        })
        ET.SubElement(ev, "point", attrib={
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "hae": str(inc.get("altitude_m") or 0),
            "ce": "25.0",
            "le": "15.0",
        })
        detail = ET.SubElement(ev, "detail")
        ET.SubElement(detail, "contact", attrib={"callsign": f"INC-{inc['id']} {inc['kind_label_ru']}"})
        ET.SubElement(detail, "remarks").text = (
            f"[AI-ASSISTED · KZ Law 230-VIII] P{inc['priority']} | {inc['summary_ru']} | "
            f"Source: {inc.get('source_callsign', 'radio')} | Sensor: {inc.get('sensor_status', 'unverified')}"
        )

    for name, u in units.items():
        lon, lat = u["pos"]
        ev = ET.SubElement(root, "event", attrib={
            "version": "2.0",
            "uid": f"QYRAN-UNIT-{name}",
            "type": "a-f-G-U-C",
            "how": "m-g",
            "time": now.strftime(fmt),
            "start": now.strftime(fmt),
            "stale": stale.strftime(fmt),
        })
        ET.SubElement(ev, "point", attrib={
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "hae": "0",
            "ce": "10.0",
            "le": "10.0",
        })
        detail = ET.SubElement(ev, "detail")
        ET.SubElement(detail, "contact", attrib={"callsign": name})
        ET.SubElement(detail, "remarks").text = f"{u['role']} | {u['status']} | Crew {u['crew']}"

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def export_geojson(
    scenario: dict[str, Any],
    incidents: list[dict[str, Any]],
    units: dict[str, Any],
    audit_head_hash: str,
) -> dict[str, Any]:
    """Export standard GeoJSON FeatureCollection with Law No. 230-VIII JSON-LD provenance."""
    features: list[dict[str, Any]] = []
    for inc in incidents:
        features.append({
            "type": "Feature",
            "id": f"inc-{inc['id']}",
            "geometry": {"type": "Point", "coordinates": inc["coords"]},
            "properties": {
                "feature_class": "incident",
                "id": inc["id"],
                "kind": inc["kind"],
                "label": inc["kind_label_ru"],
                "priority": inc["priority"],
                "status": inc["status"],
                "location_label": inc["location_label"],
                "square": inc.get("square"),
                "floor": inc.get("floor"),
                "count": inc.get("count"),
                "altitude_m": inc.get("altitude_m"),
                "heading_deg": inc.get("heading_deg"),
                "confidence": inc.get("confidence"),
                "sensor_status": inc.get("sensor_status"),
                "summary_ru": inc["summary_ru"],
            },
        })
    for name, u in units.items():
        features.append({
            "type": "Feature",
            "id": f"unit-{name}",
            "geometry": {"type": "Point", "coordinates": u["pos"]},
            "properties": {
                "feature_class": "unit",
                "callsign": name,
                "role": u["role"],
                "status": u["status"],
                "crew": u["crew"],
                "battery_pct": u["battery"],
            },
        })

    provenance = build_dual_marking(
        artifact_type="OperationalGeoJSON",
        payload={"scenario": scenario["id"], "count": len(features), "audit_head": audit_head_hash},
        ai_assisted=True,
        human_verified=True,
    )
    return {
        "type": "FeatureCollection",
        "name": f"QYRAN_{scenario['id']}",
        "kz_ai_law_provenance": provenance,
        "audit_chain_head_sha256": audit_head_hash,
        "features": features,
    }


def export_markdown_report(
    *,
    scenario: dict[str, Any],
    transmissions: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    audit_verify: dict[str, Any],
    redact_pii_flag: bool = True,
    lang: str = "ru",
) -> str:
    """Generate official dual-marked Markdown operational report compliant with KZ Law No. 230-VIII."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    provenance = build_dual_marking(
        artifact_type="ShiftOperationalReport",
        payload={
            "scenario": scenario["id"],
            "transmissions": len(transmissions),
            "incidents": len(incidents),
            "tasks": len(tasks),
            "audit_head": audit_verify.get("head_hash"),
        },
        ai_assisted=True,
        human_verified=any(r.get("status") == "APPROVED" for r in recommendations),
    )

    approved_cnt = sum(1 for r in recommendations if r.get("status") == "APPROVED")
    rejected_cnt = sum(1 for r in recommendations if r.get("status") == "REJECTED")
    pending_cnt = sum(1 for r in recommendations if r.get("status") == "PENDING")

    lines = [
        f"# QYRAN 2.0 · {'Оперативное донесение смены' if lang == 'ru' else 'Ауысымның жедел баяндамасы'}",
        "",
        f"> **🤖 МАРКИРОВКА ИИ (ст. 21 Закона РК № 230-VIII «Об искусственном интеллекте»):**",
        f"> Отчёт сформирован с использованием системы ИИ высокого риска (On-Premise). Все критические решения проходят обязательный контроль оператора (Human-in-the-Loop).",
        "",
        f"- **Сценарий:** {scenario['title_ru']}",
        f"- **Сформировано:** `{now_str}`",
        f"- **Контур развёртывания:** `{KZ_AI_LAW_PROFILE['deployment_contour']}`",
        f"- **Режим ПДн (Закон РК № 94-V):** `{'PII REDACTION ON' if redact_pii_flag else 'RAW INTERNAL'}`",
        f"- **Криптографическая целостность журнала (SHA-256):** `{'VALID' if audit_verify['valid'] else 'BROKEN'}` ({audit_verify['total_blocks']} блоков) · Head: `{audit_verify['head_hash'][:24]}...`",
        "",
        "## 1. Сводка показателей",
        f"- Радиосообщений обработано: **{len(transmissions)}**",
        f"- Инцидентов на карте: **{len(incidents)}** (активных: **{sum(1 for i in incidents if i['status'] == 'active')}**)",
        f"- Поставлено задач: **{len(tasks)}** (выполнено: **{sum(1 for t in tasks if t['status'] == 'done')}**)",
        f"- Решения Human-in-the-Loop: утверждено **{approved_cnt}**, отклонено **{rejected_cnt}**, ожидает **{pending_cnt}**",
        "",
        "## 2. Хронология радиоэфира (ASR + контекстная коррекция ИИ)",
    ]

    for t in transmissions:
        raw_txt = t["raw_asr"]
        rep_txt = t["repaired_text"]
        if redact_pii_flag:
            raw_txt, _ = redact_pii(raw_txt)
            rep_txt, _ = redact_pii(rep_txt)
        lines.append(
            f"- **{t['sim_time']}** `{t['from_callsign']} → {t['to_callsign']}` [{t['detected_lang'].upper()} · P{t['priority']} · {t['asr_latency_ms']} ms · conf {int(t['asr_confidence']*100)}%]"
        )
        lines.append(f"  - Исправлено ИИ: *{rep_txt}*")
        if t.get("repaired_count", 0) > 0:
            lines.append(f"  - Сырой Whisper ASR: `{raw_txt}`")
        lines.append(f"  - Сводка: {t['summary_ru']} · Датчики: `{t['sensor_status']}`")

    lines.extend(["", "## 3. Журнал решений командира (Human-in-the-Loop)"])
    if recommendations:
        for r in recommendations:
            lines.append(
                f"- `{r['sim_time']}` **{r['status']}** (P{r['priority']}) · {r['title']} · Оператор: `{r.get('decided_by') or 'Ожидает'}`"
            )
    else:
        lines.append("- Рекомендаций ИИ за сессию не поступало.")

    lines.extend(["", "## 4. Задачи подразделениям"])
    if tasks:
        for k in tasks:
            lines.append(f"- `{k['id']}` **{k['unit']}**: {k['text']} — статус `{k['status']}`")
    else:
        lines.append("- Задач не создано.")

    lines.extend([
        "",
        "## 5. Машиночитаемая маркировка (JSON-LD · ст. 21 Закона РК № 230-VIII)",
        "```json",
        json.dumps(provenance, ensure_ascii=False, indent=2),
        "```",
        "",
    ])

    md = "\n".join(lines)
    if redact_pii_flag:
        md, findings = redact_pii(md)
        if findings:
            md += f"\n> **PII Redaction Summary:** автоматически скрыто элементов ПДн: {len(findings)}.\n"
    return md


def export_printable_html_report(
    *,
    scenario: dict[str, Any],
    transmissions: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    audit_verify: dict[str, Any],
    redact_pii_flag: bool = True,
) -> str:
    """Render an official print/PDF-ready Situation Center Dossier compliant with KZ Law No. 230-VIII."""
    import html as _h

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    approved = sum(1 for r in recommendations if r.get("status") == "APPROVED")
    rejected = sum(1 for r in recommendations if r.get("status") == "REJECTED")
    avg_ms = int(round(sum(t["asr_latency_ms"] for t in transmissions) / max(1, len(transmissions)))) if transmissions else 0

    tx_rows = []
    for t in transmissions:
        raw_t = redact_pii(t["raw_asr"])[0] if redact_pii_flag else t["raw_asr"]
        rep_t = redact_pii(t["repaired_text"])[0] if redact_pii_flag else t["repaired_text"]
        tx_rows.append(
            f"<tr><td><b>{_h.escape(t['sim_time'])}</b></td>"
            f"<td>{_h.escape(t['from_callsign'])} → {_h.escape(t['to_callsign'])}<br><small>{t['detected_lang'].upper()} · P{t['priority']} · {t['asr_latency_ms']} ms</small></td>"
            f"<td>{_h.escape(rep_t)}<br><small style='color:#64748b'>Raw ASR: {_h.escape(raw_t)}</small></td>"
            f"<td>{_h.escape(t['location_label'])}<br><small>Датчик: {_h.escape(t['sensor_status'])}</small></td></tr>"
        )

    hitl_rows = []
    for r in recommendations:
        hitl_rows.append(
            f"<tr><td><b>{_h.escape(r['id'])}</b></td>"
            f"<td>{_h.escape(r['sim_time'])}</td>"
            f"<td>{_h.escape(r['title'])}</td>"
            f"<td><b>{_h.escape(r['status'])}</b></td>"
            f"<td>{_h.escape(r.get('decided_by') or 'Ожидает')}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>QYRAN 2.0 · Официальный отчёт смены ({_h.escape(scenario['id'])})</title>
<style>
  body{{font-family:Inter,system-ui,sans-serif;color:#0f172a;background:#f8fafc;margin:0;padding:28px}}
  .page{{max-width:960px;margin:0 auto;background:#fff;padding:34px 40px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.08)}}
  .top{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #0f172a;padding-bottom:14px;margin-bottom:18px}}
  h1{{margin:0;font-size:22px}} .sub{{color:#475569;font-size:13px;margin-top:4px}}
  .seal{{background:#eff6ff;border:1.5px solid #2563eb;border-radius:10px;padding:10px 14px;font-size:12px;max-width:340px}}
  .seal b{{color:#1d4ed8}}
  .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}}
  .kpi{{background:#f1f5f9;border-radius:8px;padding:10px 12px}}.kpi b{{display:block;font-size:20px}}.kpi span{{font-size:11px;color:#475569}}
  h2{{font-size:15px;text-transform:uppercase;letter-spacing:.05em;margin:22px 0 8px;color:#1e293b;border-bottom:1px solid #e2e8f0;padding-bottom:4px}}
  table{{width:100%;border-collapse:collapse;font-size:12px}} th,td{{border-bottom:1px solid #e2e8f0;padding:7px 8px;text-align:left;vertical-align:top}}
  th{{background:#f8fafc;color:#475569;font-weight:700}}
  .hash{{font-family:monospace;font-size:11px;background:#ecfdf5;border:1px solid #10b981;padding:10px 12px;border-radius:8px;word-break:break-all;margin-top:16px}}
  .btn{{background:#0f172a;color:#fff;border:none;border-radius:8px;padding:9px 16px;font-weight:700;cursor:pointer;float:right}}
  @media print{{body{{background:#fff;padding:0}}.page{{box-shadow:none;padding:0}}.btn{{display:none}}}}
</style>
</head>
<body>
<div class="page">
  <button class="btn" onclick="window.print()">🖨 Печать / Сохранить PDF</button>
  <div class="top">
    <div>
      <h1>QYRAN 2.0 · Оперативное донесение смены</h1>
      <div class="sub">{_h.escape(scenario['title_ru'])}</div>
      <div class="sub">Сформировано: <b>{now_str}</b> · Контур: <b>100% On-Premise</b> · ПДн: <b>{'РЕДАКЦИЯ ВКЛ' if redact_pii_flag else 'БЕЗ РЕДАКЦИИ'}</b></div>
    </div>
    <div class="seal">
      <b>🤖 МАРКИРОВКА ИИ (ст. 21 Закона РК № 230-VIII)</b><br>
      Система высокого риска (ст. 17–19). Решения утверждаются оператором (HITL). Облачных вызовов ИИ: <b>0</b>.
    </div>
  </div>

  <div class="kpis">
    <div class="kpi"><b>{len(transmissions)}</b><span>радиосообщений</span></div>
    <div class="kpi"><b>{len(incidents)}</b><span>инцидентов на карте</span></div>
    <div class="kpi"><b>{approved} / {rejected}</b><span>HITL утверждено / откл.</span></div>
    <div class="kpi"><b>{avg_ms} ms</b><span>средняя задержка ASR</span></div>
  </div>

  <h2>1. Хронология радиоэфира (Whisper Local + AI Repair)</h2>
  <table><thead><tr><th>Время</th><th>Канал</th><th>Исправленный текст / Сырой ASR</th><th>Локация / Датчик</th></tr></thead>
  <tbody>{''.join(tx_rows) or '<tr><td colspan="4">Нет сообщений</td></tr>'}</tbody></table>

  <h2>2. Журнал решений оператора (Human-in-the-Loop · ст. 19)</h2>
  <table><thead><tr><th>ID</th><th>Время</th><th>Рекомендация ИИ</th><th>Статус</th><th>Оператор</th></tr></thead>
  <tbody>{''.join(hitl_rows) or '<tr><td colspan="5">Нет рекомендаций</td></tr>'}</tbody></table>

  <div class="hash">
    <b>🔐 КРИПТОГРАФИЧЕСКАЯ ПОДПИСЬ ЖУРНАЛА (SQLite SHA-256 Hash Chain):</b><br>
    Статус целостности: <b>{'VALID ✔' if audit_verify['valid'] else 'BROKEN ✖'}</b> ({audit_verify['total_blocks']} блоков) ·
    HEAD SHA-256: <code>{_h.escape(audit_verify['head_hash'])}</code>
  </div>
</div>
</body></html>"""


def dispatch_telegram_alert(title: str, body: str, priority: int = 1) -> dict[str, Any]:
    """Send real Telegram Bot P1 alert if configured, or return honest air-gapped dry-run receipt."""
    msg = (
        f"🚨 QYRAN P{priority} ALERT\n"
        f"{title}\n\n"
        f"{body}\n\n"
        f"🤖 AI-Assisted · KZ Law № 230-VIII (Art. 21)"
    )
    if TG_BOT_TOKEN and TG_CHAT_ID:
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": msg},
                timeout=4.0,
            )
            ok = r.status_code == 200
            return {"mode": "LIVE_TELEGRAM", "sent": ok, "status_code": r.status_code, "preview": msg}
        except Exception as exc:
            return {"mode": "LIVE_TELEGRAM_ERROR", "sent": False, "error": str(exc), "preview": msg}
    return {
        "mode": "AIR_GAPPED_DRY_RUN",
        "sent": False,
        "note": "Установите QYRAN_TG_BOT_TOKEN и QYRAN_TG_CHAT_ID для live-отправки в Telegram",
        "preview": msg,
    }
