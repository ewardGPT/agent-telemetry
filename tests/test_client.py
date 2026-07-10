"""Tests for the TelemetrySDKClient SDK."""

from agent_telemetry.client import AsyncTelemetrySDKClient, TelemetrySDKClient


class TestTelemetryClient:
    def test_instantiation(self):
        c = TelemetrySDKClient(store_dir="/tmp/ci_telemetry_test")
        assert hasattr(c, "traces")
        assert hasattr(c, "cost")
        assert hasattr(c, "agents")
        assert hasattr(c, "alerts")

    def test_search_traces(self):
        c = TelemetrySDKClient(store_dir="/tmp/ci_telemetry_test")
        traces = c.traces.search(last="24h")
        assert isinstance(traces, list)

    def test_cost_total(self):
        c = TelemetrySDKClient(store_dir="/tmp/ci_telemetry_test")
        cost = c.cost.total()
        assert isinstance(cost, (int, float, dict))

    def test_agents_list(self):
        c = TelemetrySDKClient(store_dir="/tmp/ci_telemetry_test")
        agents = c.agents.list()
        assert isinstance(agents, list)

    def test_async(self):
        ac = AsyncTelemetrySDKClient(store_dir="/tmp/ci_telemetry_test")
        assert ac.traces is not None
