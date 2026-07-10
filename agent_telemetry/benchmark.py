"""Performance benchmark for agent operations.

Measures latency, token usage, and cost per capability.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

from agent_telemetry.instrument import TelemetryClient
from agent_telemetry.schema import SpanKind


@dataclass
class BenchmarkResult:
    name: str
    runs: int
    latencies_ms: list[float] = field(default_factory=list)
    tokens: list[int] = field(default_factory=list)
    costs: list[float] = field(default_factory=list)

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0

    @property
    def p50_ms(self) -> float:
        s = sorted(self.latencies_ms)
        return s[len(s) // 2] if s else 0

    @property
    def p95_ms(self) -> float:
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.95)] if s else 0

    @property
    def avg_tokens(self) -> float:
        return statistics.mean(self.tokens) if self.tokens else 0

    @property
    def avg_cost(self) -> float:
        return statistics.mean(self.costs) if self.costs else 0


def run_benchmark(
    agent_name: str,
    func: callable,
    name: str = "bench",
    warmup: int = 3,
    runs: int = 10,
    *args,
    **kwargs,
) -> BenchmarkResult:
    """Benchmark a function with warmup and measured runs."""
    client = TelemetryClient(agent_name, environment="benchmark")

    result = BenchmarkResult(name=name, runs=runs)

    # Warmup
    for _ in range(warmup):
        func(*args, **kwargs)

    # Measured runs
    for _ in range(runs):
        start = time.monotonic()
        with client.trace(), client.span(f"{name}_span", kind=SpanKind.TOOL):
            func(*args, **kwargs)
        elapsed = (time.monotonic() - start) * 1000
        result.latencies_ms.append(elapsed)

        if client.current_trace:
            result.tokens.append(
                int(
                    sum(
                        float(s.attributes.get("tokens_in", 0))
                        + float(s.attributes.get("tokens_out", 0))
                        for s in client.current_trace.spans
                    )
                )
            )

    return result


def benchmark_agent_capability(
    agent_name: str,
    capability: str,
    func: callable,
    client: TelemetryClient | None = None,
    runs: int = 10,
):
    """Benchmark a specific agent capability."""
    client = client or TelemetryClient(agent_name, environment="benchmark")
    result = BenchmarkResult(name=capability, runs=runs)

    for _ in range(3):  # warmup
        func()

    for _ in range(runs):
        start = time.monotonic()
        with client.trace(), client.span(capability, kind=SpanKind.TOOL):
            func()
        elapsed = (time.monotonic() - start) * 1000
        result.latencies_ms.append(elapsed)

    return result
