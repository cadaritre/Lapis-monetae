from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

DEFAULT_NETWORK = "mainnet"
NETWORK_CHOICES = ("mainnet", "testnet-10", "testnet-11")

_FROZEN = getattr(sys, "frozen", False)
_EXE_DIR = Path(sys.executable).parent if _FROZEN else None

APP_DIR = _EXE_DIR if _FROZEN else Path(__file__).resolve().parents[1]
REPO_ROOT = _EXE_DIR if _FROZEN else Path(__file__).resolve().parents[2]
CONFIG_PATH = _EXE_DIR / ".wallet_gui_config.json" if _FROZEN else APP_DIR / ".wallet_gui_config.json"

DEFAULT_SESSION_TIMEOUT_MINUTES = 0  # 0 = disabled
SESSION_TIMEOUT_CHOICES = (0, 5, 10, 15, 30, 60)

PROFILE_KEYS = (
    "cli_path", "network", "last_wallet", "contacts",
    "session_timeout_minutes", "auto_lock_on_timeout",
    "seed_backup_confirmed",
)

PROFILE_DEFAULTS: dict[str, Any] = {
    "cli_path": "",
    "network": DEFAULT_NETWORK,
    "last_wallet": "",
    "contacts": [],
    "session_timeout_minutes": DEFAULT_SESSION_TIMEOUT_MINUTES,
    "auto_lock_on_timeout": True,
    "seed_backup_confirmed": {},
}


def _make_default_config() -> dict[str, Any]:
    return {
        "_version": 2,
        "active_profile": "default",
        "profiles": {"default": dict(PROFILE_DEFAULTS)},
    }


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return _make_default_config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _make_default_config()
    if "_version" not in data:
        return {"_version": 2, "active_profile": "default", "profiles": {"default": data}}
    return data


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def active_profile(config: dict[str, Any]) -> dict[str, Any]:
    name = config.get("active_profile", "default")
    profiles = config.get("profiles", {})
    return profiles.get(name, dict(PROFILE_DEFAULTS))


def resolve_cli_binary(config: dict[str, Any]) -> str | None:
    profile = active_profile(config) if "profiles" in config else config
    candidates: list[str] = []
    explicit = str(profile.get("cli_path", "")).strip()
    env_bin = os.environ.get("LMT_CLI_BIN", "").strip()
    if explicit:
        candidates.append(explicit)
    if env_bin:
        candidates.append(env_bin)
    candidates.extend(["kaspa-cli", "lmt-cli", "kaspa-cli.exe", "lmt-cli.exe"])

    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).exists():
            return str(Path(candidate))
        found = shutil.which(candidate)
        if found:
            return found
    return None
