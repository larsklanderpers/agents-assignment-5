"""Durable local audit records and an email/Slack simulation outbox."""
import json
import os
import sqlite3
import math
from datetime import datetime, timezone
from contextlib import contextmanager
from backend.guardrails.output_filter import sanitize_output


def now():
    return datetime.now(timezone.utc).isoformat()


class ActivityStore:
    def __init__(self, path=None):
        self.path = str(path or os.getenv("APPROVAL_AUDIT_DB", "approval_audit.db"))
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS requests (
                    run_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, title TEXT,
                    amount REAL, department TEXT, risk_level TEXT, status TEXT,
                    current_stage TEXT, parallel_reviews INTEGER,
                    completed_stages TEXT NOT NULL, pending_stages TEXT NOT NULL,
                    decisions TEXT NOT NULL, created_at TEXT, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, event_key TEXT NOT NULL,
                    stage TEXT, event_type TEXT, timestamp TEXT, reviewer TEXT,
                    decision TEXT, details TEXT NOT NULL, UNIQUE(run_id,event_key)
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, run_id TEXT NOT NULL,
                    channel TEXT, recipient TEXT, message TEXT, timestamp TEXT,
                    delivery TEXT NOT NULL DEFAULT 'simulated', UNIQUE(event_id,channel)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, state, stage, output=None, *, pending=False, started=False, error=None):
        output = output or {}
        merged = {**state, **output}
        run_id = merged.get("audit_run_id")
        if not run_id:
            return
        timestamp = now()
        amount = merged.get("amount")
        if type(amount) not in (int, float) or not math.isfinite(amount):
            amount = None
        department = merged.get("department")
        if not isinstance(department, str):
            department = None
        review = next((output[k] for k in ("parallel_manager_decision", "parallel_finance_decision")
                       if output.get(k)), None)
        if review is None and stage in ("manager_review", "finance_review", "final_signoff") and not pending:
            review = next((d for d in output.get("decisions", []) if d["stage"] == stage), None)
        event_type = ("review_requested" if pending else "error" if error else "decision" if review
                      else "stage_started" if started else "stage_completed")
        details = {"message": sanitize_output(str(error))} if error else {}
        if review:
            details["comments"] = review.get("comments", "")
        if stage == "assess_risk" and "risk_reasoning" in output:
            details["risk_reasoning"] = output.get("risk_reasoning", "")
        if stage == "submit_request":
            details["validation_message"] = output.get("validation_message", "")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                run_id, str(merged.get("request_id", "")), sanitize_output(str(merged.get("title") or "")),
                amount, department, merged.get("risk_level"), "pending",
                stage, int(bool(merged.get("parallel_approvals"))), "[]", "[]", "[]", timestamp, timestamp))
            row = dict(db.execute("SELECT * FROM requests WHERE run_id=?", (run_id,)).fetchone())
            completed = json.loads(row["completed_stages"])
            waiting = json.loads(row["pending_stages"])
            decisions = json.loads(row["decisions"])
            if pending:
                if stage not in waiting:
                    waiting.append(stage)
            elif not started:
                waiting = [s for s in waiting if s != stage]
                if not error and stage not in completed:
                    completed.append(stage)
            if review:
                decisions = [d for d in decisions if d["stage"] != review["stage"]] + [review]
            if stage == "join_parallel_reviews" and "decisions" in output:
                decisions = output["decisions"]
            terminal = stage in ("process_request", "handle_rejection") and not error and not started
            status = "error" if error else merged.get("status", row["status"])
            if terminal:
                waiting = []
            db.execute("""UPDATE requests SET risk_level=?,status=?,current_stage=?,parallel_reviews=?,
                          completed_stages=?,pending_stages=?,decisions=?,updated_at=? WHERE run_id=?""", (
                merged.get("risk_level"), status, "complete" if terminal else stage,
                int(bool(merged.get("parallel_approvals"))), json.dumps(completed), json.dumps(waiting),
                json.dumps(decisions), timestamp, run_id))
            cursor = db.execute("""INSERT OR IGNORE INTO audit_events
                (run_id,event_key,stage,event_type,timestamp,reviewer,decision,details) VALUES (?,?,?,?,?,?,?,?)""", (
                run_id, f"{stage}:{event_type}", stage, event_type, timestamp,
                review.get("reviewer") if review else None, review.get("decision") if review else None,
                json.dumps(details)))
            if pending and cursor.rowcount:
                role = {"manager_review": "Manager", "finance_review": "Finance", "final_signoff": "Executive"}[stage]
                for channel in ("email", "slack"):
                    db.execute("""INSERT INTO notifications
                        (event_id,run_id,channel,recipient,message,timestamp) VALUES (?,?,?,?,?,?)""", (
                        cursor.lastrowid, run_id, channel, f"{role} review queue (simulation)",
                        f"Review requested for {merged.get('request_id')}: {sanitize_output(merged.get('title', ''))}", timestamp))

    @staticmethod
    def request_dict(row):
        result = dict(row)
        for field in ("completed_stages", "pending_stages", "decisions"):
            result[field] = json.loads(result[field])
        result["parallel_reviews"] = bool(result["parallel_reviews"])
        return result

    def dashboard(self):
        with self.connect() as db:
            counts = {r["status"]: r["n"] for r in db.execute("SELECT status,COUNT(*) n FROM requests GROUP BY status")}
            waiting = db.execute("SELECT COUNT(*) FROM requests WHERE pending_stages!='[]' AND status='pending'").fetchone()[0]
            return {"counts": {"total": sum(counts.values()), "pending": counts.get("pending", 0),
                               "awaiting_review": waiting, "approved": counts.get("approved", 0),
                               "rejected": counts.get("rejected", 0), "error": counts.get("error", 0)},
                    "requests": [self.request_dict(r) for r in db.execute("SELECT * FROM requests ORDER BY updated_at DESC LIMIT 100")],
                    "notifications": [dict(r) for r in db.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")],
                    "updated_at": now()}

    def audit(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM requests WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            events = []
            for event in db.execute("SELECT * FROM audit_events WHERE run_id=? ORDER BY id", (run_id,)):
                item = dict(event)
                item["details"] = json.loads(item["details"])
                events.append(item)
            return {"request": self.request_dict(row), "events": events,
                    "notifications": [dict(r) for r in db.execute("SELECT * FROM notifications WHERE run_id=? ORDER BY id", (run_id,))]}

    def export(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT run_id FROM requests ORDER BY created_at")]
        return {"exported_at": now(), "notification_delivery": "Simulation only; no messages sent",
                "runs": [self.audit(run_id) for run_id in ids]}
