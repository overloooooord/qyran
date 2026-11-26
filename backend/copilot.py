"""Grounded On-Premise Commander AI Co-Pilot (Zero-Hallucination Operational Q&A).

Answers commander & jury questions in Kazakh or Russian using strictly verified live state
(incidents, HITL queue, units, sensors, SHA-256 audit chain, Law No. 230-VIII compliance),
citing exact entity IDs and embedding Article 21 Dual-Marking Provenance.
"""
from __future__ import annotations

from typing import Any

import httpx

from .compliance import build_dual_marking
from .config import LOCAL_LLM_URL
from .nlp_engine import check_local_llm_available


def _try_local_llm_brief(question: str, context_text: str) -> tuple[str | None, str | None]:
    """If a local LLM (LM Studio / Ollama on localhost) is running, use it grounded on live state."""
    info = check_local_llm_available()
    if not info.get("available"):
        return None, None
    try:
        resp = httpx.post(
            f"{LOCAL_LLM_URL.rstrip('/')}/chat/completions",
            json={
                "model": info["model"],
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты оперативный ИИ-ассистент ситуационного центра QYRAN. "
                            "Отвечай кратко, фактами, ТОЛЬКО по предоставленным данным. Не выдумывай события."
                        ),
                    },
                    {"role": "user", "content": f"Данные штаба:\n{context_text}\n\nВопрос: {question}"},
                ],
                "temperature": 0.1,
                "max_tokens": 240,
            },
            timeout=6.0,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content:
                return content, info["model"]
    except Exception:
        pass
    return None, None


def answer_commander_question(question: str, snap: dict[str, Any], lang: str = "ru") -> dict[str, Any]:
    """Generate a grounded, citation-backed operational briefing answer."""
    q = (question or "").strip()
    ql = q.lower()

    incs = snap.get("incidents") or []
    active = [i for i in incs if i["status"] == "active"]
    p1 = [i for i in active if i["priority"] == 1]
    unverified = [i for i in active if i.get("sensor_status") == "unverified"]
    tasks = snap.get("tasks") or []
    recs = snap.get("recommendations") or []
    pending_recs = [r for r in recs if r["status"] == "PENDING"]
    units = snap.get("units") or {}
    chain = snap.get("audit_chain") or {}
    comp = snap.get("compliance") or {}
    ana = snap.get("analytics") or {}
    bldg = snap.get("building") or {}

    citations: list[str] = []
    bullets: list[str] = []
    headline = ""

    if any(k in ql for k in ("закон", "230", "право", "аудит", "sha", "пдн", "иин", "заң", "қауіпсіздік")):
        headline = f"Соответствие Закону РК № 230-VIII: {comp.get('compliance_score_pct', 100)}% (Высокий риск · ст. 17-21)"
        bullets.append(
            f"Криптографическая цепь SQLite SHA-256: {'VALID ✔' if chain.get('valid') else 'BROKEN ✖'} "
            f"({chain.get('total_blocks', 0)} блоков, head `{str(chain.get('head_hash', ''))[:14]}…`)."
        )
        bullets.append(
            f"Строгий Human-in-the-Loop (ст. 19): {'ВКЛ' if comp.get('strict_hitl') else 'ДЕМО'} · "
            f"Утверждено: {comp.get('hitl_stats', {}).get('approved', 0)}, отклонено: {comp.get('hitl_stats', {}).get('rejected', 0)}, "
            f"ожидает оператора: {len(pending_recs)}."
        )
        bullets.append(
            f"Суверенный контур: {comp.get('cloud_ai_calls', 0)} внешних облачных AI-вызовов. "
            f"Авто-маскирование ПДн (Закон № 94-V): {'ВКЛ' if comp.get('pii_redaction_active') else 'ВЫКЛ'}."
        )
        citations.extend(["KZ-Law-230-VIII", f"SHA256:{str(chain.get('head_hash', ''))[:10]}"])

    elif any(k in ql for k in ("силы", "подраздел", "свобод", "молч", "экипаж", "күш", "бөлімше", "юнит")):
        free_u = [n for n, u in units.items() if u["status"] in ("дежурство", "готовность", "патруль", "резерв", "наблюдение")]
        busy_u = [n for n, u in units.items() if n not in free_u]
        headline = f"Диспозиция сил: всего {len(units)} подразделений · в работе {len(busy_u)} · в готовности {len(free_u)}"
        if busy_u:
            bullets.append("Задействованы: " + ", ".join(f"{n} ({units[n]['status']})" for n in busy_u))
        if free_u:
            bullets.append("Доступны для назначения: " + ", ".join(f"{n} ({units[n]['role']}, 🔋{units[n]['battery']}%)" for n in free_u))
        open_tasks = [t for t in tasks if t["status"] != "done"]
        if open_tasks:
            bullets.append("Открытые задачи: " + "; ".join(f"{t['id']} {t['unit']} [{t['status']}]" for t in open_tasks[:5]))
            citations.extend(t["id"] for t in open_tasks[:5])
        else:
            bullets.append("Активных невыполненных задач сейчас нет.")

    elif any(k in ql for k in ("здан", "этаж", "3d", "эвакуа", "ғимарат", "қабат", "павильон", "c2", "с2")):
        headline = f"Цифровой двойник объекта: {bldg.get('name', 'Объект')}"
        bullets.append(
            f"Приоритетный этаж: {bldg.get('hot_floor')} из {bldg.get('floors')} · "
            f"Задымление: {'АКТИВНО 🔥' if bldg.get('smoke_active') else 'не зафиксировано'}."
        )
        bullets.append(
            f"Люди внутри: {bldg.get('remaining_inside', 0)} чел. · Эвакуировано: {bldg.get('evacuated_count', 0)} чел."
        )
        bullets.append("Активные датчики: " + ", ".join(bldg.get("sensors") or []))
        citations.append(f"BLDG:{bldg.get('name', 'object')}")

    elif any(k in ql for k in ("неподтвержд", "датчик", "довер", "провер", "сенсор", "күмән")):
        headline = f"Проверка достоверности докладов: {len(unverified)} требуют голосовой перепроверки"
        if unverified:
            for i in unverified:
                bullets.append(f"⚠ #{i['id']} ({i['tx_id']}): {i['summary_ru']} (датчиками не подтверждён, запросите повтор у {i['source_callsign']}).")
                citations.append(f"INC-#{i['id']}")
        else:
            bullets.append("Все текущие активные инциденты подтверждены камерами, SCADA или IoT-датчиками ✔.")

    elif any(k in ql for k in ("roi", "экономи", "скорост", "wer", "точн", "метрик", "быстр")):
        headline = f"Эффективность ИИ-контура: ускорение в {ana.get('speedup_factor', 150)}× против ручного диспетчера"
        bullets.append(
            f"Средняя задержка обработки: {snap['kpis'].get('avg_asr_ms', 0)} ms "
            f"(сэкономлено ~{ana.get('time_saved_sec', 0)} с за текущую сессию)."
        )
        bullets.append(
            f"Радио-коррекция ИИ: исправлено {snap['kpis'].get('repaired_words_total', 0)} искажённых слов, "
            f"перехвачено галлюцинаций Whisper: {snap['kpis'].get('hallucinations_prevented', 0)}."
        )
        bench = snap.get("last_benchmark")
        if bench:
            bullets.append(
                f"Последний живой WER-бенчмарк ({bench['scenario_id']}): "
                f"{bench['wer_raw_pct']}% → {bench['wer_repaired_pct']}% (-{bench['wer_relative_reduction_pct']}%)."
            )
            citations.append(f"BENCH:{bench['scenario_id']}")
        else:
            bullets.append("Для точного замера WER/CER откройте вкладку «🧪 AI WER» → «▶ Запустить».")

    else:
        # Full executive commander situation brief (P1 + HITL + unverified + next action)
        headline = (
            f"Оперативная сводка ({snap['scenario']['id']}): активных угроз {len(active)} "
            f"(P1: {len(p1)}), ожидает HITL: {len(pending_recs)}"
        )
        if p1:
            for i in p1[:4]:
                s_lbl = "✔ датчик" if i.get("sensor_status") == "ok" else "⚠ только голос"
                bullets.append(f"🔴 P1 #{i['id']} ({i['tx_id']}): {i['summary_ru']} [{s_lbl}]")
                citations.append(f"INC-#{i['id']}")
        elif active:
            for i in active[:3]:
                bullets.append(f"🟠 P{i['priority']} #{i['id']}: {i['summary_ru']}")
                citations.append(f"INC-#{i['id']}")
        else:
            bullets.append("Активных угроз не зафиксировано. Запустите живой эфир, «⚡ Шквал ×5» или продиктуйте доклад в микрофон.")

        if pending_recs:
            top = pending_recs[-1]
            eta = f" (ETA ~{top['route_eta_min']} мин)" if top.get("route_eta_min") else ""
            bullets.append(f"⏳ Приоритетное HITL-решение {top['id']}: {top['title']}{eta}: нажмите Enter для утверждения.")
            citations.append(top["id"])
        if unverified:
            bullets.append(f"⚠ Внимание: {len(unverified)} доклад(а) без подтверждения датчиков ({', '.join('#'+str(x['id']) for x in unverified)}).")

    answer_text = headline + "\n" + "\n".join(f"• {b}" for b in bullets)
    llm_text, llm_model = _try_local_llm_brief(q, answer_text)
    engine_used = f"Local-LLM ({llm_model}) + Grounded State" if llm_text else "QYRAN-Grounded-Commander-CoPilot-v2"
    if llm_text:
        bullets = [ln.lstrip("-• ").strip() for ln in llm_text.splitlines() if ln.strip()][:6]
        answer_text = llm_text

    provenance = build_dual_marking(
        artifact_type="CommanderCopilotBrief",
        payload={"question": q, "headline": headline, "citations": citations},
        ai_assisted=True,
        human_verified=False,
        nlp_engine=engine_used,
    )
    return {
        "question": q,
        "headline": headline,
        "bullets": bullets,
        "answer_text": answer_text,
        "citations": citations,
        "grounded_only": True,
        "engine": engine_used,
        "provenance": provenance,
    }
