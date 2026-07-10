"""Alert engine — sends notifications to Slack, Discord, and GitHub.

Triggered by drift detection, security audits, and custom conditions.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone


def send_alert(
    title: str,
    body: str,
    severity: str = "warning",
    slack_webhook: str = "",
    discord_webhook: str = "",
    github_repo: str = "",
) -> dict[str, bool]:
    """Send alerts to configured channels. Returns per-channel success."""
    results: dict[str, bool] = {}

    if slack_webhook:
        results["slack"] = _send_slack(slack_webhook, title, body, severity)
    if discord_webhook:
        results["discord"] = _send_discord(discord_webhook, title, body, severity)
    if github_repo:
        results["github"] = _create_issue(github_repo, title, body, severity)

    return results


def alert_drift(agent: str, drifts: list[dict], config: dict) -> dict[str, bool]:
    """Alert on drift detection."""
    slack = config.get("slack_webhook", "")
    discord = config.get("discord_webhook", "")
    gh = config.get("github_repo", "")

    if not (slack or discord or gh):
        return {}

    body_lines = [f"**Agent:** {agent}", "", "**Drifts detected:**"]
    for d in drifts:
        body_lines.append(f"- {d['metric']}: {d['baseline']} → {d['current']} ({d['pct_change']}%)")

    return send_alert(
        title=f"⚠ Drift detected: {agent}",
        body="\n".join(body_lines),
        severity="warning",
        slack_webhook=slack,
        discord_webhook=discord,
        github_repo=gh,
    )


def alert_security(findings: list, config: dict) -> dict[str, bool]:
    """Alert on critical/high security findings."""
    slack = config.get("slack_webhook", "")
    discord = config.get("discord_webhook", "")
    gh = config.get("github_repo", "")

    if not (slack or discord or gh):
        return {}

    crit = [f for f in findings if getattr(f, "severity", "") == "critical"]
    high = [f for f in findings if getattr(f, "severity", "") == "high"]

    if not crit and not high:
        return {}

    body_lines = []
    if crit:
        body_lines.append("**Critical:**")
        for f in crit:
            body_lines.append(f"- [{getattr(f, 'agent', '?')}] {getattr(f, 'title', '?')}")
    if high:
        body_lines.append("**High:**")
        for f in high:
            body_lines.append(f"- [{getattr(f, 'agent', '?')}] {getattr(f, 'title', '?')}")

    return send_alert(
        title=f"🔒 Security audit: {len(crit)} critical, {len(high)} high",
        body="\n".join(body_lines),
        severity="critical",
        slack_webhook=slack,
        discord_webhook=discord,
        github_repo=gh,
    )


def _send_slack(webhook: str, title: str, body: str, severity: str) -> bool:
    color = {"critical": "#ff0000", "warning": "#ffa500", "info": "#36a64f"}.get(
        severity, "#36a64f"
    )
    payload = {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": body,
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }
        ]
    }
    return _post(webhook, payload)


def _send_discord(webhook: str, title: str, body: str, severity: str) -> bool:
    color = {"critical": 0xFF0000, "warning": 0xFFA500, "info": 0x36A64F}.get(severity, 0x36A64F)
    payload = {"embeds": [{"title": title, "description": body, "color": color}]}
    return _post(webhook, payload)


def _create_issue(repo: str, title: str, body: str, severity: str) -> bool:
    try:
        result = os.system(
            f'gh issue create --repo {repo} --title "{title}" --body "{body}" --label "security" 2>/dev/null'
        )
        return result == 0
    except Exception:
        return False


def _post(url: str, payload: dict) -> bool:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False
