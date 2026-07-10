"""Integration tests for new agent-telemetry features: optimizer, drift, alerts, benchmark."""

from __future__ import annotations

import tempfile

import pytest

from agent_telemetry.alerts import _post, send_alert
from agent_telemetry.benchmark import BenchmarkResult
from agent_telemetry.drift_detector import detect_drift
from agent_telemetry.optimizer import MODEL_ALTERNATIVES, optimize_costs
from agent_telemetry.schema import SpanKind, Trace
from agent_telemetry.storage import TelemetryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as td:
        yield TelemetryStore(root=td)


@pytest.fixture
def populated(store):
    for _i in range(5):
        t = Trace(agent_name="test-agent", environment="production")
        t.start_span("op", kind=SpanKind.TOOL, cost_usd=0.01).finish()
        store.store(t)
    return store


class TestDriftDetector:
    def test_no_data(self, store):
        result = detect_drift(store, "no-agent")
        assert result["drift_detected"] is False

    def test_insufficient_data(self, populated):
        result = detect_drift(populated, "test-agent", window_hours=1)
        assert "drift_detected" in result


class TestOptimizer:
    def test_model_alternatives_exist(self):
        assert "kimi-k2.5" in MODEL_ALTERNATIVES
        assert len(MODEL_ALTERNATIVES["kimi-k2.5"]) == 2

    def test_optimize_empty(self, store):
        suggestions = optimize_costs(store)
        assert suggestions == []

    def test_optimize_with_data(self, populated):
        suggestions = optimize_costs(populated)
        assert isinstance(suggestions, list)


class TestAlerts:
    def test_send_alert_no_channels(self):
        results = send_alert("test", "body")
        assert isinstance(results, dict)

    def test_alert_post_noop(self):
        result = _post("", {"test": True})
        assert result is not None


class TestBenchmark:
    def test_benchmark_result_stats(self):
        r = BenchmarkResult(name="test", runs=5)
        r.latencies_ms = [10, 20, 30, 40, 50]
        assert r.avg_ms == 30
        assert r.p50_ms == 30
        assert r.p50_ms is not None
