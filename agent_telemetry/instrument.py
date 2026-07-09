"""Decorator-based instrumentation for agent functions.

Usage:
    from agent_telemetry.instrument import TelemetryClient, instrument

    client = TelemetryClient("agentic-inbox", environment="production")

    @instrument(client, kind="tool")
    def read_inbox(mailbox_id: str, limit: int = 20):
        ...
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from contextlib import contextmanager

from agent_telemetry.schema import SpanKind, Trace
from agent_telemetry.storage import TelemetryStore


class TelemetryClient:
    """Client for instrumenting an agent with tracing.

    Create one client per agent instance.  Each invocation starts a new trace.
    """

    def __init__(
        self,
        agent_name: str,
        environment: str = "production",
        agent_version: str | None = None,
        store: TelemetryStore | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.environment = environment
        self.agent_version = agent_version
        self._store = store or TelemetryStore()
        self._current_trace: Trace | None = None

    @property
    def current_trace(self) -> Trace | None:
        return self._current_trace

    @contextmanager
    def trace(
        self,
        session_id: str | None = None,
        tags: dict | None = None,
    ):
        """Context manager for a complete agent invocation trace."""
        self._current_trace = Trace(
            agent_name=self.agent_name,
            environment=self.environment,
            agent_version=self.agent_version,
            session_id=session_id,
        )
        self._tags = tags
        try:
            yield self._current_trace
        except Exception:
            for s in self._current_trace.spans:
                if not s.end_time:
                    s.fail("unhandled_exception")
            self._current_trace.finish()
            self._store.store(self._current_trace, tags=self._tags)
            raise
        else:
            self._current_trace.finish()
            self._store.store(self._current_trace, tags=self._tags)
        finally:
            self._current_trace = None

    @contextmanager
    def span(
        self,
        name: str,
        kind: SpanKind = SpanKind.TOOL,
        **attrs,
    ):
        """Context manager for a span within the current trace."""
        if self._current_trace is None:
            raise RuntimeError("No active trace. Use `trace()` context manager first.")

        span = self._current_trace.start_span(name, kind=kind, **attrs)
        try:
            yield span
        except Exception as e:
            span.fail(str(e))
            raise
        else:
            span.finish()


def instrument(
    client: TelemetryClient,
    kind: SpanKind = SpanKind.TOOL,
    capture_args: bool = False,
    capture_result: bool = False,
) -> Callable:
    """Decorator: instrument a function as a span within the current trace.

    Args:
        client: The TelemetryClient instance
        kind: Span kind (tool, llm, agent, etc.)
        capture_args: Include function arguments in span attributes
        capture_result: Include return value in span attributes

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if client.current_trace is None:
                return func(*args, **kwargs)

            attrs = {"function": func.__name__}
            if capture_args:
                attrs["args"] = str(args)
                attrs["kwargs"] = str(kwargs)

            span = client.current_trace.start_span(func.__name__, kind=kind, **attrs)
            started = time.monotonic()
            try:
                result = func(*args, **kwargs)
                span.finish()
                span.attributes["duration_ms"] = (time.monotonic() - started) * 1000
                if capture_result:
                    span.attributes["result"] = str(result)
                return result
            except Exception as e:
                span.fail(str(e))
                span.attributes["duration_ms"] = (time.monotonic() - started) * 1000
                raise

        return wrapper

    return decorator


def trace_tool(name: str):
    """Lightweight decorator that creates a standalone trace + span (no client needed).

    Use for quick one-off instrumentation without a TelemetryClient.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            trace = Trace(agent_name="unknown", environment="development")
            span = trace.start_span(name, kind=SpanKind.TOOL)
            started = time.monotonic()
            try:
                result = func(*args, **kwargs)
                span.finish()
                span.attributes["duration_ms"] = (time.monotonic() - started) * 1000
                return result
            except Exception as e:
                span.fail(str(e))
                raise
            finally:
                trace.finish()
                TelemetryStore().store(trace)

        return wrapper

    return decorator
