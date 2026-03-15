"""Smoke tests for wallet_app.validators — address, amount, fee parsing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wallet_app.validators import (
    AddressValidationResult,
    parse_nonnegative_fee,
    parse_positive_amount,
    validate_address,
)


class TestParsePositiveAmount:
    def test_valid_integer(self) -> None:
        assert parse_positive_amount("100") == 100.0

    def test_valid_float(self) -> None:
        assert parse_positive_amount("0.5") == 0.5

    def test_zero_returns_none(self) -> None:
        assert parse_positive_amount("0") is None

    def test_negative_returns_none(self) -> None:
        assert parse_positive_amount("-5") is None

    def test_empty_returns_none(self) -> None:
        assert parse_positive_amount("") is None

    def test_non_numeric_returns_none(self) -> None:
        assert parse_positive_amount("abc") is None

    def test_whitespace_stripped(self) -> None:
        assert parse_positive_amount("  42  ") == 42.0


class TestParseNonnegativeFee:
    def test_empty_returns_zero(self) -> None:
        assert parse_nonnegative_fee("") == 0.0

    def test_valid_fee(self) -> None:
        assert parse_nonnegative_fee("0.001") == 0.001

    def test_zero_is_valid(self) -> None:
        assert parse_nonnegative_fee("0") == 0.0

    def test_negative_returns_none(self) -> None:
        assert parse_nonnegative_fee("-1") is None

    def test_non_numeric_returns_none(self) -> None:
        assert parse_nonnegative_fee("bad") is None


class TestValidateAddress:
    def test_too_short(self) -> None:
        result = validate_address("lmt:abc", "mainnet")
        assert not result
        assert "short" in result.error.lower()

    def test_missing_separator(self) -> None:
        result = validate_address("lmtabcdefghijklmnopqrstuvwxyz", "mainnet")
        assert not result

    def test_wrong_prefix(self) -> None:
        result = validate_address("lmttest:" + "q" * 60, "mainnet")
        assert not result
        assert "prefix" in result.error.lower()

    def test_empty_payload(self) -> None:
        result = validate_address("lmt:", "mainnet")
        assert not result

    def test_invalid_chars(self) -> None:
        result = validate_address("lmt:" + "!" * 30, "mainnet")
        assert not result
        assert "character" in result.error.lower()

    def test_result_is_truthy_on_success(self) -> None:
        r = AddressValidationResult(True)
        assert r
        assert r.valid
        assert r.error == ""

    def test_result_is_falsy_on_failure(self) -> None:
        r = AddressValidationResult(False, "bad")
        assert not r
        assert r.error == "bad"
