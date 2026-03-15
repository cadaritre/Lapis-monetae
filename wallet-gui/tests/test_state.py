"""Smoke tests for wallet_app.state — WalletState transitions and gates."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wallet_app.state import WalletState


class TestWalletState:
    def _make(self) -> WalletState:
        ws = WalletState(network="mainnet")
        ws.cli_binary = "/fake/cli"
        return ws

    def test_initial_state(self) -> None:
        ws = self._make()
        assert ws.wallet_open is False
        assert ws.busy is False
        assert ws.network == "mainnet"

    def test_open_wallet(self) -> None:
        ws = self._make()
        ws.open_wallet("my_wallet")
        assert ws.wallet_open is True
        assert ws.wallet_name == "my_wallet"

    def test_close_wallet(self) -> None:
        ws = self._make()
        ws.open_wallet("w1")
        ws.close_wallet()
        assert ws.wallet_open is False

    def test_set_busy(self) -> None:
        ws = self._make()
        ws.set_busy(True)
        assert ws.busy is True
        ws.set_busy(False)
        assert ws.busy is False

    def test_can_run_action_when_idle(self) -> None:
        ws = self._make()
        ok, reason = ws.can_run_action()
        assert ok is True
        assert reason == ""

    def test_can_run_action_when_busy(self) -> None:
        ws = self._make()
        ws.set_busy(True)
        ok, reason = ws.can_run_action()
        assert ok is False
        assert "wait" in reason.lower()

    def test_can_send_requires_wallet(self) -> None:
        ws = self._make()
        ok, reason = ws.can_send()
        assert ok is False
        assert "wallet" in reason.lower() or "open" in reason.lower()

    def test_can_send_with_open_wallet(self) -> None:
        ws = self._make()
        ws.open_wallet("sender_wallet")
        ok, reason = ws.can_send()
        assert ok is True

    def test_set_network(self) -> None:
        ws = self._make()
        ws.set_network("testnet-10")
        assert ws.network == "testnet-10"

    def test_listener_called(self) -> None:
        ws = self._make()
        calls: list[str] = []
        ws.add_listener(lambda: calls.append("changed"))
        ws.set_busy(True)
        assert len(calls) >= 1

    def test_pill_info(self) -> None:
        ws = self._make()
        text, bg, fg = ws.pill_info()
        assert isinstance(text, str)
        assert text.strip()

    def test_node_status(self) -> None:
        ws = self._make()
        ws.set_node_status(True, True)
        assert ws.node_connected is True
        assert ws.node_synced is True
        ws.set_node_status(False, None)
        assert ws.node_connected is False
