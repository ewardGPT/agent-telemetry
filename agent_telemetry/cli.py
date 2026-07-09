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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
