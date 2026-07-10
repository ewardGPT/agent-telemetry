"""Config file loader for agent-telemetry."""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "telemetry_dir": str(Path.home() / ".config" / "agent-telemetry"),
    "drift": {
        "window_hours": 24,
        "threshold_pct": 25,
    },
    "alerts": {
        "slack_webhook": "",
        "discord_webhook": "",
        "github_repo": "",
    },
    "dashboard": {
        "refresh_sec": 2.0,
    },
    "benchmark": {
        "warmup_runs": 3,
        "measure_runs": 10,
    },
}

_config: dict | None = None


def load_config() -> dict:
    global _config
    if _config is not None:
        return _config
    config_path = Path.home() / ".config" / "agent-telemetry" / "config.yaml"
    if config_path.exists():
        _config = {**DEFAULT_CONFIG, **yaml.safe_load(config_path.read_text() or {})}
    else:
        _config = dict(DEFAULT_CONFIG)
    return _config


def get(key: str, default=None):
    config = load_config()
    parts = key.split(".")
    val = config
    for p in parts:
        val = val.get(p, {})
    return val if val != {} else default
