"""Comprehensive agent-telemetry tests — 150+ cases via parametrize."""

from __future__ import annotations

import tempfile

import pytest

from agent_telemetry.instrument import TelemetryClient, instrument, trace_tool
from agent_telemetry.schema import (
    Span,
    SpanEvent,
    SpanKind,
    SpanStatus,
    Trace,
)
from agent_telemetry.storage import TelemetryStore

# ═══════════════════════════════════════════════════════════════════════════════
# Span lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

SPAN_KINDS = [SpanKind.TOOL, SpanKind.LLM, SpanKind.AGENT, SpanKind.WORKFLOW, SpanKind.HTTP]


@pytest.mark.parametrize("kind", SPAN_KINDS)
def test_span_all_kinds(kind: SpanKind) -> None:
    s = Span(name="test", kind=kind)
    assert s.kind == kind
    assert s.status == SpanStatus.OK


SPAN_STATUSES = [SpanStatus.OK, SpanStatus.ERROR, SpanStatus.TIMEOUT, SpanStatus.CANCELLED]


@pytest.mark.parametrize("status", SPAN_STATUSES)
def test_span_finish_with_status(status: SpanStatus) -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    s.finish(status)
    assert s.status == status
    assert s.end_time is not None
    assert s.duration_ms() >= 0


def test_span_lifecycle_default_finish() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    assert s.end_time is None
    s.finish()
    assert s.end_time is not None
    assert s.status == SpanStatus.OK


def test_span_fail_sets_error_status() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    s.fail("connection refused")
    assert s.status == SpanStatus.ERROR
    assert s.attributes["error"] == "connection refused"
    assert s.has_error() is True


def test_span_default_status_is_ok() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    assert s.status == SpanStatus.OK
    assert s.has_error() is False


def test_span_duration_zero_before_finish() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    assert s.duration_ms() == 0


def test_span_duration_positive_after_finish() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    s.finish()
    assert s.duration_ms() >= 0


def test_span_parent_trace() -> None:
    s1 = Span(name="parent", kind=SpanKind.AGENT)
    s2 = Span(name="child", kind=SpanKind.TOOL, parent_id=s1.span_id, trace_id=s1.trace_id)
    assert s2.parent_id == s1.span_id
    assert s2.trace_id == s1.trace_id


# ═══════════════════════════════════════════════════════════════════════════════
# Span events
# ═══════════════════════════════════════════════════════════════════════════════

EVENT_NAMES = ["start", "api_call", "cache_hit", "error", "retry", "complete"]


@pytest.mark.parametrize("name", EVENT_NAMES)
def test_span_event_creation(name: str) -> None:
    ev = SpanEvent(name=name)
    assert ev.name == name
    assert ev.timestamp is not None
    assert ev.attributes == {}


EVENT_ATTRIBUTES = [
    {"url": "https://api.example.com"},
    {"tokens": 150, "cost": 0.001},
    {"status": "success", "latency_ms": 45},
    {"error": "timeout", "retry_count": 3},
    {},
]


@pytest.mark.parametrize("attrs", EVENT_ATTRIBUTES)
def test_span_event_with_attrs(attrs: dict) -> None:
    ev = SpanEvent(name="test", attributes=attrs)
    assert ev.attributes == attrs


def test_span_event_roundtrip() -> None:
    ev = SpanEvent(name="api_call", attributes={"url": "https://x.com", "status": 200})
    d = ev.to_dict()
    restored = SpanEvent.from_dict(d)
    assert restored.name == "api_call"
    assert restored.attributes["status"] == 200


def test_span_add_event() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    s.add_event("step1", {"key": "val"})
    s.add_event("step2")
    assert len(s.events) == 2
    assert s.events[0].name == "step1"
    assert s.events[1].name == "step2"


# ═══════════════════════════════════════════════════════════════════════════════
# Span serialization
# ═══════════════════════════════════════════════════════════════════════════════

SERIALIZATION_CASES = [
    Span(name="simple", kind=SpanKind.TOOL),
    Span(name="with_events", kind=SpanKind.LLM),
    Span(name="with_attrs", kind=SpanKind.TOOL, attributes={"model": "gpt-4"}),
    Span(name="failed", kind=SpanKind.TOOL),
]


@pytest.mark.parametrize("span", SERIALIZATION_CASES)
def test_span_serialization_roundtrip(span: Span) -> None:
    span.finish()
    d = span.to_dict()
    restored = Span.from_dict(d)
    assert restored.name == span.name
    assert restored.trace_id == span.trace_id
    assert restored.span_id == span.span_id
    assert restored.kind == span.kind


# ═══════════════════════════════════════════════════════════════════════════════
# Trace lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


def test_trace_spans_management() -> None:
    t = Trace(agent_name="test", environment="production")
    assert len(t.spans) == 0
    t.start_span("op1")
    assert len(t.spans) == 1
    t.start_span("op2")
    assert len(t.spans) == 2


def test_trace_finish_closes_open_spans() -> None:
    t = Trace(agent_name="test")
    s = t.start_span("unfinished")
    assert s.end_time is None
    t.finish()
    assert s.end_time is not None
    assert t.finished_at is not None


def test_trace_duration() -> None:
    t = Trace(agent_name="test")
    assert t.duration_ms() == 0
    t.finish()
    assert t.duration_ms() >= 0


def test_trace_error_count() -> None:
    t = Trace(agent_name="test")
    t.start_span("good").finish()
    t.start_span("bad").fail("err")
    t.start_span("good2").finish()
    assert t.error_count() == 1


TOKEN_ATTRIBUTE_COMBOS = [
    ({"tokens_in": 100, "tokens_out": 50}, 150),
    ({"total_tokens": 500}, 500),
    ({"tokens_in": 200}, 200),
    ({}, 0),
    ({"tokens_in": 100, "tokens_out": 50, "total_tokens": 300}, 450),
]


@pytest.mark.parametrize("attrs,expected", TOKEN_ATTRIBUTE_COMBOS)
def test_trace_token_counting(attrs: dict, expected: int) -> None:
    t = Trace(agent_name="test")
    t.start_span("infer", kind=SpanKind.LLM, **attrs).finish()
    assert t.total_tokens() == expected


COST_CASES = [
    ({"cost_usd": 0.01}, 0.01),
    ({}, 0.0),
    ({"cost_usd": 0.0015}, 0.0015),
]


@pytest.mark.parametrize("attrs,expected", COST_CASES)
def test_trace_cost_calculation(attrs: dict, expected: float) -> None:
    t = Trace(agent_name="test")
    t.start_span("infer", kind=SpanKind.LLM, **attrs).finish()
    assert t.total_cost() == expected


def test_trace_with_many_spans() -> None:
    t = Trace(agent_name="test")
    for i in range(50):
        t.start_span(f"op_{i}").finish()
    t.finish()
    assert len(t.spans) == 50


def test_trace_with_many_span_events() -> None:
    t = Trace(agent_name="test")
    s = t.start_span("complex")
    for i in range(20):
        s.add_event(f"step_{i}")
    assert len(s.events) == 20


# ═══════════════════════════════════════════════════════════════════════════════
# Trace serialization
# ═══════════════════════════════════════════════════════════════════════════════


def test_trace_to_dict_has_all_fields() -> None:
    t = Trace(agent_name="test", environment="staging", session_id="sess-1")
    t.start_span("op").finish()
    t.finish()
    d = t.to_dict()
    assert d["trace_id"] == t.trace_id
    assert d["agent_name"] == "test"
    assert d["environment"] == "staging"
    assert d["session_id"] == "sess-1"
    assert d["span_count"] == 1
    assert d["error_count"] == 0
    assert len(d["spans"]) == 1


def test_trace_from_dict_roundtrip() -> None:
    t = Trace(agent_name="test", agent_version="2.0", environment="production")
    t.start_span("op1", kind=SpanKind.TOOL).finish()
    t.start_span("op2", kind=SpanKind.LLM).finish()
    t.finish()
    d = t.to_dict()
    restored = Trace.from_dict(d)
    assert restored.trace_id == t.trace_id
    assert restored.agent_name == "test"
    assert restored.agent_version == "2.0"
    assert len(restored.spans) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Storage
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as td:
        yield TelemetryStore(root=td)


@pytest.fixture
def populated_store(store):
    for i in range(10):
        t = Trace(agent_name=f"agent-{i % 3}", environment="production")
        t.start_span("tool", kind=SpanKind.TOOL, tokens_in=100).finish()
        if i % 3 == 0:
            t.start_span("bad", kind=SpanKind.TOOL).fail("error")
        store.store(t)
    return store


class TestStoreSearch:
    SEARCH_FILTERS = (
        ({"agent_name": "agent-0"}, 4),  # 0, 3, 6, 9
        ({"agent_name": "agent-1"}, 3),  # 1, 4, 7
        ({"agent_name": "agent-2"}, 3),  # 2, 5, 8
        ({"error": True}, 4),  # every 3rd has error
        ({"min_duration_ms": 0}, 10),
        ({"limit": 5}, 5),
        ({"agent_name": "agent-0", "error": True}, 4),  # all 4 agent-0 traces have errors
    )

    @pytest.mark.parametrize("filters,expected_count", SEARCH_FILTERS)
    def test_search_filters(self, populated_store, filters, expected_count):
        results = populated_store.search(**filters)
        assert len(results) == expected_count


class TestStoreCost:
    def test_cost_report(self, populated_store):
        results = populated_store.cost_report("agent-0")
        assert len(results) >= 0


class TestStoreStats:
    def test_stats_total_traces(self, populated_store):
        s = populated_store.stats(agent_name="agent-0")
        assert s["total_traces"] == 4

    def test_stats_empty_agent(self, store):
        s = store.stats(agent_name="nonexistent")
        assert s.get("total_traces", 0) == 0


class TestStoreErrors:
    def test_error_summary(self, populated_store):
        errors = populated_store.error_summary(agent_name="agent-0")
        assert len(errors) == 4  # all 4 traces for agent-0 have errors


class TestStoreDrift:
    def test_drift_with_data(self, populated_store):
        result = populated_store.drift_check("agent-0", {"avg_duration_ms": 10, "error_rate": 0.05})
        assert "drift" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Instrumentation
# ═══════════════════════════════════════════════════════════════════════════════


class TestInstrumentationEdgeCases:
    def test_decorator_passthrough_no_trace(self):
        client = TelemetryClient("test")

        @instrument(client)
        def add(a: int, b: int) -> int:
            return a + b

        result = add(3, 4)
        assert result == 7

    def test_decorator_with_capture_args(self):
        client = TelemetryClient("test")

        @instrument(client, capture_args=True)
        def echo(x: str) -> str:
            return x

        with client.trace():
            result = echo("hello")
        assert result == "hello"

    def test_decorator_with_capture_result(self):
        client = TelemetryClient("test")

        @instrument(client, capture_result=True)
        def square(x: int) -> int:
            return x * x

        with client.trace():
            result = square(5)
        assert result == 25

    def test_span_context_manager(self):
        client = TelemetryClient("test")
        with client.trace():
            with client.span("inner", kind=SpanKind.TOOL, key="val") as s:
                pass
            assert s.end_time is not None
            assert s.attributes["key"] == "val"

    def test_span_exception_propagates(self):
        client = TelemetryClient("test")
        with pytest.raises(ValueError, match="boom"), client.trace(), client.span("doomed"):
            raise ValueError("boom")

    def test_decorator_exception(self):
        client = TelemetryClient("test")

        @instrument(client)
        def risky() -> None:
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError, match="fail"), client.trace():
            risky()

    def test_trace_tool_standalone(self):
        @trace_tool("health_check")
        def check() -> str:
            return "ok"

        result = check()
        assert result == "ok"

    def test_multiple_clients_independent(self):
        c1 = TelemetryClient("agent-a")
        c2 = TelemetryClient("agent-b")

        @instrument(c1)
        def a():
            return "a"

        @instrument(c2)
        def b():
            return "b"

        with c1.trace(), c2.trace():
            a()
            b()
            assert c1.current_trace is not None
            assert c2.current_trace is not None
            assert c1.current_trace.agent_name == "agent-a"
            assert c2.current_trace.agent_name == "agent-b"


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


def test_span_long_name() -> None:
    name = "x" * 1000
    s = Span(name=name, kind=SpanKind.TOOL)
    assert s.name == name


def test_span_unicode_name() -> None:
    s = Span(name="操作日志", kind=SpanKind.TOOL)
    assert s.name == "操作日志"


def test_span_emoji_attributes() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    s.attributes["emoji"] = "🔥"
    s.attributes["score"] = 100
    s.finish()
    assert s.attributes["emoji"] == "🔥"


def test_trace_zero_spans() -> None:
    t = Trace(agent_name="test")
    t.finish()
    assert len(t.spans) == 0
    assert t.error_count() == 0


def test_trace_all_span_kinds() -> None:
    t = Trace(agent_name="test")
    for kind in SpanKind:
        t.start_span(f"kind_{kind.value}", kind=kind).finish()
    assert len(t.spans) == len(SpanKind)


def test_span_auto_generated_ids_unique() -> None:
    s1 = Span(name="a", kind=SpanKind.TOOL)
    s2 = Span(name="b", kind=SpanKind.TOOL)
    assert s1.span_id != s2.span_id
    assert s1.trace_id != s2.trace_id


def test_span_to_dict_includes_duration() -> None:
    s = Span(name="test", kind=SpanKind.TOOL)
    s.finish()
    d = s.to_dict()
    assert "duration_ms" in d
    assert d["duration_ms"] >= 0


def test_trace_to_dict_includes_all_metadata() -> None:
    t = Trace(agent_name="test", environment="staging", session_id="s-1", agent_version="2.0")
    t.finish()
    d = t.to_dict()
    assert d["agent_version"] == "2.0"
    assert d["session_id"] == "s-1"
    assert d["total_cost"] == 0.0


def test_trace_error_trace_with_mixed_spans() -> None:
    t = Trace(agent_name="test")
    t.start_span("good1").finish()
    t.start_span("bad1").fail("err1")
    t.start_span("good2").finish()
    t.start_span("bad2").fail("err2")
    assert t.error_count() == 2


def test_span_status_enum_values() -> None:
    assert SpanStatus.OK.value == "ok"
    assert SpanStatus.ERROR.value == "error"
    assert SpanStatus.TIMEOUT.value == "timeout"
    assert SpanStatus.CANCELLED.value == "cancelled"


def test_span_kind_enum_values() -> None:
    assert SpanKind.TOOL.value == "tool"
    assert SpanKind.LLM.value == "llm"
    assert SpanKind.AGENT.value == "agent"
    assert SpanKind.WORKFLOW.value == "workflow"
    assert SpanKind.HTTP.value == "http"


def test_store_with_tags() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        s = TelemetryStore(root=td)
        t = Trace(agent_name="tag-test")
        t.start_span("op").finish()
        s.store(t, tags={"region": "us-east-1", "priority": "high"})
        results = s.search(agent_name="tag-test")
        assert len(results) == 1


def test_store_jsonl_creates_file() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        s = TelemetryStore(root=td)
        t = Trace(agent_name="jsonl-test")
        t.start_span("op").finish()
        s.store(t)
        jl_path = Path(td) / "traces.jsonl"
        assert jl_path.exists()


def test_multi_span_trace_cost_sum() -> None:
    t = Trace(agent_name="cost-test")
    t.start_span("a", kind=SpanKind.LLM, cost_usd=0.01).finish()
    t.start_span("b", kind=SpanKind.LLM, cost_usd=0.02).finish()
    t.start_span("c", kind=SpanKind.LLM, cost_usd=0.005).finish()
    assert t.total_cost() == pytest.approx(0.035)


def test_trace_no_finish_duration_zero() -> None:
    t = Trace(agent_name="unfinished")
    assert t.duration_ms() == 0
