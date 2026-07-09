"""Behavior drift detector.

Compares current production metrics against stored baselines
and historical averages. Flags when agent behavior has shifted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_telemetry.storage import TelemetryStore


def detect_drift(
    store: TelemetryStore,
    agent_name: str,
    window_hours: float = 24,
    threshold_pct: float = 25,
) -> dict:
    """Detect behavior drift for an agent compared to historical baseline."""
    now = datetime.now(timezone.utc)
    baseline_since = now - timedelta(days=30)
    current_since = now - timedelta(hours=window_hours)

    baseline = store.stats(agent_name=agent_name, start_after=baseline_since)
    current = store.stats(agent_name=agent_name, start_after=current_since)

    if not current or current.get("total_traces", 0) == 0:
        return {"agent": agent_name, "drift_detected": False, "reason": "insufficient data"}

    metrics = ["avg_duration_ms", "error_rate", "total_cost_usd"]
    drifts: list[dict] = []

    for metric in metrics:
        base_val = baseline.get(metric) or 0
        cur_val = current.get(metric) or 0

        if base_val == 0 and cur_val == 0:
            continue
        if base_val == 0:
            drifts.append({"metric": metric, "baseline": 0, "current": cur_val, "pct_change": 100})
            continue

        pct = (cur_val - base_val) / base_val * 100
        if abs(pct) > threshold_pct:
            drifts.append(
                {
                    "metric": metric,
                    "baseline": round(base_val, 4),
                    "current": round(cur_val, 4),
                    "pct_change": round(pct, 1),
                    "direction": "↑" if pct > 0 else "↓",
                }
            )

    alerts: list[str] = []
    for d in drifts:
        if d["metric"] == "error_rate" and d["pct_change"] > 0:
            alerts.append(f"Error rate increased {d['pct_change']}% — possible regression")
        if d["metric"] == "avg_duration_ms" and d["pct_change"] > 50:
            alerts.append(f"Latency spiked {d['pct_change']}% — possible model or infra change")
        if d["metric"] == "total_cost_usd" and d["pct_change"] > 30:
            alerts.append(f"Cost increased {d['pct_change']}% — check prompt/model changes")

    return {
        "agent": agent_name,
        "drift_detected": len(drifts) > 0,
        "window_hours": window_hours,
        "drifts": drifts,
        "alerts": alerts,
    }
