"""SQLite Persistent Operational Store + SHA-256 Tamper-Evident Audit Hash Chain."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH

GENESIS_HASH = "0" * 64


class AuditDatabase:
    """Thread-safe SQLite store with cryptographic hash-chained audit trail."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_chain (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    sim_time TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transmissions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    sim_time TEXT NOT NULL,
                    source TEXT NOT NULL,
                    audio_url TEXT,
                    detected_lang TEXT NOT NULL,
                    raw_asr TEXT NOT NULL,
                    repaired_text TEXT NOT NULL,
                    asr_latency_ms INTEGER NOT NULL,
                    asr_confidence REAL NOT NULL,
                    snr_db REAL,
                    data_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recommendations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    sim_time TEXT NOT NULL,
                    title TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    decided_by TEXT,
                    decided_utc TEXT,
                    decision_note TEXT,
                    payload_json TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def _compute_hash(
        self,
        seq_hint: int,
        prev_hash: str,
        ts_utc: str,
        actor: str,
        event_type: str,
        summary: str,
        payload_json: str,
    ) -> str:
        raw = f"{seq_hint}|{prev_hash}|{ts_utc}|{actor}|{event_type}|{summary}|{payload_json}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append_audit(
        self,
        session_id: str,
        sim_time: str,
        actor: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an immutable hash-linked block to the audit chain."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT seq, entry_hash FROM audit_chain ORDER BY seq DESC LIMIT 1"
            )
            row = cur.fetchone()
            prev_hash = row["entry_hash"] if row else GENESIS_HASH
            next_seq = (row["seq"] + 1) if row else 1
            ts_utc = datetime.now(timezone.utc).isoformat()
            payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, default=str)
            entry_hash = self._compute_hash(
                next_seq, prev_hash, ts_utc, actor, event_type, summary, payload_json
            )
            cur = self._conn.execute(
                """
                INSERT INTO audit_chain
                    (seq, session_id, ts_utc, sim_time, actor, event_type, summary, payload_json, prev_hash, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (next_seq, session_id, ts_utc, sim_time, actor, event_type, summary, payload_json, prev_hash, entry_hash),
            )
            self._conn.commit()
            return {
                "seq": next_seq,
                "session_id": session_id,
                "ts_utc": ts_utc,
                "sim_time": sim_time,
                "actor": actor,
                "event_type": event_type,
                "summary": summary,
                "payload": payload or {},
                "prev_hash": prev_hash,
                "entry_hash": entry_hash,
            }

    def save_transmission(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO transmissions
                    (id, session_id, scenario_id, ts_utc, sim_time, source, audio_url, detected_lang,
                     raw_asr, repaired_text, asr_latency_ms, asr_confidence, snr_db, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["session_id"],
                    record["scenario_id"],
                    record["ts_utc"],
                    record["sim_time"],
                    record["source"],
                    record.get("audio_url"),
                    record["detected_lang"],
                    record["raw_asr"],
                    record["repaired_text"],
                    int(record["asr_latency_ms"]),
                    float(record["asr_confidence"]),
                    record.get("snr_db"),
                    json.dumps(record, ensure_ascii=False, default=str),
                ),
            )
            self._conn.commit()

    def save_recommendation(self, rec: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO recommendations
                    (id, session_id, created_utc, sim_time, title, action_type, priority,
                     status, decided_by, decided_utc, decision_note, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec["id"],
                    rec["session_id"],
                    rec["created_utc"],
                    rec["sim_time"],
                    rec["title"],
                    rec["action_type"],
                    int(rec["priority"]),
                    rec["status"],
                    rec.get("decided_by"),
                    rec.get("decided_utc"),
                    rec.get("decision_note"),
                    json.dumps(rec.get("payload", {}), ensure_ascii=False, default=str),
                ),
            )
            self._conn.commit()

    def get_recent_audit(self, session_id: str | None = None, limit: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            if session_id:
                rows = self._conn.execute(
                    "SELECT * FROM audit_chain WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM audit_chain ORDER BY seq DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            out = []
            for r in reversed(rows):
                out.append(
                    {
                        "seq": r["seq"],
                        "session_id": r["session_id"],
                        "ts_utc": r["ts_utc"],
                        "sim_time": r["sim_time"],
                        "actor": r["actor"],
                        "event_type": r["event_type"],
                        "summary": r["summary"],
                        "payload": json.loads(r["payload_json"]),
                        "prev_hash": r["prev_hash"],
                        "entry_hash": r["entry_hash"],
                    }
                )
            return out

    def verify_chain(self) -> dict[str, Any]:
        """Walk every block from Genesis to Head and verify SHA-256 integrity."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM audit_chain ORDER BY seq ASC").fetchall()
            prev = GENESIS_HASH
            broken_seq: int | None = None
            reason: str | None = None
            for r in rows:
                if r["prev_hash"] != prev:
                    broken_seq = r["seq"]
                    reason = "prev_hash mismatch (chain link broken)"
                    break
                expected = self._compute_hash(
                    r["seq"],
                    r["prev_hash"],
                    r["ts_utc"],
                    r["actor"],
                    r["event_type"],
                    r["summary"],
                    r["payload_json"],
                )
                if r["entry_hash"] != expected:
                    broken_seq = r["seq"]
                    reason = "entry_hash mismatch (record content tampered)"
                    break
                prev = r["entry_hash"]
            return {
                "valid": broken_seq is None,
                "total_blocks": len(rows),
                "head_hash": prev,
                "broken_seq": broken_seq,
                "reason": reason,
                "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            }

    def simulate_tamper_demo(self) -> dict[str, Any]:
        """Run an isolated in-memory tamper attack simulation without modifying the live DB."""
        with self._lock:
            rows = [dict(r) for r in self._conn.execute("SELECT * FROM audit_chain ORDER BY seq ASC").fetchall()]
        if not rows:
            return {
                "simulated": False,
                "note": "Журнал пуст — выполните хотя бы одно действие",
            }
        before_head = rows[-1]["entry_hash"]
        target = rows[0]
        orig_summary = target["summary"]
        tampered_summary = orig_summary + " [ПОДМЕНЕНО: скрыт инцидент P1]"

        # Re-verify tampered copy
        prev = GENESIS_HASH
        broken_seq = None
        broken_reason = None
        expected_hash = None
        stored_hash = None
        for idx, r in enumerate(rows):
            summary = tampered_summary if idx == 0 else r["summary"]
            if r["prev_hash"] != prev:
                broken_seq = r["seq"]
                broken_reason = "prev_hash mismatch"
                break
            expected = self._compute_hash(
                r["seq"], r["prev_hash"], r["ts_utc"], r["actor"], r["event_type"], summary, r["payload_json"]
            )
            if r["entry_hash"] != expected:
                broken_seq = r["seq"]
                broken_reason = "SHA-256 entry_hash mismatch: обнаружена ретроактивная подмена записи!"
                expected_hash = expected
                stored_hash = r["entry_hash"]
                break
            prev = r["entry_hash"]

        return {
            "simulated": True,
            "isolated_sandbox": True,
            "live_db_untouched": True,
            "target_seq": target["seq"],
            "original_summary": orig_summary,
            "tampered_summary": tampered_summary,
            "attack_detected": broken_seq is not None,
            "broken_seq": broken_seq,
            "reason": broken_reason,
            "stored_hash": stored_hash,
            "recomputed_hash": expected_hash,
            "live_head_hash": before_head,
            "total_blocks": len(rows),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
