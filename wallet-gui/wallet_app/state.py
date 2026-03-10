"""Wallet state manager — tracks CLI availability, wallet open/closed status,
and network selection.  Provides gate methods that the GUI consults before
allowing critical actions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import DEFAULT_NETWORK, resolve_cli_binary


@dataclass
class WalletState:
    """Centralised runtime state for the wallet GUI."""

    cli_binary: str | None = None
    wallet_open: bool = False
    wallet_name: str = ""
    network: str = DEFAULT_NETWORK
    busy: bool = False

    _listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)

    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in self._listeners:
            cb()

    # ── Mutators ──

    def refresh_cli(self, config: dict[str, object]) -> None:
        self.cli_binary = resolve_cli_binary(config)
        self._notify()

    def open_wallet(self, name: str) -> None:
        self.wallet_open = True
        self.wallet_name = name
        self._notify()

    def close_wallet(self) -> None:
        self.wallet_open = False
        self.wallet_name = ""
        self._notify()

    def set_network(self, network: str) -> None:
        self.network = network or DEFAULT_NETWORK
        self._notify()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._notify()

    # ── Gate checks ──

    @property
    def cli_available(self) -> bool:
        return self.cli_binary is not None

    def can_run_action(self) -> tuple[bool, str]:
        """Return (allowed, reason) for running a general CLI action."""
        if self.busy:
            return False, "Please wait for the current command to finish"
        if not self.cli_available:
            return False, "CLI binary not found — set a path first"
        return True, ""

    def can_send(self) -> tuple[bool, str]:
        """Return (allowed, reason) for sending LMT or transferring."""
        ok, reason = self.can_run_action()
        if not ok:
            return ok, reason
        if not self.wallet_open:
            return False, "Open a wallet before sending"
        return True, ""

    def status_text(self) -> str:
        parts: list[str] = []
        if self.cli_binary:
            parts.append(f"CLI: {self.cli_binary}")
        else:
            parts.append("CLI: not found")
        parts.append(f"Network: {self.network}")
        if self.wallet_open:
            parts.append(f"Wallet: {self.wallet_name}")
        else:
            parts.append("Wallet: none")
        return "  \u2502  ".join(parts)

    def pill_info(self) -> tuple[str, str, str]:
        """Return (text, bg, fg) for the status pill."""
        if self.busy:
            return " \u25CF  RUNNING\u2026 ", "#fef3c7", "#d97706"
        if not self.cli_available:
            return " \u25CF  CLI MISSING ", "#fee2e2", "#dc2626"
        if self.wallet_open:
            return " \u25CF  WALLET OPEN ", "#dcfce7", "#16a34a"
        return " \u25CF  READY ", "#dbeafe", "#2563eb"
