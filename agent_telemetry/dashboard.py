"""Rich-based TUI dashboard for live agent telemetry monitoring."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_telemetry.storage import TelemetryStore


def dashboard(refresh_sec: float = 2.0) -> None:
    """Run an interactive terminal dashboard.

    Press Ctrl+C to exit.
    """
    console = Console()
    store = TelemetryStore()

    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )

    with Live(layout, screen=True, refresh_per_second=1 / refresh_sec):
        try:
            while True:
                layout["header"].update(_render_header(store))
                layout["body"].update(_render_body(store))
                layout["footer"].update(
                    Panel(
                        Text.from_markup("[dim]Ctrl+C to exit | agent-telemetry dashboard[/]"),
                        height=3,
                    )
                )
                time.sleep(refresh_sec)
        except KeyboardInterrupt:
            console.print("[green]Dashboard exited.[/]")


def _render_header(store: TelemetryStore) -> Panel:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return Panel(
        Text.from_markup(f"[bold]Agent Telemetry Dashboard[/]\n[dim]{now}[/]"),
        style="bold blue",
    )


def _render_body(store: TelemetryStore) -> Layout:
    body = Layout()
    body.split_row(
        Layout(name="stats", ratio=1),
        Layout(name="errors", ratio=1),
    )

    body["stats"].update(_render_stats(store))
    body["errors"].update(_render_errors(store))
    return body


def _render_stats(store: TelemetryStore) -> Panel:
    conn = store._get_conn()
    row = conn.execute("""
        SELECT COUNT(*) as total, SUM(error_count) as errors,
               SUM(total_tokens) as tokens, SUM(total_cost) as cost,
               AVG(duration_ms) as avg_ms, COUNT(DISTINCT agent_name) as agents
        FROM traces
    """).fetchone()
    conn.close()

    if not row or row["total"] == 0:
        return Panel("[dim]No traces yet[/]", title="Overview")

    error_rate = (row["errors"] or 0) / max(row["total"], 1) * 100
    lines = [
        f"[bold]Traces:[/]  {row['total']}",
        f"[bold]Agents:[/]  {row['agents']}",
        f"[bold]Tokens:[/]  {row['tokens'] or 0:,}",
        f"[bold]Cost:[/]    ${row['cost'] or 0:.4f}",
        f"[bold]Avg ms:[/]  {row['avg_ms'] or 0:.0f}ms",
        f"[bold]Errors:[/]  {row['errors'] or 0} ({error_rate:.1f}%)",
    ]
    return Panel("\n".join(lines), title="Overview")


def _render_errors(store: TelemetryStore) -> Panel:
    conn = store._get_conn()
    rows = conn.execute("""
        SELECT agent_name, error_count, started_at, trace_id
        FROM traces WHERE error_count > 0
        ORDER BY started_at DESC LIMIT 10
    """).fetchall()
    conn.close()

    if not rows:
        return Panel("[green]No errors[/]", title="Recent Errors")

    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("Agent", style="cyan")
    table.add_column("Errors", justify="right", style="red")
    table.add_column("When", style="dim")
    table.add_column("Trace ID", style="dim")

    for r in rows:
        ts = r["started_at"][:19] if r["started_at"] else "-"
        table.add_row(r["agent_name"], str(r["error_count"]), ts, r["trace_id"][:12])

    return Panel(table, title="Recent Errors")


def main() -> None:
    dashboard()


if __name__ == "__main__":
    main()
