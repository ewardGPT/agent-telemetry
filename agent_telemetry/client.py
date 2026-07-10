"""TelemetrySDKClient — the single entry point for the agent-telemetry Python SDK.

Patterned after EvalClient:
- env-var config fallback (zero-config startup)
- @cached_property resource hierarchy (IDE-discoverable)
- sync/async mirror
- query audit trail to YAML

Usage:
    from agent_telemetry import TelemetrySDKClient

    client = TelemetrySDKClient()
    traces = client.traces.search(agent="agentic-inbox", last="24h")
    cost = client.cost.by_agent(agent="agentic-inbox")
    agents = client.agents.list()

NOTE: This is the *query* SDK.  For *instrumentation* (sending telemetry),
use TelemetryClient from agent_telemetry.instrument instead.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Any

from agent_telemetry.storage import TelemetryStore

_QUERIES_FILE = "queries.yaml"


def _parse_time(when: str | None) -> datetime | None:
    if not when:
        return None
    m = re.match(r"(\d+)\s*(h|d|m|w)", when.lower())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2)
    now = datetime.now(timezone.utc)
    if unit == "m":
        return now - timedelta(minutes=value)
    elif unit == "h":
        return now - timedelta(hours=value)
    elif unit == "d":
        return now - timedelta(days=value)
    elif unit == "w":
        return now - timedelta(weeks=value)
    return None


# ── TelemetrySDKClient ─────────────────────────────────────────────────


class TelemetrySDKClient:
    """Agent Telemetry Python SDK entry point.

    One import, one object, everything discoverable from there.
    For querying/reading telemetry data (not instrumentation).
    """

    store_dir: str | None

    def __init__(
        self,
        *,
        store_dir: str | None = None,
    ) -> None:
        self.store_dir = store_dir
        self._store = TelemetryStore(root=store_dir) if store_dir else TelemetryStore()
        queries_dir = self._store.root
        queries_dir.mkdir(parents=True, exist_ok=True)
        self._queries_path = queries_dir / _QUERIES_FILE

    def __repr__(self) -> str:
        return f"TelemetrySDKClient(store_dir={self._store.root})"

    # ── Resource hierarchy ──────────────────────────────────────────────

    @cached_property
    def traces(self) -> TracesResource:
        return TracesResource(self)

    @cached_property
    def cost(self) -> CostResource:
        return CostResource(self)

    @cached_property
    def agents(self) -> AgentsResource:
        return AgentsResource(self)

    @cached_property
    def alerts(self) -> AlertsResource:
        return AlertsResource(self)

    # ── Query audit ─────────────────────────────────────────────────────

    def _log_query(self, resource: str, method: str, params: dict) -> None:
        import yaml

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resource": resource,
            "method": method,
            "params": params,
        }
        existing: list[dict] = []
        if self._queries_path.exists():
            raw = self._queries_path.read_text()
            if raw.strip():
                existing = yaml.safe_load(raw) or []
        existing.append(record)
        self._queries_path.write_text(
            yaml.dump(existing, sort_keys=False, default_flow_style=False)
        )

    # ── Store access (used by resources) ────────────────────────────────

    @property
    def _store_root(self) -> Path:
        return self._store.root


# ── TracesResource ─────────────────────────────────────────────────────


class TracesResource:
    """Query trace data: search, retrieve, and find errors."""

    def __init__(self, client: TelemetrySDKClient) -> None:
        self._client = client
        self._store = client._store

    def search(
        self,
        *,
        agent: str | None = None,
        last: str | None = None,
        status: str | None = None,
        slow: float | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Search traces with filters.

        Args:
            agent: Filter by agent name.
            last: Time window, e.g. "24h", "7d", "30m".
            status: "error" to show only error traces, "ok" for non-error.
            slow: Minimum duration in milliseconds.
            limit: Max results (default 50).
        """
        self._client._log_query(
            "traces",
            "search",
            {
                "agent": agent,
                "last": last,
                "status": status,
                "slow": slow,
                "limit": limit,
            },
        )
        return self._store.search(
            agent_name=agent,
            error=(status == "error"),
            min_duration_ms=slow,
            start_after=_parse_time(last),
            limit=limit,
        )

    def get(self, trace_id: str) -> dict | None:
        """Retrieve a full trace from the JSONL store."""
        self._client._log_query("traces", "get", {"trace_id": trace_id})
        traces_path = self._store._traces_path
        if not traces_path.exists():
            return None
        with open(traces_path) as f:
            for line in f:
                data = json.loads(line)
                if data.get("trace_id") == trace_id:
                    return data
        return None

    def errors(
        self,
        *,
        agent: str | None = None,
        last: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Show recent error traces.

        Args:
            agent: Filter by agent name.
            last: Time window, e.g. "24h", "7d".
            limit: Max results (default 20).
        """
        self._client._log_query(
            "traces",
            "errors",
            {
                "agent": agent,
                "last": last,
                "limit": limit,
            },
        )
        return self._store.error_summary(
            agent_name=agent,
            start_after=_parse_time(last),
            limit=limit,
        )


# ── CostResource ───────────────────────────────────────────────────────


class CostResource:
    """Query cost data: per-agent, total, breakdown."""

    def __init__(self, client: TelemetrySDKClient) -> None:
        self._client = client
        self._store = client._store

    def by_agent(
        self,
        agent: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        """Cost breakdown for a specific agent.

        Args:
            agent: Agent name.
            since: Start of time window, e.g. "7d", "24h".
            until: End of time window (rarely needed).
        """
        self._client._log_query(
            "cost",
            "by_agent",
            {
                "agent": agent,
                "since": since,
                "until": until,
            },
        )
        return self._store.cost_report(
            agent_name=agent,
            start_after=_parse_time(since),
            start_before=_parse_time(until),
        )

    def total(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict:
        """Aggregate cost across all agents."""
        self._client._log_query(
            "cost",
            "total",
            {
                "since": since,
                "until": until,
            },
        )
        conn = self._store._get_conn()
        conditions = ["1=1"]
        params: list = []
        if since:
            conditions.append("started_at >= ?")
            params.append(_parse_time(since).isoformat())
        if until:
            conditions.append("started_at <= ?")
            params.append(_parse_time(until).isoformat())
        where = " AND ".join(conditions)
        row = conn.execute(
            f"""SELECT COUNT(*) as total_traces,
                       SUM(total_tokens) as total_tokens,
                       SUM(total_cost) as total_cost_usd,
                       AVG(duration_ms) as avg_duration_ms,
                       SUM(error_count) as total_errors
                FROM traces WHERE {where}""",
            params,
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    def breakdown(
        self,
        *,
        group_by: str = "agent_name",
        since: str | None = None,
    ) -> list[dict]:
        """Cost grouped by dimension.

        Args:
            group_by: "agent_name", "environment", or "session_id".
            since: Time window, e.g. "7d".
        """
        self._client._log_query(
            "cost",
            "breakdown",
            {
                "group_by": group_by,
                "since": since,
            },
        )
        valid = {"agent_name", "environment", "session_id"}
        col = group_by if group_by in valid else "agent_name"
        conn = self._store._get_conn()
        conditions = ["1=1"]
        params: list = []
        if since:
            conditions.append("started_at >= ?")
            params.append(_parse_time(since).isoformat())
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""SELECT {col} as grp,
                       SUM(total_tokens) as tokens,
                       SUM(total_cost) as cost,
                       COUNT(*) as trace_count,
                       AVG(duration_ms) as avg_duration_ms,
                       SUM(error_count) as total_errors
                FROM traces
                WHERE {where}
                GROUP BY {col}
                ORDER BY cost DESC""",
            params,
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ── AgentsResource ─────────────────────────────────────────────────────


class AgentsResource:
    """Query agent metadata, health, and usage."""

    def __init__(self, client: TelemetrySDKClient) -> None:
        self._client = client
        self._store = client._store

    def list(self) -> list[dict]:
        """List all unique agents with summary stats."""
        self._client._log_query("agents", "list", {})
        conn = self._store._get_conn()
        rows = conn.execute(
            """SELECT agent_name,
                      COUNT(*) as trace_count,
                      SUM(total_cost) as total_cost_usd,
                      AVG(duration_ms) as avg_duration_ms,
                      SUM(error_count) as total_errors,
                      MAX(started_at) as last_seen
               FROM traces
               GROUP BY agent_name
               ORDER BY last_seen DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get(self, slug: str) -> dict | None:
        """Get summary stats for a specific agent."""
        self._client._log_query("agents", "get", {"slug": slug})
        s = self._store.stats(agent_name=slug)
        return s if s and s.get("total_traces", 0) > 0 else None

    def health(self, slug: str) -> dict:
        """Health check for an agent: last seen, error rate, recent status.

        Returns dict with health indicators.  Raises ValueError if no data.
        """
        self._client._log_query("agents", "health", {"slug": slug})
        s = self._store.stats(agent_name=slug)
        if not s or s.get("total_traces", 0) == 0:
            return {"agent": slug, "status": "unknown", "reason": "no data"}

        error_rate = s.get("error_rate", 0) or 0
        if error_rate > 0.1:
            status = "degraded"
        elif error_rate > 0.05:
            status = "warn"
        else:
            status = "healthy"

        return {
            "agent": slug,
            "status": status,
            "error_rate": error_rate,
            "total_traces": s["total_traces"],
            "total_errors": s["total_errors"],
            "avg_duration_ms": s.get("avg_duration_ms", 0),
            "total_cost_usd": s.get("total_cost_usd", 0),
        }

    def usage(
        self,
        slug: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> dict:
        """Usage statistics for an agent over a time window.

        Args:
            slug: Agent name.
            since: Start of window, e.g. "24h", "7d".
            until: End of window.
        """
        self._client._log_query(
            "agents",
            "usage",
            {
                "slug": slug,
                "since": since,
                "until": until,
            },
        )
        return self._store.stats(
            agent_name=slug,
            start_after=_parse_time(since),
            start_before=_parse_time(until),
        )


# ── AlertsResource ─────────────────────────────────────────────────────


class AlertsResource:
    """Manage alert rules and check conditions."""

    def __init__(self, client: TelemetrySDKClient) -> None:
        self._client = client
        self._store = client._store
        self._alerts_path = client._store_root / "alerts.yaml"

    def _load_alerts(self) -> list[dict]:
        if not self._alerts_path.exists():
            return []
        import yaml

        raw = self._alerts_path.read_text()
        if not raw.strip():
            return []
        data = yaml.safe_load(raw) or []
        return data if isinstance(data, list) else []

    def _save_alerts(self, alerts: list[dict]) -> None:
        import yaml

        self._alerts_path.write_text(yaml.dump(alerts, sort_keys=False, default_flow_style=False))

    def list(self) -> list[dict]:
        """List all configured alert rules."""
        self._client._log_query("alerts", "list", {})
        return self._load_alerts()

    def configure(
        self,
        name: str,
        threshold: str,
        action: str,
        *,
        agent: str | None = None,
    ) -> dict:
        """Create or update an alert rule.

        Args:
            name: Alert rule name.
            threshold: Condition expression, e.g. "error_rate > 0.05".
            action: What to do on trigger, e.g. "slack", "discord", "log".
            agent: Optional agent name to scope the alert.
        """
        self._client._log_query(
            "alerts",
            "configure",
            {
                "name": name,
                "threshold": threshold,
                "action": action,
                "agent": agent,
            },
        )
        alerts = self._load_alerts()
        existing = None
        for a in alerts:
            if a["name"] == name:
                existing = a
                break
        rule = {
            "name": name,
            "threshold": threshold,
            "action": action,
            "agent": agent,
            "silenced": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if existing:
            existing.update(rule)
        else:
            rule["created_at"] = rule["updated_at"]
            alerts.append(rule)
        self._save_alerts(alerts)
        return rule

    def silence(self, alert_id: str) -> dict:
        """Silence an alert rule by name.

        Args:
            alert_id: Name of the alert rule to silence.
        """
        self._client._log_query("alerts", "silence", {"alert_id": alert_id})
        alerts = self._load_alerts()
        for a in alerts:
            if a["name"] == alert_id:
                a["silenced"] = True
                a["silenced_at"] = datetime.now(timezone.utc).isoformat()
                self._save_alerts(alerts)
                return a
        raise ValueError(f"Alert rule '{alert_id}' not found")


# ── AsyncTelemetrySDKClient ──────────────────────────────────────────────


class AsyncTelemetrySDKClient:
    """Async mirror of TelemetrySDKClient.

    Same interface, all methods async. Uses asyncio.to_thread under the hood.
    """

    def __init__(self, **kwargs: Any) -> None:

        self._sync = TelemetrySDKClient(**kwargs)
        self.store_dir = self._sync.store_dir

    def __repr__(self) -> str:
        return f"AsyncTelemetrySDKClient(store_dir={self._sync._store.root})"

    @cached_property
    def traces(self) -> AsyncTracesResource:
        return AsyncTracesResource(self._sync.traces)

    @cached_property
    def cost(self) -> AsyncCostResource:
        return AsyncCostResource(self._sync.cost)

    @cached_property
    def agents(self) -> AsyncAgentsResource:
        return AsyncAgentsResource(self._sync.agents)

    @cached_property
    def alerts(self) -> AsyncAlertsResource:
        return AsyncAlertsResource(self._sync.alerts)


class AsyncTracesResource:
    """Async mirror of TracesResource."""

    def __init__(self, sync: TracesResource) -> None:

        self._sync = sync

    async def search(self, **kwargs: Any) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self._sync.search, **kwargs)

    async def get(self, trace_id: str) -> dict | None:
        import asyncio

        return await asyncio.to_thread(self._sync.get, trace_id)

    async def errors(self, **kwargs: Any) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self._sync.errors, **kwargs)


class AsyncCostResource:
    """Async mirror of CostResource."""

    def __init__(self, sync: CostResource) -> None:
        self._sync = sync

    async def by_agent(self, agent: str, **kwargs: Any) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self._sync.by_agent, agent, **kwargs)

    async def total(self, **kwargs: Any) -> dict:
        import asyncio

        return await asyncio.to_thread(self._sync.total, **kwargs)

    async def breakdown(self, **kwargs: Any) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self._sync.breakdown, **kwargs)


class AsyncAgentsResource:
    """Async mirror of AgentsResource."""

    def __init__(self, sync: AgentsResource) -> None:
        self._sync = sync

    async def list(self) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self._sync.list)

    async def get(self, slug: str) -> dict | None:
        import asyncio

        return await asyncio.to_thread(self._sync.get, slug)

    async def health(self, slug: str) -> dict:
        import asyncio

        return await asyncio.to_thread(self._sync.health, slug)

    async def usage(self, slug: str, **kwargs: Any) -> dict:
        import asyncio

        return await asyncio.to_thread(self._sync.usage, slug, **kwargs)


class AsyncAlertsResource:
    """Async mirror of AlertsResource."""

    def __init__(self, sync: AlertsResource) -> None:
        self._sync = sync

    async def list(self) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self._sync.list)

    async def configure(self, name: str, threshold: str, action: str, **kwargs: Any) -> dict:
        import asyncio

        return await asyncio.to_thread(self._sync.configure, name, threshold, action, **kwargs)

    async def silence(self, alert_id: str) -> dict:
        import asyncio

        return await asyncio.to_thread(self._sync.silence, alert_id)
