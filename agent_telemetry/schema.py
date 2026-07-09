"""Core schema for agent telemetry traces and spans.

OpenTelemetry-compatible but local-first.  No cloud dependency — everything
stores to SQLite + JSONL on local disk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid4().hex[:16]


class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class SpanKind(str, Enum):
    TOOL = "tool"
    LLM = "llm"
    AGENT = "agent"
    WORKFLOW = "workflow"
    HTTP = "http"


class SpanEvent:
    """A timestamped event within a span."""

    name: str
    timestamp: datetime
    attributes: dict

    def __init__(
        self,
        name: str,
        timestamp: datetime | None = None,
        attributes: dict | None = None,
    ) -> None:
        self.name = name
        self.timestamp = timestamp or _now()
        self.attributes = attributes or {}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
            "attributes": self.attributes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SpanEvent:
        return cls(
            name=d["name"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            attributes=d.get("attributes", {}),
        )


class Span:
    """A single span — one unit of work in a trace.

    Each span represents a distinct action: a tool call, an LLM inference,
    or an agent decision point.
    """

    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    kind: SpanKind
    start_time: datetime
    end_time: datetime | None
    status: SpanStatus
    attributes: dict
    events: list[SpanEvent]

    def __init__(
        self,
        name: str,
        kind: SpanKind = SpanKind.TOOL,
        parent_id: str | None = None,
        trace_id: str | None = None,
        attributes: dict | None = None,
    ) -> None:
        self.trace_id = trace_id or _new_id()
        self.span_id = _new_id()
        self.parent_id = parent_id
        self.name = name
        self.kind = kind
        self.start_time = _now()
        self.end_time = None
        self.status = SpanStatus.OK
        self.attributes = attributes or {}
        self.events = []

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        self.events.append(SpanEvent(name=name, attributes=attributes))

    def finish(self, status: SpanStatus = SpanStatus.OK) -> None:
        self.end_time = _now()
        self.status = status

    def fail(self, error: str) -> None:
        self.finish(SpanStatus.ERROR)
        self.attributes["error"] = error

    def duration_ms(self) -> float:
        if not self.end_time:
            return 0
        return (self.end_time - self.start_time).total_seconds() * 1000

    def has_error(self) -> bool:
        return self.status in (SpanStatus.ERROR, SpanStatus.TIMEOUT)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status.value,
            "duration_ms": self.duration_ms(),
            "attributes": self.attributes,
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Span:
        s = cls(
            name=d["name"],
            kind=SpanKind(d["kind"]),
            parent_id=d.get("parent_id"),
            trace_id=d.get("trace_id", _new_id()),
            attributes=d.get("attributes", {}),
        )
        s.span_id = d["span_id"]
        s.start_time = datetime.fromisoformat(d["start_time"])
        s.end_time = datetime.fromisoformat(d["end_time"]) if d.get("end_time") else None
        s.status = SpanStatus(d["status"])
        s.events = [SpanEvent.from_dict(e) for e in d.get("events", [])]
        return s


class Trace:
    """A complete trace — collection of spans for one agent invocation.

    Traces are the unit of query.  You search traces, not individual spans.
    """

    trace_id: str
    spans: list[Span]
    agent_name: str
    agent_version: str | None
    environment: str
    session_id: str | None
    started_at: datetime
    finished_at: datetime | None

    def __init__(
        self,
        agent_name: str,
        environment: str = "production",
        agent_version: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.trace_id = trace_id or _new_id()
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.environment = environment
        self.session_id = session_id
        self.started_at = _now()
        self.finished_at = None
        self.spans = []

    def start_span(self, name: str, kind: SpanKind = SpanKind.TOOL, **attrs) -> Span:
        span = Span(name=name, kind=kind, trace_id=self.trace_id, attributes=attrs)
        self.spans.append(span)
        return span

    def finish(self) -> None:
        self.finished_at = _now()
        for s in self.spans:
            if not s.end_time:
                s.finish()

    def duration_ms(self) -> float:
        if not self.finished_at:
            return 0
        return (self.finished_at - self.started_at).total_seconds() * 1000

    def error_count(self) -> int:
        return sum(1 for s in self.spans if s.has_error())

    def total_tokens(self) -> int:
        total = 0
        for s in self.spans:
            for k in ("tokens_in", "tokens_out", "total_tokens"):
                total += int(s.attributes.get(k, 0))
        return total

    def total_cost(self) -> float:
        """Sum cost_usd across all spans."""
        return sum(float(s.attributes.get("cost_usd", 0)) for s in self.spans)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "environment": self.environment,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms(),
            "span_count": len(self.spans),
            "error_count": self.error_count(),
            "total_tokens": self.total_tokens(),
            "total_cost": self.total_cost(),
            "spans": [s.to_dict() for s in self.spans],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Trace:
        t = cls(
            agent_name=d["agent_name"],
            environment=d.get("environment", "production"),
            agent_version=d.get("agent_version"),
            session_id=d.get("session_id"),
            trace_id=d.get("trace_id"),
        )
        t.started_at = datetime.fromisoformat(d["started_at"])
        t.finished_at = datetime.fromisoformat(d["finished_at"]) if d.get("finished_at") else None
        t.spans = [Span.from_dict(s) for s in d.get("spans", [])]
        return t
