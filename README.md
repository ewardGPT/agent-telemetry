# Agent Telemetry

Production observability for AI agents — OpenTelemetry-compatible trace collection, query, and analysis. Runtime companion to eval-harness.

## Quick Start

```bash
pip install -e .

# Instrument your agent code
# Then query from the CLI
```

### Instrument Python Code

```python
from agent_telemetry.instrument import TelemetryClient, instrument

client = TelemetryClient("agentic-inbox", environment="production")

@instrument(client, kind="tool")
def read_inbox(mailbox_id: str, limit: int = 20):
    # This call is now automatically traced
    ...

# Run a complete agent invocation as a trace
with client.trace(session_id="user-session-123"):
    emails = read_inbox("mbx-1")
    # All @instrument calls inside this block are traced
```

## CLI Reference

```bash
# Search recent traces
agent-telemetry search --agent agentic-inbox --last 24h
agent-telemetry search --agent agentic-inbox --error --limit 50
agent-telemetry search --slow 5000  # traces slower than 5s

# Cost breakdown
agent-telemetry cost agentic-inbox
agent-telemetry cost agentic-inbox --group-by environment --last 7d

# Recent errors
agent-telemetry errors --agent agentic-inbox --last 1h

# Aggregate stats
agent-telemetry stats agentic-inbox --last 24h

# Drift detection against baseline
agent-telemetry drift agentic-inbox --baseline '{"avg_duration_ms": 1200, "error_rate": 0.02}'

# Replay a full trace
agent-telemetry replay <trace-id>

# Alert condition check (non-zero exit on trigger)
agent-telemetry alert "error_rate > 0.05" --agent agentic-inbox --last 1h
```

## Storage

- **SQLite** (`~/.config/agent-telemetry/traces.db`) — indexed metadata for fast queries
- **JSONL** (`~/.config/agent-telemetry/traces.jsonl`) — full trace payloads for replay

Set `TELEMETRY_DIR` to override storage location.

## Trace Structure

Each trace contains:
- **Trace ID** — unique invocation identifier
- **Spans** — individual work units (tool calls, LLM inferences, agent decisions)
- **Events** — timestamped observations within spans
- **Attributes** — recorded metadata (tokens, cost, duration, errors)

## Integration with Eval Harness

Production traces feed back into eval-harness:
1. Instrument agents with `TelemetryClient`
2. `agent-telemetry search` finds real production failure patterns
3. Convert production traces into eval test cases
4. Run `evalh` with new production-seeded suites

This closes the loop: **test → deploy → observe → refine tests**.
