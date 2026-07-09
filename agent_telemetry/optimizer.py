"""Cost optimizer for agent-telemetry.

Analyzes model usage from telemetry data and suggests cost-saving
model switches based on capability profiles.
"""

from __future__ import annotations

from agent_telemetry.storage import TelemetryStore

# Known cheaper alternatives for common models
MODEL_ALTERNATIVES: dict[str, list[dict]] = {
    "kimi-k2.5": [
        {"name": "llama-3.3-70b-instruct", "provider": "cloudflare", "savings_pct": 40},
        {"name": "llama-3.1-8b-instruct", "provider": "cloudflare", "savings_pct": 70},
    ],
    "claude-3-sonnet-20240229": [
        {"name": "claude-3-haiku-20240307", "provider": "anthropic", "savings_pct": 60},
        {"name": "llama-3.3-70b", "provider": "aws", "savings_pct": 80},
    ],
    "claude-3-haiku-20240307": [
        {"name": "llama-3.1-8b", "provider": "aws", "savings_pct": 50},
    ],
    "gpt-4": [
        {"name": "gpt-4o-mini", "provider": "openai", "savings_pct": 90},
        {"name": "gpt-3.5-turbo", "provider": "openai", "savings_pct": 95},
    ],
}


def optimize_costs(store: TelemetryStore) -> list[dict]:
    """Suggest model switches based on cost analysis of telemetry data."""
    conn = store._get_conn()
    rows = conn.execute("""
        SELECT agent_name, SUM(total_tokens) as tokens, SUM(total_cost) as cost,
               COUNT(*) as trace_count
        FROM traces GROUP BY agent_name ORDER BY cost DESC
    """).fetchall()
    conn.close()

    suggestions: list[dict] = []
    for row in rows:
        agent = row["agent_name"]
        cost = row["cost"] or 0
        if cost < 0.01:
            continue

        suggestion = {
            "agent": agent,
            "current_monthly_cost_est": round(cost * 30, 4),
            "total_tokens": row["tokens"],
            "trace_count": row["trace_count"],
            "alternatives": [],
        }

        for alts in MODEL_ALTERNATIVES.values():
            suggestion["alternatives"].extend(
                [
                    {
                        "switch_to": f"{alt['provider']}/{alt['name']}",
                        "estimated_savings_pct": alt["savings_pct"],
                        "estimated_monthly_savings": round(cost * 30 * alt["savings_pct"] / 100, 4),
                    }
                    for alt in alts
                ]
            )

        if suggestion["alternatives"]:
            suggestions.append(suggestion)

    return suggestions
