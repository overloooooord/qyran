"""Automated verification suite for QYRAN 2.0 (IT FEST 2026 MVP)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ["QYRAN_SKIP_PRELOAD"] = "1"

from fastapi.testclient import TestClient

from backend.audio_dsp import analyze_audio, apply_radio_degradation, load_wav_16k
from backend.audit import AuditDatabase
from backend.compliance import build_dual_marking, redact_pii
from backend.config import SCENARIOS_DIR
from backend.exporters import export_cot_xml, export_geojson
from backend.nlp_engine import extract_operational_intelligence
from backend.scenarios import build_scenarios


class TestQyranCore(unittest.TestCase):
    def setUp(self) -> None:
        self.scenarios = build_scenarios()

    def test_audio_dsp_and_radio_degradation(self) -> None:
        wav = SCENARIOS_DIR / "astana_expo" / "a01.wav"
        self.assertTrue(wav.exists(), "Astana a01.wav must exist")
        sr, samples = load_wav_16k(wav)
        self.assertEqual(sr, 16000)
        analysis = analyze_audio(samples, sr, radio_filtered=True)
        self.assertGreater(analysis.duration_sec, 3.0)
        self.assertEqual(len(analysis.waveform), 64)
        self.assertGreater(analysis.snr_db, 3.0)

        degraded = apply_radio_degradation(samples, sr=sr)
        self.assertEqual(len(degraded), len(samples))

    def test_kazakh_drone_not_confused_with_russian_smoke(self) -> None:
        """Regression test: Kazakh verb suffix '-дым' in 'байқадым' must NEVER trigger fire_smoke."""
        sc = self.scenarios["astana_expo"]
        res = extract_operational_intelligence(
            "Орталық, орталық, мен қырам бір. Жетінші шаршыда ұрғсатсыз дұром байқадым. Биіктігі 200 метр экспосферасына ғарай ұшып барады.",
            "kk",
            sc,
        )
        self.assertEqual(res["kind"], "drone")
        self.assertEqual(res["priority"], 1)
        self.assertEqual(res["square"], 7)
        self.assertEqual(res["altitude_m"], 200)
        self.assertIn("дрон", res["repaired_text"].lower())
        self.assertIn("Қыран-1", res["repaired_text"])
        self.assertGreater(res["repaired_count"], 2)

    def test_russian_smoke_contextual_repair(self) -> None:
        sc = self.scenarios["almaty_zenkova"]
        res = extract_operational_intelligence(
            "Сумкар, я Орлан-3. Вижу дом на крыше, северо-восточный угол здания.",
            "ru",
            sc,
        )
        self.assertEqual(res["kind"], "fire_smoke")
        self.assertIn("дым на крыше", res["repaired_text"].lower())
        self.assertIn("Арлан-3", res["repaired_text"])
        self.assertEqual(res["direction"], "NE")

    def test_astana_substation_and_unverified_casualties(self) -> None:
        sc = self.scenarios["astana_expo"]
        sub = extract_operational_intelligence(
            "Центр, Техник-7. На подстанции Левобережья скачок напряжения и утечка хладагента.",
            "ru",
            sc,
        )
        self.assertEqual(sub["kind"], "infrastructure")
        self.assertEqual(sub["priority"], 1)
        self.assertEqual(sub["sensor_status"], "ok")

        med = extract_operational_intelligence(
            "Орталық, Бекет-үш. Мегасилк Вей маңында түтінден 2 адамыз ардап шекті. Жедел жәрдем 103 ұғыл керек.",
            "kk",
            sc,
        )
        self.assertEqual(med["kind"], "casualties")
        self.assertEqual(med["priority"], 1)
        self.assertEqual(med["sensor_status"], "unverified")
        self.assertTrue(med["needs_recheck"])
        self.assertIn("MEGA Silk Way", med["repaired_text"])

    def test_pii_redaction_kazakhstan_formats(self) -> None:
        raw = "Гражданин Иванов Асан, ИИН 040512500123, тел +7 705 193 82 42, авто 777 KZ 01, почта test@gov.kz"
        redacted, findings = redact_pii(raw)
        self.assertNotIn("040512500123", redacted)
        self.assertNotIn("705 193 82 42", redacted)
        self.assertNotIn("777 KZ 01", redacted)
        self.assertNotIn("test@gov.kz", redacted)
        self.assertNotIn("Иванов Асан", redacted)
        self.assertGreaterEqual(len(findings), 5)

    def test_dual_marking_and_sha256_tamper_detection(self) -> None:
        marking = build_dual_marking("TestRecord", {"a": 1}, ai_assisted=True, human_verified=True, human_operator="Op-1")
        self.assertEqual(marking["kz_ai_law"]["risk_tier"], "HIGH")
        self.assertTrue(marking["kz_ai_law"]["human_verified"])
        self.assertEqual(len(marking["technical_provenance"]["content_sha256"]), 64)

        with tempfile.TemporaryDirectory() as td:
            db = AuditDatabase(Path(td) / "test_audit.db")
            db.append_audit("s1", "14:10:01", "ASR", "RADIO_INGEST", "Clip 1", {"ok": True})
            db.append_audit("s1", "14:10:05", "OP-1", "HITL_APPROVED", "Approved dispatch", {"rec": "REC-001"})
            res_ok = db.verify_chain()
            self.assertTrue(res_ok["valid"])
            self.assertEqual(res_ok["total_blocks"], 2)

            # Simulate database tampering -> SHA-256 chain MUST detect it!
            db._conn.execute("UPDATE audit_chain SET summary = 'TAMPERED' WHERE seq = 1")
            db._conn.commit()
            res_bad = db.verify_chain()
            self.assertFalse(res_bad["valid"])
            self.assertEqual(res_bad["broken_seq"], 1)
            db.close()

    def test_api_end_to_end_hitl_and_exports(self) -> None:
        from backend.app import app

        with TestClient(app) as client:
            h = client.get("/api/health")
            self.assertEqual(h.status_code, 200)
            self.assertEqual(h.json()["status"], "ok")

            # Activate Astana EXPO scenario
            r_act = client.post("/api/scenarios/astana_expo/activate")
            self.assertEqual(r_act.status_code, 200)

            # Ingest Kazakh emergency report via text
            r_tx = client.post(
                "/api/ingest/text",
                json={"text": "ЭКСПО павильон С-2, екінші қабатта электр қалқанынан қою түтін шықты", "lang": "kk"},
            )
            self.assertEqual(r_tx.status_code, 200)
            body = r_tx.json()
            self.assertEqual(body["transmission"]["kind"], "fire_smoke")
            self.assertIsNotNone(body["recommendation"])
            rec_id = body["recommendation"]["id"]

            # Approve via mandatory HITL gate
            r_dec = client.post(
                f"/api/recommendations/{rec_id}/decide",
                json={"decision": "APPROVED", "operator": "Жюри IT FEST"},
            )
            self.assertEqual(r_dec.status_code, 200)
            self.assertEqual(r_dec.json()["recommendation"]["status"], "APPROVED")

            # Verify SHA-256 audit chain
            r_ver = client.get("/api/audit/verify")
            self.assertTrue(r_ver.json()["valid"])

            # Verify TAK/CoT XML, GeoJSON, and Dual-Marked Markdown exports
            r_cot = client.get("/api/export/cot.xml")
            self.assertEqual(r_cot.status_code, 200)
            self.assertIn("<events", r_cot.text)
            self.assertIn("Law-RK-230-VIII", r_cot.text)

            r_geo = client.get("/api/export/geojson")
            self.assertEqual(r_geo.status_code, 200)
            self.assertEqual(r_geo.json()["type"], "FeatureCollection")
            self.assertIn("kz_ai_law_provenance", r_geo.json())

            r_md = client.get("/api/export/report.md")
            self.assertEqual(r_md.status_code, 200)
            self.assertIn("230-VIII", r_md.text)

            # Printable PDF/HTML dossier & interactive IT FEST 2026 pitch deck
            r_html = client.get("/api/export/report.html")
            self.assertEqual(r_html.status_code, 200)
            self.assertIn("window.print()", r_html.text)

            r_pitch = client.get("/pitch")
            self.assertEqual(r_pitch.status_code, 200)
            self.assertIn("IT FEST 2026", r_pitch.text)

            # Isolated SHA-256 tamper simulation must detect attack WITHOUT corrupting live DB
            r_tamp = client.post("/api/audit/simulate-tamper")
            self.assertEqual(r_tamp.status_code, 200)
            self.assertTrue(r_tamp.json()["attack_detected"])
            self.assertTrue(client.get("/api/audit/verify").json()["valid"])

            # Dynamic nearest-unit OSRM/fallback routing to a brand-new spoken landmark (Baiterek)
            r_bt = client.post("/api/ingest/text", json={"text": "Пожар возле Байтерека, срочно нужна 101!", "lang": "ru"})
            self.assertEqual(r_bt.status_code, 200)
            rec_bt = r_bt.json()["recommendation"]
            self.assertIsNotNone(rec_bt["route_eta_min"])
            self.assertEqual(r_bt.json()["transmission"]["location_ref"], "baiterek")

            # Edge-vision image upload analysis (synthetic red/orange fire + gray smoke JPEG)
            import io
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (320, 200), (30, 35, 42))
            draw = ImageDraw.Draw(img)
            draw.rectangle([10, 10, 310, 100], fill=(160, 164, 168))  # dense smoke
            draw.ellipse([110, 90, 220, 190], fill=(245, 110, 20))   # fire hotspot
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            r_cv = client.post("/api/ingest/image", files={"file": ("fire_test.jpg", buf.getvalue(), "image/jpeg")})
            self.assertEqual(r_cv.status_code, 200)
            self.assertEqual(r_cv.json()["analysis"]["verdict"], "ANOMALY_CONFIRMED")

            # 3D building plan send
            r_b3 = client.post("/api/building/send-plan", json={"unit": "Өрт-2", "floor": 2})
            self.assertEqual(r_b3.status_code, 200)
            self.assertTrue(r_b3.json()["sent"])

            # Parallel x5 stress-burst triage
            r_burst = client.post("/api/scenarios/astana_expo/stress-burst")
            self.assertEqual(r_burst.status_code, 200)
            self.assertEqual(r_burst.json()["processed_count"], 5)

            # Grounded Commander Co-Pilot Q&A with Law No. 230-VIII provenance
            r_cop = client.post("/api/copilot/ask", json={"question": "Дай полную сводку P1 и Закон 230-VIII"})
            self.assertEqual(r_cop.status_code, 200)
            self.assertTrue(r_cop.json()["grounded_only"])
            self.assertIn("provenance", r_cop.json())

            # Real AI Telemetry + Real TTS synthesis + WAV playback serving
            r_tel = client.get("/api/ai/telemetry")
            self.assertEqual(r_tel.status_code, 200)
            self.assertIn("nli", r_tel.json())
            self.assertIn("tts", r_tel.json())

            r_tts = client.post(
                "/api/tts/speak",
                json={"text": "Внимание, тест радиосвязи.", "voice_key": "ru_male", "radio_effect": True},
            )
            self.assertEqual(r_tts.status_code, 200)
            tts_url = r_tts.json()["audio_url"]
            self.assertGreater(r_tts.json()["duration_sec"], 0.3)
            r_wav = client.get(tts_url)
            self.assertEqual(r_wav.status_code, 200)
            self.assertGreater(len(r_wav.content), 2000)


if __name__ == "__main__":
    unittest.main()
