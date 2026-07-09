"""CLI + storage parametrized tests for agent-telemetry."""

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
def td():
    with tempfile.TemporaryDirectory() as d:
        # Seed diverse traces for CLI testing
        s = TelemetryStore(root=d)
        for i in range(6):
            t = Trace(agent_name=f"agent-{i % 2}", environment="production")
            t.start_span("tool1", kind=SpanKind.TOOL, tokens_in=100, cost_usd=0.001).finish()
            if i % 3 == 0:
                t.start_span("bad_tool", kind=SpanKind.TOOL).fail("timeout")
            if i % 2 == 0:
                t.start_span("infer", kind=SpanKind.LLM, tokens_in=200, cost_usd=0.005).finish()
            s.store(t)
        yield d


# ═══════════════════════════════════════════════════════════════════════════════
# Search CLI
# ═══════════════════════════════════════════════════════════════════════════════

SEARCH_CLI_CASES = [
    (["search", "--agent", "agent-0"], 0),
    (["search", "--agent", "agent-1"], 0),
    (["search", "--error"], 0),
    (["search", "--last", "24h"], 0),
    (["search", "--limit", "3"], 0),
    (["search", "--limit", "10"], 0),
    (["search"], 0),
    (["search", "--agent", "agent-0", "--error"], 0),
    (["search", "--agent", "agent-1", "--limit", "5"], 0),
    (["search", "--limit", "100"], 0),
]


@pytest.mark.parametrize("args,expected_exit", SEARCH_CLI_CASES)
def test_search_variants(runner, td, args, expected_exit):
    result = runner.invoke(app, args, env={"TELEMETRY_DIR": td})
    assert result.exit_code == expected_exit


# ═══════════════════════════════════════════════════════════════════════════════
# Cost CLI
# ═══════════════════════════════════════════════════════════════════════════════

COST_CLI_CASES = [
    (["cost", "agent-0"], 0),
    (["cost", "agent-1"], 0),
    (["cost", "agent-0", "--last", "7d"], 0),
    (["cost", "agent-0", "--group-by", "environment"], 0),
    (["cost", "agent-0", "--group-by", "agent_name"], 0),
]


@pytest.mark.parametrize("args,expected_exit", COST_CLI_CASES)
def test_cost_variants(runner, td, args, expected_exit):
    result = runner.invoke(app, args, env={"TELEMETRY_DIR": td})
    assert result.exit_code == expected_exit


# ═══════════════════════════════════════════════════════════════════════════════
# Errors CLI
# ═══════════════════════════════════════════════════════════════════════════════

ERRORS_CLI_CASES = [
    (["errors"], 0),
    (["errors", "--agent", "agent-0"], 0),
    (["errors", "--last", "48h"], 0),
    (["errors", "--limit", "5"], 0),
    (["errors", "--agent", "agent-0", "--last", "7d"], 0),
]


@pytest.mark.parametrize("args,expected_exit", ERRORS_CLI_CASES)
def test_errors_variants(runner, td, args, expected_exit):
    result = runner.invoke(app, args, env={"TELEMETRY_DIR": td})
    assert result.exit_code == expected_exit


# ═══════════════════════════════════════════════════════════════════════════════
# Stats CLI
# ═══════════════════════════════════════════════════════════════════════════════

STATS_CLI_CASES = [
    (["stats", "agent-0"], 0),
    (["stats", "agent-1"], 0),
    (["stats", "agent-0", "--last", "24h"], 0),
    (["stats", "agent-0", "--last", "1h"], 0),
]


@pytest.mark.parametrize("args,expected_exit", STATS_CLI_CASES)
def test_stats_variants(runner, td, args, expected_exit):
    result = runner.invoke(app, args, env={"TELEMETRY_DIR": td})
    assert result.exit_code == expected_exit


# ═══════════════════════════════════════════════════════════════════════════════
# Drift CLI
# ═══════════════════════════════════════════════════════════════════════════════

DRIFT_CLI_CASES = [
    (
        [
            "drift",
            "agent-0",
            "--baseline",
            '{"avg_duration_ms": 100, "error_rate": 0.05, "total_tokens": 100}',
        ],
        0,
    ),
    (
        [
            "drift",
            "agent-0",
            "--baseline",
            '{"avg_duration_ms": 10, "error_rate": 0.01, "total_tokens": 1}',
            "--window",
            "12",
        ],
        0,
    ),
    (["drift", "agent-0", "--baseline", "bad json"], 1),
]


@pytest.mark.parametrize("args,expected_exit", DRIFT_CLI_CASES)
def test_drift_variants(runner, td, args, expected_exit):
    result = runner.invoke(app, args, env={"TELEMETRY_DIR": td})
    assert result.exit_code == expected_exit


# ═══════════════════════════════════════════════════════════════════════════════
# Alert CLI
# ═══════════════════════════════════════════════════════════════════════════════

ALERT_CASES = [
    (["alert", "total_traces > 0", "--agent", "agent-0"], 1),  # triggers: 3 > 0
    (["alert", "total_traces > 9999", "--agent", "agent-0"], 0),  # ok: 3 < 9999
    (["alert", "total_traces > 2", "--agent", "agent-0"], 1),  # triggers: 3 > 2
    (["alert", "total_traces >= 3", "--agent", "agent-0"], 1),  # triggers
    (["alert", "total_traces > 4", "--agent", "agent-0"], 0),  # ok: 3 < 4
    (["alert", "bad metric > 0", "--agent", "agent-0"], 2),  # unknown metric
    (["alert", "bad format", "--agent", "agent-0"], 2),  # invalid format
]


@pytest.mark.parametrize("args,expected_exit", ALERT_CASES)
def test_alert_variants(runner, td, args, expected_exit):
    result = runner.invoke(app, args, env={"TELEMETRY_DIR": td})
    assert result.exit_code == expected_exit


# ═══════════════════════════════════════════════════════════════════════════════
# Replay CLI
# ═══════════════════════════════════════════════════════════════════════════════


def test_replay_nonexistent(runner, td):
    result = runner.invoke(app, ["replay", "nonexistent_trace_id"], env={"TELEMETRY_DIR": td})
    assert result.exit_code == 0
    assert "not found" in result.stdout


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases — storage
# ═══════════════════════════════════════════════════════════════════════════════


class TestStorageEdgeCases:
    def test_store_batch(self, td_dir):
        s = TelemetryStore(root=td_dir)
        traces = []
        for i in range(5):
            t = Trace(agent_name=f"batch-{i % 2}")
            t.start_span("op").finish()
            traces.append(t)
        for t in traces:
            s.store(t)
        results = s.search(agent_name="batch-0")
        assert len(results) == 3

    def test_empty_search(self, td_dir):
        s = TelemetryStore(root=td_dir)
        results = s.search()
        assert len(results) == 0

    def test_search_by_time_range(self, td_dir):
        s = TelemetryStore(root=td_dir)
        t = Trace(agent_name="time-test")
        t.start_span("op").finish()
        s.store(t)

        results = s.search(agent_name="time-test")
        assert len(results) == 1


@pytest.fixture
def td_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d
