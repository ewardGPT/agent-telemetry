"""CLI tests."""

from __future__ import annotations

import tempfile

import pytest
from typer.testing import CliRunner

from agent_telemetry.cli import app
from agent_telemetry.schema import SpanKind, Trace
from agent_telemetry.storage import TelemetryStore


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def store_dir():
    with tempfile.TemporaryDirectory() as td:
        # Seed with test data
        store = TelemetryStore(root=td)
        for i in range(5):
            t = Trace(agent_name="test-agent", environment="production")
            t.start_span("tool1", kind=SpanKind.TOOL, tokens_in=100).finish()
            if i % 2 == 0:
                span = t.start_span("bad", kind=SpanKind.TOOL)
                span.fail("error")
            store.store(t)
        yield td


class TestSearch:
    def test_search_empty(self, runner):
        with tempfile.TemporaryDirectory() as td:
            result = runner.invoke(app, ["search"], env={"TELEMETRY_DIR": td})
            assert result.exit_code == 0
            assert "No matching" in result.stdout

    def test_search_by_agent(self, runner, store_dir):
        result = runner.invoke(
            app, ["search", "--agent", "test-agent"], env={"TELEMETRY_DIR": store_dir}
        )
        assert result.exit_code == 0
        assert "test-agent" in result.stdout


class TestCost:
    def test_cost_report(self, runner, store_dir):
        result = runner.invoke(app, ["cost", "test-agent"], env={"TELEMETRY_DIR": store_dir})
        assert result.exit_code == 0


class TestErrors:
    def test_errors(self, runner, store_dir):
        result = runner.invoke(
            app, ["errors", "--agent", "test-agent"], env={"TELEMETRY_DIR": store_dir}
        )
        assert result.exit_code == 0


class TestStats:
    def test_stats(self, runner, store_dir):
        result = runner.invoke(app, ["stats", "test-agent"], env={"TELEMETRY_DIR": store_dir})
        assert result.exit_code == 0
        assert "total_traces" in result.stdout.lower() or "Total Traces" in result.stdout


class TestAlert:
    def test_alert_triggered(self, runner, store_dir):
        result = runner.invoke(
            app,
            ["alert", "total_traces > 0", "--agent", "test-agent"],
            env={"TELEMETRY_DIR": store_dir},
        )
        assert result.exit_code == 1

    def test_alert_ok(self, runner, store_dir):
        result = runner.invoke(
            app,
            ["alert", "total_traces > 999999", "--agent", "test-agent"],
            env={"TELEMETRY_DIR": store_dir},
        )
        assert result.exit_code == 0


class TestReplay:
    def test_replay_not_found(self, runner, store_dir):
        result = runner.invoke(app, ["replay", "nonexistent"], env={"TELEMETRY_DIR": store_dir})
        assert result.exit_code == 0
        assert "not found" in result.stdout
