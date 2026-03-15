"""Smoke tests for wallet_app.cli_bridge — parsing and error mapping."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wallet_app.cli_bridge import (
    is_wallet_open_from_output,
    map_cli_error_action,
    parse_node_rich_info,
    parse_node_sync_hint,
)


class TestParseNodeSyncHint:
    def test_disconnected(self) -> None:
        connected, synced = parse_node_sync_hint("wallet is not connected to the network")
        assert connected is False
        assert synced is None

    def test_syncing(self) -> None:
        connected, synced = parse_node_sync_hint("node is currently syncing, please wait")
        assert connected is True
        assert synced is False

    def test_connected_and_synced(self) -> None:
        connected, synced = parse_node_sync_hint("account #0\n  balance: 100 LMT")
        assert connected is True
        assert synced is True


class TestMapCliErrorAction:
    def test_success(self) -> None:
        msg, key = map_cli_error_action(0, "ok")
        assert msg == ""
        assert key is None

    def test_wallet_not_open(self) -> None:
        msg, key = map_cli_error_action(1, "please open a wallet first")
        assert "Open a wallet" in msg
        assert key == "open_wallet"

    def test_insufficient_funds(self) -> None:
        msg, key = map_cli_error_action(1, "insufficient funds for this operation")
        assert "Insufficient" in msg
        assert key is None

    def test_network_select(self) -> None:
        msg, key = map_cli_error_action(1, "please select a network first")
        assert key == "select_network"

    def test_connection_failed(self) -> None:
        msg, key = map_cli_error_action(1, "unable to connect to node")
        assert key == "check_node"

    def test_generic_error(self) -> None:
        msg, key = map_cli_error_action(1, "something unknown happened")
        assert "Check output" in msg
        assert key is None


class TestIsWalletOpenFromOutput:
    def test_open(self) -> None:
        assert is_wallet_open_from_output(0, "account list:\n  #0 default") is True

    def test_not_open(self) -> None:
        assert is_wallet_open_from_output(0, "please open a wallet first") is False

    def test_error_code(self) -> None:
        assert is_wallet_open_from_output(1, "account list") is False


class TestParseNodeRichInfo:
    def test_basic_parsing(self) -> None:
        dag_output = (
            'GetBlockDagInfoResponse { network_name: "kaspa-mainnet", '
            'block_count: 12345, header_count: 12346, '
            'tip_hashes: ["aabbccdd11223344aabbccdd11223344aabbccdd11223344aabbccdd11223344"], '
            'difficulty: 1.234e+10, '
            'virtual_daa_score: 99999 }'
        )
        peers_output = (
            'GetConnectedPeerInfoResponse { peer_info: [] }'
        )
        ri = parse_node_rich_info("", dag_output, peers_output, latency_ms=42.5)
        assert ri.daa_score == "99999"
        assert ri.block_count == "12345"
        assert ri.header_count == "12346"
        assert ri.difficulty == "1.234e+10"
        assert ri.network_name == "kaspa-mainnet"
        assert ri.latency_ms == 42.5
        assert "aabbccdd" in ri.tip_hash

    def test_empty_input(self) -> None:
        ri = parse_node_rich_info("")
        assert ri.daa_score == ""
        assert ri.peers == ""
        assert ri.tip_hash == ""
        assert ri.latency_ms == 0.0

    def test_peer_counting(self) -> None:
        peers = "GetConnectedPeerInfoResponse { peer_info: [RpcPeerInfo { }, RpcPeerInfo { }, RpcPeerInfo { }] }"
        ri = parse_node_rich_info("", "", peers)
        assert ri.peers == "3"
