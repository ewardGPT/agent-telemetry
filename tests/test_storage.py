"""Storage tests."""

from __future__ import annotations

import tempfile

import pytest

from agent_telemetry.schema import SpanKind, Trace
from agent_telemetry.storage import TelemetryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as td:
        yield TelemetryStore(root=td)


class TestTelemetryStore:
    def test_store_and_search(self, store):
        t = Trace(agent_name="test-agent", environment="production")
        t.start_span("tool1", kind=SpanKind.TOOL).finish()
        t.finish()
        store.store(t)

        results = store.search(agent_name="test-agent")
        assert len(results) == 1
        assert results[0]["agent_name"] == "test-agent"
        assert results[0]["span_count"] == 1

    def test_search_by_error(self, store):
        t = Trace(agent_name="bad-agent")
        span = t.start_span("fails", kind=SpanKind.TOOL)
        span.fail("oops")
        store.store(t)

        results = store.search(agent_name="bad-agent", error=True)
        assert len(results) == 1
        assert results[0]["error_count"] == 1

    def test_search_no_errors(self, store):
        t = Trace(agent_name="good-agent")
        t.start_span("works", kind=SpanKind.TOOL).finish()
        store.store(t)

        results = store.search(agent_name="good-agent", error=True)
        assert len(results) == 0

    def test_cost_report(self, store):
        t = Trace(agent_name="costly")
        t.start_span("infer", kind=SpanKind.LLM, tokens_in=100, cost_usd=0.01).finish()
        t.start_span("infer2", kind=SpanKind.LLM, tokens_in=50, cost_usd=0.005).finish()
        store.store(t)

        results = store.cost_report(agent_name="costly")
        assert len(results) == 1
        assert results[0]["cost"] == 0.015

    def test_stats(self, store):
        for _i in range(3):
            t = Trace(agent_name="stat-agent")
            t.start_span("work", kind=SpanKind.TOOL).finish()
            store.store(t)

        s = store.stats(agent_name="stat-agent")
        assert s["total_traces"] == 3

    def test_error_summary(self, store):
        t = Trace(agent_name="err-agent")
        span = t.start_span("bad", kind=SpanKind.TOOL)
        span.fail("connection error")
        store.store(t)

        errors = store.error_summary(agent_name="err-agent")
        assert len(errors) == 1
