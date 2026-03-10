from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

DEFAULT_NETWORK = "mainnet"
NETWORK_CHOICES = ("mainnet", "testnet-10", "testnet-11")

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = APP_DIR / ".wallet_gui_config.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"cli_path": "", "network": DEFAULT_NETWORK, "last_wallet": "", "contacts": []}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cli_path": "", "network": DEFAULT_NETWORK, "last_wallet": "", "contacts": []}
    contacts = data.get("contacts", [])
    if not isinstance(contacts, list):
        contacts = []
    return {
        "cli_path": str(data.get("cli_path", "")).strip(),
        "network": str(data.get("network", DEFAULT_NETWORK)).strip() or DEFAULT_NETWORK,
        "last_wallet": str(data.get("last_wallet", "")).strip(),
        "contacts": contacts,
    }


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def resolve_cli_binary(config: dict[str, Any]) -> str | None:
    candidates: list[str] = []
    explicit = str(config.get("cli_path", "")).strip()
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
