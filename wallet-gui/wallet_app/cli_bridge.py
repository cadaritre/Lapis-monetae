from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .config import REPO_ROOT


def run_capture(binary: str, args: list[str]) -> tuple[int, str]:
    command = [binary, *args]
    try:
        result = subprocess.run(command, text=True, capture_output=True, cwd=str(REPO_ROOT))
    except OSError as err:
        return 1, f"> {' '.join(command)}\nERROR: {err}"

    text = f"> {' '.join(command)}\n"
    if result.stdout:
        text += result.stdout
    if result.stderr:
        text += "\n[stderr]\n" + result.stderr
    if not result.stdout and not result.stderr:
        text += "(no output)\n"
    return result.returncode, text


def launch_interactive(binary: str, args: list[str]) -> tuple[bool, str]:
    command = [binary, *args]
    try:
        if os.name == "nt":
            subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=str(REPO_ROOT))
            return True, f"Launched interactive command in new console: {' '.join(command)}"
        subprocess.Popen(command, cwd=str(REPO_ROOT))
        return True, f"Launched interactive command: {' '.join(command)}"
    except OSError as err:
        return False, f"ERROR launching interactive command: {err}"


def map_cli_error(exit_code: int, output: str) -> str:
    text = output.lower()
    if exit_code == 0:
        return ""
    if "please open a wallet" in text or "open a wallet before" in text:
        return "Open a wallet first."
    if "wallet secret" in text and "required" in text:
        return "Wallet password is required."
    if "insufficient funds" in text:
        return "Insufficient funds for this transaction."
    if "network" in text and "select" in text:
        return "Select a network first."
    if "syncing" in text:
        return "Node is still syncing. Please wait."
    if "invalid prefix" in text or "checksum" in text:
        return "Destination address is invalid."
    if "unable to connect" in text or "ping error" in text:
        return "Node/RPC connection failed."
    return "Command failed. Check output details."


def is_wallet_open_from_output(exit_code: int, output: str) -> bool:
    text = output.lower()
    if exit_code != 0:
        return False
    if "please open a wallet" in text or "wallet is not open" in text:
        return False
    return True


def parse_node_sync_hint(list_output: str) -> tuple[bool, bool | None]:
    """Return (connected, synced_or_none)."""
    text = list_output.lower()
    if "wallet is not connected to the network" in text:
        return False, None
    if "is currently syncing" in text:
        return True, False
    return True, True


def contains_txid(text: str) -> bool:
    return re.search(r"\b[a-fA-F0-9]{64}\b", text) is not None
