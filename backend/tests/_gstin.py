"""Test helper: build GSTINs whose 15th character is a correct check digit.

The server validates the GSTN mod-36 check digit on party create / GSTIN
change, so fixtures must use checksum-valid numbers. Deliberately an
independent implementation (not imported from ``app``) so a bug in the app's
algorithm can't hide behind the same bug here.
"""

from __future__ import annotations

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = _ALPHABET.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def make_gstin(state: str, pan_like: str = "AABCX1234C", entity: str = "1") -> str:
    """``make_gstin("27", "AABCM1234C")`` -> ``"27AABCM1234C1Z" + check digit``."""
    first14 = f"{state}{pan_like}{entity}Z".upper()
    assert len(first14) == 14, first14
    return first14 + gstin_check_digit(first14)
