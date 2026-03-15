from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import REPO_ROOT


def run_capture(binary: str, args: list[str], timeout_sec: int = 25) -> tuple[int, str]:
    command = [binary, *args]
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            cwd=str(REPO_ROOT),
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return 1, f"> {' '.join(command)}\nERROR: Command timed out after {timeout_sec} seconds."
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


def run_capture_timed(binary: str, args: list[str], timeout_sec: int = 25) -> tuple[int, str, float]:
    t0 = time.monotonic()
    code, out = run_capture(binary, args, timeout_sec)
    elapsed = (time.monotonic() - t0) * 1000
    return code, out, elapsed


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
    msg, _ = map_cli_error_action(exit_code, output)
    return msg


def map_cli_error_action(exit_code: int, output: str) -> tuple[str, str | None]:
    """Return (friendly_message, suggested_action_key | None)."""
    text = output.lower()
    if exit_code == 0:
        return "", None
    if "please open a wallet" in text or "open a wallet before" in text or "wallet is not open" in text:
        return "Open a wallet first.", "open_wallet"
    if "wallet secret" in text and "required" in text:
        return "Wallet password is required.", None
    if "insufficient funds" in text:
        return "Insufficient funds for this transaction.", None
    if "network" in text and "select" in text:
        return "Select a network first.", "select_network"
    if "syncing" in text:
        return "Node is still syncing. Please wait.", "wait_sync"
    if "invalid prefix" in text or "checksum" in text:
        return "Destination address is invalid.", None
    if "unable to connect" in text or "ping error" in text:
        return "Node/RPC connection failed.", "check_node"
    if "timed out" in text:
        return "Command timed out. Open a wallet or try again.", None
    return "Command failed. Check output details.", None


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


@dataclass
class NodeRichInfo:
    """Parsed node info for debug/status display."""
    daa_score: str
    peers: str
    tip_hash: str
    raw_dag: str
    raw_peers: str
    latency_ms: float = 0.0
    header_count: str = ""
    block_count: str = ""
    difficulty: str = ""
    network_name: str = ""


def parse_node_rich_info(list_output: str, rpc_dag_output: str = "",
                         rpc_peers_output: str = "",
                         latency_ms: float = 0.0) -> NodeRichInfo:
    daa_score = ""
    peers = ""
    tip_hash = ""
    header_count = ""
    block_count = ""
    difficulty = ""
    network_name = ""
    raw_dag = (rpc_dag_output or list_output)[:400]
    raw_peers = (rpc_peers_output or "")[:300]

    dag = rpc_dag_output or list_output
    m = re.search(r"virtual_daa_score[\"']?\s*:\s*(\d+)", dag, re.IGNORECASE)
    if m:
        daa_score = m.group(1)
    tip_m = re.search(r"tip_hashes[\"']?\s*:\s*\[(.*?)\]", dag, re.DOTALL | re.IGNORECASE)
    if tip_m:
        inner = tip_m.group(1).strip()
        first_hash = re.search(r"[\"']?([a-fA-F0-9]{8,64})[\"']?", inner)
        if first_hash:
            h = first_hash.group(1)
            tip_hash = f"{h[:8]}...{h[-8:]}" if len(h) >= 20 else h
    peer_m = re.search(r"(?:peer_info|active_peers|peers)[\"']?\s*:\s*(\d+)", rpc_peers_output or dag, re.IGNORECASE)
    if peer_m:
        peers = peer_m.group(1)
    elif "GetConnectedPeerInfoResponse" in (rpc_peers_output or ""):
        count = len(re.findall(r"RpcPeerInfo\s*\{", rpc_peers_output or ""))
        peers = str(count) if count else ""

    hc = re.search(r"header_count[\"']?\s*:\s*(\d+)", dag, re.IGNORECASE)
    if hc:
        header_count = hc.group(1)
    bc = re.search(r"block_count[\"']?\s*:\s*(\d+)", dag, re.IGNORECASE)
    if bc:
        block_count = bc.group(1)
    diff = re.search(r"difficulty[\"']?\s*:\s*([\d.eE+\-]+)", dag, re.IGNORECASE)
    if diff:
        difficulty = diff.group(1)
    nn = re.search(r"network_name[\"']?\s*:\s*[\"']?([\w-]+)", dag, re.IGNORECASE)
    if nn:
        network_name = nn.group(1)

    return NodeRichInfo(
        daa_score=daa_score, peers=peers, tip_hash=tip_hash,
        raw_dag=raw_dag, raw_peers=raw_peers,
        latency_ms=latency_ms, header_count=header_count,
        block_count=block_count, difficulty=difficulty, network_name=network_name,
    )


def contains_txid(text: str) -> bool:
    return re.search(r"\b[a-fA-F0-9]{64}\b", text) is not None
