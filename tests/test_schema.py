"""Schema tests."""

from __future__ import annotations

import pytest

from agent_telemetry.schema import Span, SpanKind, SpanStatus, Trace


class TestSpan:
    def test_lifecycle(self):
        s = Span(name="read_inbox", kind=SpanKind.TOOL)
        assert s.status == SpanStatus.OK
        assert s.end_time is None
        assert s.duration_ms() == 0

        s.finish()
        assert s.end_time is not None
        assert s.duration_ms() > 0

    def test_fail(self):
        s = Span(name="risky", kind=SpanKind.TOOL)
        s.fail("connection refused")
        assert s.status == SpanStatus.ERROR
        assert s.attributes["error"] == "connection refused"

    def test_events(self):
        s = Span(name="enrich", kind=SpanKind.TOOL)
        s.add_event("api_call_started", {"url": "https://api.example.com"})
        assert len(s.events) == 1
        assert s.events[0].name == "api_call_started"

    def test_serialization_roundtrip(self):
        s = Span(name="test", kind=SpanKind.LLM, attributes={"tokens": 150})
        s.add_event("start")
        s.finish()
        d = s.to_dict()
        restored = Span.from_dict(d)
        assert restored.name == s.name
        assert restored.trace_id == s.trace_id
        assert restored.attributes["tokens"] == 150
        assert len(restored.events) == 1


class TestTrace:
    def test_lifecycle(self):
        t = Trace(agent_name="test-agent", environment="staging")
        assert t.agent_name == "test-agent"
        assert t.environment == "staging"
        assert len(t.spans) == 0

        t.start_span("tool1", kind=SpanKind.TOOL)
        assert len(t.spans) == 1

        t.finish()
        assert t.finished_at is not None

    def test_error_count(self):
        t = Trace(agent_name="test")
        span = t.start_span("good")
        span.finish()
        span2 = t.start_span("bad")
        span2.fail("oops")
        assert t.error_count() == 1

    def test_tokens_and_cost(self):
        t = Trace(agent_name="test")
        span = t.start_span(
            "infer", kind=SpanKind.LLM, tokens_in=100, tokens_out=50, cost_usd=0.0015
        )
        span.finish()
        span2 = t.start_span(
            "infer2", kind=SpanKind.LLM, tokens_in=200, total_tokens=300, cost_usd=0.003
        )
        span2.finish()
        assert t.total_tokens() == 650  # 100 + 50 + 200 + 300
        assert t.total_cost() == pytest.approx(0.0045)

    def test_serialization_roundtrip(self):
        t = Trace(agent_name="test", environment="production", session_id="sess-1")
        t.start_span("tool1", kind=SpanKind.TOOL).finish()
        t.finish()
        d = t.to_dict()
        restored = Trace.from_dict(d)
        assert restored.agent_name == "test"
        assert restored.environment == "production"
        assert restored.session_id == "sess-1"
        assert len(restored.spans) == 1
