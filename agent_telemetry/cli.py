"""CLI for Agent Telemetry.

Usage:
    agent-telemetry search --agent agentic-inbox --error
    agent-telemetry cost --agent agentic-inbox --group-by environment
    agent-telemetry errors --agent nexusgate --last 7d
    agent-telemetry drift --agent agentic-inbox --baseline '{"avg_duration_ms": 1200}'
    agent-telemetry stats --agent agentic-inbox --last 24h
    agent-telemetry replay --trace-id abc123
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_telemetry.storage import TelemetryStore

app = typer.Typer(
    name="agent-telemetry",
    help="Production observability for AI agents — trace, query, and analyze.",
    no_args_is_help=True,
)

console = Console()


def _get_store() -> TelemetryStore:
    root = os.environ.get("TELEMETRY_DIR")
    return TelemetryStore(root=root) if root else TelemetryStore()


def _parse_time(when: str | None) -> datetime | None:
    """Parse relative time like '1h', '7d', '30m'."""
    if not when:
        return None
    import re

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


# ── Commands ───────────────────────────────────────────────────────────────────


@app.command()
def search(
    agent: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent name"),
    error: bool = typer.Option(False, "--error", "-e", help="Show only error traces"),
    slow: float | None = typer.Option(None, "--slow", "-s", help="Min duration in ms"),
    last: str | None = typer.Option(None, "--last", help="Time window, e.g. 1h, 7d"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
):
    """Search traces with filters."""
    store = _get_store()
    results = store.search(
        agent_name=agent,
        error=error,
        min_duration_ms=slow,
        start_after=_parse_time(last),
        limit=limit,
    )

    if not results:
        console.print("[yellow]No matching traces.[/]")
        return

    table = Table(title=f"Trace Search ({len(results)} results)")
    table.add_column("Trace ID", style="cyan")
    table.add_column("Agent")
    table.add_column("Started", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("Tokens")
    table.add_column("Cost", justify="right")
    table.add_column("Errors", justify="right")

    for r in results:
        errors = f"[red]{r['error_count']}[/]" if r["error_count"] > 0 else "0"
        table.add_row(
            r["trace_id"][:12],
            r["agent_name"],
            r["started_at"][:19] if r["started_at"] else "-",
            f"{r['duration_ms']:.0f}ms",
            str(r["total_tokens"]),
            f"${r['total_cost']:.4f}",
            errors,
        )

    console.print(table)


@app.command()
def cost(
    agent: str = typer.Argument(..., help="Agent name"),
    group_by: str = typer.Option(
        "agent_name", "--group-by", "-g", help="Group by: agent_name, environment"
    ),
    last: str | None = typer.Option(None, "--last", help="Time window, e.g. 7d"),
):
    """Show cost breakdown by agent and grouping."""
    store = _get_store()
    results = store.cost_report(
        agent_name=agent,
        group_by=group_by,
        start_after=_parse_time(last),
    )

    if not results:
        console.print("[yellow]No cost data.[/]")
        return

    table = Table(title=f"Cost Report: {agent}")
    table.add_column(group_by, style="cyan")
    table.add_column("Traces", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Avg Duration", justify="right")
    table.add_column("Errors", justify="right")

    for r in results:
        table.add_row(
            str(r["grp"]),
            str(r["trace_count"]),
            str(r["tokens"]),
            f"${r['cost']:.4f}",
            f"{r['avg_duration_ms']:.0f}ms",
            str(r["total_errors"]),
        )

    console.print(table)


@app.command()
def errors(
    agent: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent"),
    last: str | None = typer.Option(None, "--last", help="Time window, e.g. 24h"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """Show recent error traces."""
    store = _get_store()
    results = store.error_summary(
        agent_name=agent,
        start_after=_parse_time(last),
        limit=limit,
    )

    if not results:
        console.print("[green]No errors found.[/]")
        return

    console.print(f"[bold red]{len(results)} error trace(s)[/]")
    for r in results:
        console.print(
            f"  [cyan]{r['trace_id'][:12]}[/] "
            f"[bold]{r['agent_name']}[/] "
            f"[dim]{r['started_at'][:19]}[/] "
            f"{r['duration_ms']:.0f}ms "
            f"[red]{r['error_count']} errors[/]"
        )


@app.command()
def stats(
    agent: str = typer.Argument(..., help="Agent name"),
    last: str | None = typer.Option(None, "--last", help="Time window, e.g. 24h"),
):
    """Show aggregate statistics for an agent."""
    store = _get_store()
    s = store.stats(
        agent_name=agent,
        start_after=_parse_time(last),
    )

    if not s or s.get("total_traces", 0) == 0:
        console.print("[yellow]No data for this agent.[/]")
        return

    rows = [
        f"[bold]Total Traces:[/]     {s['total_traces']}",
        f"[bold]Total Tokens:[/]     {s['total_tokens']:,}",
        f"[bold]Total Cost:[/]       ${s['total_cost_usd']:.4f}",
        f"[bold]Avg Duration:[/]     {s['avg_duration_ms']:.0f}ms",
        f"[bold]Total Errors:[/]     {s['total_errors']}",
        f"[bold]Error Rate:[/]       {s.get('error_rate', 0):.2%}",
    ]
    text = "\n".join(rows)
    console.print(Panel(Text.from_markup(text), title=f"Stats: {agent}"))


@app.command()
def drift(
    agent: str = typer.Argument(..., help="Agent name"),
    baseline: str = typer.Option(
        ...,
        "--baseline",
        "-b",
        help='JSON baseline, e.g. \'{"avg_duration_ms": 1200, "error_rate": 0.02}\'',
    ),
    window_hours: float = typer.Option(24.0, "--window", "-w", help="Comparison window in hours"),
):
    """Detect drift by comparing current stats against a baseline."""
    try:
        baseline_data = json.loads(baseline)
    except json.JSONDecodeError as e:
        console.print("[red]✗[/] Invalid JSON for baseline.")
        raise typer.Exit(1) from e

    store = _get_store()
    result = store.drift_check(agent, baseline_data, window_hours)

    console.print(f"[bold]Drift Report: {agent} (last {window_hours}h)[/]")
    for key, vals in result["drift"].items():
        pct = vals["pct_change"]
        color = "red" if abs(pct) > 20 else "yellow" if abs(pct) > 10 else "green"
        console.print(
            f"  {key}: baseline={vals['baseline']} → current={vals['current']} "
            f"[{color}]{pct:+.1f}%[/{color}]"
        )


@app.command()
def replay(
    trace_id: str = typer.Argument(..., help="Trace ID to retrieve from JSONL"),
):
    """Replay a full trace from the JSONL store."""
    store = _get_store()
    traces_path = store.root / "traces.jsonl"
    if not traces_path.exists():
        console.print("[yellow]No traces stored yet.[/]")
        return

    found = None
    with open(traces_path) as f:
        for line in f:
            if trace_id in line:
                found = json.loads(line)
                break

    if not found:
        console.print(f"[yellow]Trace '{trace_id}' not found.[/]")
        return

    console.print_json(json.dumps(found, default=str))


@app.command()
def alert(
    condition: str = typer.Argument(..., help="Alert condition, e.g. 'error_rate > 0.05'"),
    agent: str = typer.Option(..., "--agent", "-a", help="Agent to check"),
    last: str = typer.Option("24h", "--last", help="Time window"),
):
    """Check a condition against current stats and exit non-zero if triggered."""
    store = _get_store()
    s = store.stats(agent_name=agent, start_after=_parse_time(last))

    import re

    m = re.match(r"(\w+)\s*(>|<|>=|<=|==)\s*([\d.]+)", condition)
    if not m:
        console.print(f"[red]✗[/] Invalid condition format: {condition}")
        raise typer.Exit(2)

    metric, op, threshold = m.group(1), m.group(2), float(m.group(3))
    value = s.get(metric)

    if value is None:
        console.print(f"[red]✗[/] Unknown metric: {metric}")
        raise typer.Exit(2)

    triggers: bool
    if op == ">":
        triggers = value > threshold
    elif op == "<":
        triggers = value < threshold
    elif op == ">=":
        triggers = value >= threshold
    elif op == "<=":
        triggers = value <= threshold
    else:
        triggers = value == threshold

    if triggers:
        console.print(f"[red]⚠ ALERT: {metric} {op} {threshold} (current: {value})[/]")
        raise typer.Exit(1)
    else:
        console.print(f"[green]✓ OK: {metric} {op} {threshold} (current: {value})[/]")


@app.command()
def convert(
    trace_id: str = typer.Argument(..., help="Trace ID to convert to eval test case"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output file path (default: stdout)"
    ),
    suite: str = typer.Option("production_regression", "--suite", "-s", help="Eval suite name"),
):
    """Convert a production trace into an eval-harness test case."""
    store = _get_store()
    traces_path = store.root / "traces.jsonl"
    if not traces_path.exists():
        console.print("[yellow]No traces stored yet.[/]")
        raise typer.Exit(1)

    found = None
    with open(traces_path) as f:
        for line in f:
            data = json.loads(line)
            if data.get("trace_id") == trace_id:
                found = data
                break

    if not found:
        console.print(f"[yellow]Trace '{trace_id}' not found.[/]")
        raise typer.Exit(1)

    spans = found.get("spans", [])
    test_case = {
        "suite": suite,
        "test_id": f"trace_{trace_id[:12]}",
        "description": f"Regression test from {found['agent_name']} production trace",
        "agent": found["agent_name"],
        "environment": found.get("environment", "production"),
        "input": {
            "span_count": len(spans),
            "total_tokens": found.get("total_tokens", 0),
            "total_cost": found.get("total_cost", 0),
            "duration_ms": found.get("duration_ms", 0),
            "error_count": found.get("error_count", 0),
        },
        "expected": {
            "max_duration_ms": int(found.get("duration_ms", 100) * 1.5),
            "max_errors": 0,
            "min_tokens": 0,
        },
        "spans": [
            {
                "name": s["name"],
                "kind": s["kind"],
                "status": s["status"],
                "duration_ms": s.get("duration_ms", 0),
                "attributes": s.get("attributes", {}),
            }
            for s in spans
        ],
    }

    yaml_text = json_to_yaml(test_case)

    if output:
        Path(output).write_text(yaml_text)
        console.print(f"[green]✓[/] Eval test case exported to [bold]{output}[/]")
    else:
        console.print(yaml_text)


def json_to_yaml(data: dict) -> str:
    import yaml

    return yaml.dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


@app.command()
def convert_batch(
    agent: str = typer.Option(..., "--agent", "-a", help="Agent name to convert traces for"),
    output_dir: str = typer.Option("./eval-cases", "--output-dir", "-o", help="Output directory"),
    suite: str = typer.Option("production_regression", "--suite", "-s", help="Eval suite name"),
    error_only: bool = typer.Option(True, "--error-only/--all", help="Only convert error traces"),
    max_traces: int = typer.Option(50, "--max", "-n", help="Maximum traces to convert"),
    last: str = typer.Option("7d", "--last", help="Time window, e.g. 7d, 24h"),
):
    """Batch convert production traces to eval-harness test cases."""
    store = _get_store()
    results = store.search(
        agent_name=agent,
        error=error_only,
        limit=max_traces,
        start_after=_parse_time(last),
    )

    if not results:
        console.print("[yellow]No matching traces to convert.[/]")
        raise typer.Exit(0)

    odir = Path(output_dir)
    odir.mkdir(parents=True, exist_ok=True)

    traces_path = store.root / "traces.jsonl"
    if not traces_path.exists():
        console.print("[yellow]No trace data file found.[/]")
        return

    trace_ids = {r["trace_id"] for r in results}
    converted = 0

    with open(traces_path) as f:
        for line in f:
            data = json.loads(line)
            tid = data.get("trace_id")
            if tid not in trace_ids:
                continue

            test_case = {
                "suite": suite,
                "test_id": f"trace_{tid[:12]}",
                "description": f"Production regression from {data['agent_name']}",
                "agent": data["agent_name"],
                "expected": {
                    "max_duration_ms": int(data.get("duration_ms", 100) * 1.5),
                    "max_errors": 0,
                },
            }

            out_path = odir / f"trace_{tid[:12]}.yaml"
            out_path.write_text(json_to_yaml(test_case))
            converted += 1

    console.print(f"[green]✓[/] Converted [bold]{converted}[/] traces → [bold]{output_dir}/[/]")
    console.print(f"[dim]Run: evalh run --suite {suite} --dir {output_dir}/[/]")


def main() -> None:
    app()


@app.command()
def optimize(
    output_format: str = typer.Option("table", "--format", "-f", help="Output: table, json"),
):
    """Suggest cheaper model alternatives based on cost analysis."""
    import json

    from agent_telemetry.optimizer import optimize_costs

    suggestions = optimize_costs(_get_store())
    if not suggestions:
        console.print("[green]No optimization suggestions — costs are minimal[/]")
        return

    if output_format == "json":
        console.print(json.dumps(suggestions, indent=2, default=str))
        return

    for s in suggestions:
        console.print(
            f"[bold]{s['agent']}[/] — ${s['current_monthly_cost_est']:.2f}/mo est | {s['trace_count']} traces | {s['total_tokens']:,} tokens"
        )
        for alt in s["alternatives"]:
            console.print(
                f"  ↳ {alt['switch_to']}: save ~{alt['estimated_savings_pct']}% (${alt['estimated_monthly_savings']:.2f}/mo)"
            )
        console.print()


@app.command()
def drift_check(
    agent: str = typer.Argument(..., help="Agent name"),
    window_hours: float = typer.Option(24, "--window", "-w", help="Analysis window in hours"),
    threshold: float = typer.Option(25, "--threshold", "-t", help="Drift threshold percentage"),
):
    """Detect behavior drift compared to 30-day baseline."""

    from agent_telemetry.drift_detector import detect_drift

    result = detect_drift(_get_store(), agent, window_hours, threshold)

    if not result["drift_detected"]:
        console.print(f"[green]No drift detected for {agent}[/]")
        return

    console.print(f"[bold red]Drift detected for {agent}[/] ({window_hours}h window)")
    for d in result["drifts"]:
        console.print(
            f"  {d['metric']}: {d['baseline']} → {d['current']} ({d['direction']}{d['pct_change']}%)"
        )
    for alert in result["alerts"]:
        console.print(f"  [yellow]⚠ {alert}[/]")


@app.command()
def dashboard_cmd(
    refresh: float = typer.Option(2.0, "--refresh", "-r", help="Refresh interval in seconds"),
):
    """Launch the interactive terminal dashboard."""
    from agent_telemetry.dashboard import dashboard as run_dashboard

    run_dashboard(refresh_sec=refresh)


if __name__ == "__main__":
    main()
