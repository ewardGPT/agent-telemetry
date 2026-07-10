"""Example: Instrumenting an agent with Agent Telemetry.

Usage:
    python example_instrumentation.py

This demonstrates:
- Setting up a TelemetryClient
- Using the @instrument decorator for automatic tracing
- Using the trace() context manager for full invocation traces
- Using the span() context manager for manual control
"""

from agent_telemetry.instrument import TelemetryClient, instrument, trace_tool
from agent_telemetry.schema import SpanKind

# ── Setup ─────────────────────────────────────────────────────────────────────

client = TelemetryClient(
    "agentic-inbox",
    environment="production",
    agent_version="2.1.0",
)


# ── Instrumented functions ────────────────────────────────────────────────────


@instrument(client, kind=SpanKind.TOOL)
def read_inbox(mailbox_id: str, limit: int = 20) -> dict:
    """Read emails from a mailbox. Automatically traced."""
    # In production, this would call your actual email service
    return {"mailbox": mailbox_id, "emails": [], "count": 0}


@instrument(client, kind=SpanKind.TOOL)
def send_email(to: str, subject: str, body: str, mailbox_id: str) -> bool:
    """Send an email. Automatically traced."""
    return True


@instrument(client, kind=SpanKind.LLM)
def generate_draft(context: str) -> str:
    """Generate a draft reply using an LLM. Traced as LLM span."""
    return f"Draft reply for: {context}"


# ── Agent workflow ────────────────────────────────────────────────────────────


def handle_incoming_email(user_id: str, email_text: str) -> None:
    """Complete agent workflow: read, draft, send (all traced)."""

    with client.trace(session_id=user_id):
        # Manual span for workflow orchestration
        with client.span("handle_email", kind=SpanKind.WORKFLOW):
            read_inbox(user_id)
            draft = generate_draft(email_text)
            send_email(user_id, "Re: Hello", draft, "main")

        # Access trace metadata
        trace = client.current_trace
        if trace:
            trace.start_span("finalize", kind=SpanKind.AGENT, total_emails=0).finish()


# ── Quick instrumentation (no client needed) ──────────────────────────────────


@trace_tool("quick_health_check")
def health_check() -> str:
    """Standalone trace — no TelemetryClient required."""
    return "ok"


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    health_check()
    handle_incoming_email("user-42", "Hello, can you help me?")
    print("Traces stored in ~/.config/agent-telemetry/")
