"""Address validation with real bech32 (CashAddr-style) checksum,
amount/fee parsing, and network-aware prefix checking.

Polymod constants and charset taken from crypto/addresses/src/bech32.rs
which follows https://bch.info/en/specifications (BCH codes).
"""
from __future__ import annotations

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
CHARSET_MAP = {c: i for i, c in enumerate(CHARSET)}
CHARSET_SET = frozenset(CHARSET)
MIN_ADDRESS_LEN = 24

_GENERATORS = (0x98f2bc8e61, 0x79b76d99e2, 0xf33e5fb3c4, 0xae2eabe2a8, 0x1e4f43e470)

NETWORK_PREFIX = {
    "mainnet": "lmt",
    "testnet-10": "lmttest",
    "testnet-11": "lmttest",
}


def _polymod(values: list[int]) -> int:
    """CashAddr-style BCH polymod over a sequence of 5-bit values."""
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07_FFFF_FFFF) << 5) ^ d
        for i in range(5):
            if c0 & (1 << i):
                c ^= _GENERATORS[i]
    return c ^ 1


def _verify_checksum(prefix: str, payload_chars: str) -> bool:
    """Verify the bech32 checksum of a decoded payload string.

    The prefix bytes are masked to 5 bits, followed by a zero separator,
    then the full payload (data + 8-char checksum) decoded to 5-bit values.
    A valid address produces polymod == 0.
    """
    prefix_5bit = [b & 0x1F for b in prefix.encode("ascii")]
    try:
        payload_5bit = [CHARSET_MAP[c] for c in payload_chars]
    except KeyError:
        return False
    return _polymod(prefix_5bit + [0] + payload_5bit) == 0


class AddressValidationResult:
    """Structured result for address validation with a clear error message."""

    __slots__ = ("valid", "error")

    def __init__(self, valid: bool, error: str = "") -> None:
        self.valid = valid
        self.error = error

    def __bool__(self) -> bool:
        return self.valid


def validate_address(address: str, network: str) -> AddressValidationResult:
    """Full validation of an LMT address: format, prefix, charset, and checksum."""
    normalized = address.strip().lower()

    if len(normalized) < MIN_ADDRESS_LEN:
        return AddressValidationResult(False, "Address is too short")

    if ":" not in normalized:
        return AddressValidationResult(False, "Address must contain a ':' separator")

    prefix, payload = normalized.split(":", 1)
    expected_prefix = NETWORK_PREFIX.get(network, "lmt")

    if prefix != expected_prefix:
        return AddressValidationResult(
            False,
            f"Wrong prefix '{prefix}:' — expected '{expected_prefix}:' for {network}",
        )

    if not payload:
        return AddressValidationResult(False, "Address payload is empty")

    bad_chars = set(payload) - CHARSET_SET
    if bad_chars:
        return AddressValidationResult(
            False,
            f"Invalid characters in address: {''.join(sorted(bad_chars))}",
        )

    if not _verify_checksum(prefix, payload):
        return AddressValidationResult(False, "Address checksum is invalid")

    return AddressValidationResult(True)


def parse_positive_amount(value: str) -> float | None:
    """Parse a string as a positive (> 0) floating-point amount."""
    try:
        amount = float(value.strip())
    except ValueError:
        return None
    return amount if amount > 0 else None


def parse_nonnegative_fee(value: str) -> float | None:
    """Parse a string as a non-negative (>= 0) fee. Empty string maps to 0."""
    raw = value.strip()
    if raw == "":
        return 0.0
    try:
        fee = float(raw)
    except ValueError:
        return None
    return fee if fee >= 0 else None
