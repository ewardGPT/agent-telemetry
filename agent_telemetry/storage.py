"""SQLite + JSONL storage for agent traces.

SQLite stores indexed metadata for fast queries (search, cost, drift).
JSONL stores full trace payloads for replay and detailed analysis.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agent_telemetry.schema import Trace


class TelemetryStore:
    """Dual storage: SQLite for query + JSONL for raw data."""

    DEFAULT_DIR = Path.home() / ".config" / "agent-telemetry"

    def __init__(self, root: str | Path | None = None) -> None:
        if root:
            self.root = Path(root)
        elif os.environ.get("TELEMETRY_DIR"):
            self.root = Path(os.environ["TELEMETRY_DIR"])
        else:
            self.root = self.DEFAULT_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "traces.db"
        self._traces_path = self.root / "traces.jsonl"
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                agent_version TEXT,
                environment TEXT NOT NULL DEFAULT 'production',
                session_id TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms REAL DEFAULT 0,
                span_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0.0,
                tags TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_traces_agent ON traces(agent_name);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_traces_env ON traces(environment);
        """)
        conn.commit()
        conn.close()

    # ── Write ──────────────────────────────────────────────────────────────

    def store(self, trace: Trace, tags: dict | None = None) -> str:
        """Store a trace in SQLite + JSONL. Returns trace_id."""
        trace.finish()

        # SQLite
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO traces
               (trace_id, agent_name, agent_version, environment, session_id,
                started_at, finished_at, duration_ms, span_count, error_count,
                total_tokens, total_cost, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace.trace_id,
                trace.agent_name,
                trace.agent_version,
                trace.environment,
                trace.session_id,
                trace.started_at.isoformat(),
                trace.finished_at.isoformat() if trace.finished_at else None,
                trace.duration_ms(),
                len(trace.spans),
                trace.error_count(),
                trace.total_tokens(),
                trace.total_cost(),
                json.dumps(tags or {}),
            ),
        )
        conn.commit()
        conn.close()

        # JSONL
        with open(self._traces_path, "a") as f:
            f.write(json.dumps(trace.to_dict(), default=str) + "\n")

        return trace.trace_id

    # ── Query ──────────────────────────────────────────────────────────────

    def search(
        self,
        *,
        agent_name: str | None = None,
        error: bool = False,
        min_duration_ms: float | None = None,
        start_after: datetime | None = None,
        start_before: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Search traces with filters."""
        conn = self._get_conn()
        conditions = ["1=1"]
        params: list = []

        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if error:
            conditions.append("error_count > 0")
        if min_duration_ms:
            conditions.append("duration_ms >= ?")
            params.append(min_duration_ms)
        if start_after:
            conditions.append("started_at >= ?")
            params.append(start_after.isoformat())
        if start_before:
            conditions.append("started_at <= ?")
            params.append(start_before.isoformat())

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM traces WHERE {where} ORDER BY started_at DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def cost_report(
        self,
        agent_name: str,
        group_by: str = "agent_name",
        start_after: datetime | None = None,
        start_before: datetime | None = None,
    ) -> list[dict]:
        """Aggregate cost by group."""
        conn = self._get_conn()
        conditions = ["agent_name = ?"]
        params: list = [agent_name]

        if start_after:
            conditions.append("started_at >= ?")
            params.append(start_after.isoformat())
        if start_before:
            conditions.append("started_at <= ?")
            params.append(start_before.isoformat())

        where = " AND ".join(conditions)
        valid_groups = {"agent_name", "environment", "session_id"}
        group_col = group_by if group_by in valid_groups else "agent_name"

        rows = conn.execute(
            f"""SELECT {group_col} as grp,
                       SUM(total_tokens) as tokens,
                       SUM(total_cost) as cost,
                       COUNT(*) as trace_count,
                       AVG(duration_ms) as avg_duration_ms,
                       SUM(error_count) as total_errors
                FROM traces
                WHERE {where}
                GROUP BY {group_col}
                ORDER BY cost DESC""",
            params,
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def error_summary(
        self,
        agent_name: str | None = None,
        start_after: datetime | None = None,
        start_before: datetime | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List recent error traces with error details."""
        conn = self._get_conn()
        conditions = ["error_count > 0"]
        params: list = []

        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if start_after:
            conditions.append("started_at >= ?")
            params.append(start_after.isoformat())
        if start_before:
            conditions.append("started_at <= ?")
            params.append(start_before.isoformat())

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM traces WHERE {where} ORDER BY started_at DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def stats(
        self,
        agent_name: str | None = None,
        start_after: datetime | None = None,
        start_before: datetime | None = None,
    ) -> dict:
        """Aggregate statistics over a time window."""
        conn = self._get_conn()
        conditions = ["1=1"]
        params: list = []

        if agent_name:
            conditions.append("agent_name = ?")
            params.append(agent_name)
        if start_after:
            conditions.append("started_at >= ?")
            params.append(start_after.isoformat())
        if start_before:
            conditions.append("started_at <= ?")
            params.append(start_before.isoformat())

        where = " AND ".join(conditions)
        row = conn.execute(
            f"""SELECT COUNT(*) as total_traces,
                       SUM(total_tokens) as total_tokens,
                       SUM(total_cost) as total_cost_usd,
                       AVG(duration_ms) as avg_duration_ms,
                       SUM(error_count) as total_errors,
                       CAST(SUM(error_count) AS REAL) / MAX(COUNT(*), 1) as error_rate
                FROM traces WHERE {where}""",
            params,
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    def drift_check(
        self,
        agent_name: str,
        baseline: dict,
        window_hours: float = 24,
    ) -> dict:
        """Compare current stats against a baseline for drift detection."""
        since = datetime.now(timezone.utc)
        stats = self.stats(agent_name=agent_name, start_after=since)

        diff = {}
        for key in ("avg_duration_ms", "error_rate", "total_tokens"):
            baseline_val = baseline.get(key, 0)
            current_val = stats.get(key, 0) or 0
            if baseline_val > 0:
                pct = (current_val - baseline_val) / baseline_val * 100
                diff[key] = {
                    "baseline": baseline_val,
                    "current": current_val,
                    "pct_change": round(pct, 1),
                }
            else:
                diff[key] = {"baseline": baseline_val, "current": current_val, "pct_change": 0}

        return {"agent": agent_name, "drift": diff, "window_hours": window_hours}
