"""Smoke tests for wallet_app.tx_history — parse_history_output."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wallet_app.tx_history import parse_history_output


class TestParseHistoryOutput:
    def test_parses_txids(self) -> None:
        sample = (
            "> history list 30\n"
            "  received  +100.50000000 LMT  "
            "aabbccdd11223344aabbccdd11223344aabbccdd11223344aabbccdd11223344  confirmed\n"
            "  sent      -50.00000000 LMT  "
            "11223344aabbccdd11223344aabbccdd11223344aabbccdd11223344aabbccdd  pending\n"
            "Exit code: 0\n"
        )
        rows = parse_history_output(sample)
        assert len(rows) == 2
        assert rows[0].direction == "in"
        assert rows[0].amount == "+100.50000000"
        assert rows[0].status == "confirmed"
        assert len(rows[0].full_txid) == 64

        assert rows[1].direction == "out"
        assert rows[1].amount == "-50.00000000"
        assert rows[1].status == "pending"

    def test_empty_output(self) -> None:
        rows = parse_history_output("")
        assert rows == []

    def test_no_txids(self) -> None:
        rows = parse_history_output("no transactions found here\n")
        assert rows == []

    def test_skips_command_line_and_exit(self) -> None:
        sample = (
            "> history list 30\n"
            "Exit code: 0\n"
        )
        rows = parse_history_output(sample)
        assert rows == []

    def test_ansi_stripped(self) -> None:
        sample = (
            "\x1b[32m  received  +10.00000000 LMT  "
            "aabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccddaabbccdd  confirmed\x1b[0m\n"
        )
        rows = parse_history_output(sample)
        assert len(rows) == 1
        assert rows[0].direction == "in"
