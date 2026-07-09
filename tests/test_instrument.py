"""Instrumentation tests."""

from __future__ import annotations

import pytest

from agent_telemetry.instrument import TelemetryClient, instrument, trace_tool
from agent_telemetry.schema import SpanKind, Trace


class TestTelemetryClient:
    def test_trace_context(self):
        client = TelemetryClient("test-agent")
        spans = []

        with client.trace(session_id="sess-1") as t:
            assert t.agent_name == "test-agent"
            assert t.session_id == "sess-1"
            s = t.start_span("step1")
            s.finish()
            spans.append(s)

        assert t.finished_at is not None
        assert len(spans) == 1

    def test_span_context(self):
        client = TelemetryClient("test-agent")
        spans = []

        with client.trace(), client.span("sub_step", kind=SpanKind.TOOL) as s:
            spans.append(s)

        assert len(spans) == 1
        assert spans[0].end_time is not None

    def test_span_missing_trace(self):
        client = TelemetryClient("test-agent")
        with pytest.raises(RuntimeError, match="No active trace"), client.span("orphan"):
            pass

    def test_trace_on_exception(self):
        client = TelemetryClient("test-agent")
        with pytest.raises(ValueError), client.trace():
            s = client.current_trace.start_span("doomed")
            raise ValueError("boom")
        assert s.status.value == "error"

    def test_instrument_decorator(self):
        client = TelemetryClient("test-agent")

        @instrument(client, kind=SpanKind.TOOL)
        def my_tool(x: int) -> int:
            return x * 2

        trace_ref: Trace | None = None
        with client.trace() as t:
            trace_ref = t
            result = my_tool(5)

        assert result == 10
        assert len(trace_ref.spans) == 1

    def test_instrument_no_trace_passthrough(self):
        client = TelemetryClient("test-agent")

        @instrument(client)
        def my_tool(x: int) -> int:
            return x + 1

        result = my_tool(5)
        assert result == 6  # passthrough when no trace active


class TestTraceTool:
    def test_standalone_decorator(self):
        @trace_tool("quick_lookup")
        def lookup(key: str) -> str:
            return f"value:{key}"

        result = lookup("test")
        assert result == "value:test"
