"""Canonical Indian GST state-code validation and normalisation.

All state codes are canonicalized to 2-char ALPHABETIC format (ISO 3166-2:IN,
e.g. "MH" for Maharashtra) regardless of input format. This is the canonical
form used throughout this codebase for internal comparison and storage.

Numeric GST-schedule codes (e.g. "27" from GSTIN prefix or Vyapar migration)
are converted to their alpha equivalents via a complete mapping table so that
the PoS engine's intra/inter-state comparison (`pos != seller_state`) always
operates on a single canonical format, preventing format-mixing bugs where
"27" (numeric Maharashtra) != "MH" (alpha Maharashtra) -> wrongly charged IGST
on an intra-state sale (B1 blocker).

Accepted input formats:
  - 2-char alphabetic (ISO 3166-2:IN), any case: "MH", "mh", "Mh" -> "MH"
  - 2-digit numeric (GST Council schedule): "27", "27 " (trailing space) -> "MH"
  - None or empty -> None (optional field)

Rejected (returns None -> 422 via schema field_validator):
  - Unknown codes: "XX", "ZZ", "99", "ab"
  - Any non-2-character value after stripping

CA-VALIDATED-PENDING: confirm with CA:
  - Ladakh (38 -> LA) is correctly included as of 2019 UTs Reorganisation Act.
  - Code 25 (Daman & Diu, pre-2020) mapped to DN is correct for legacy GSTINs.
  - Code 28 (old Andhra Pradesh, pre-bifurcation) mapped to AP same as 37 is
    correct for legacy GSTINs starting with 28.
  - Other Territory (97 -> OT) usage is needed for high-seas/transitional cases.
"""

from __future__ import annotations

# ── Complete numeric-code-to-canonical-alpha mapping ──────────────────────
# Covers all codes assigned by the GST Council (01-38, 97).
# Code 38 = Ladakh (carved out of J&K in 2019); included per S1 requirement.
# Code 25 (Daman & Diu) merged with code 26 in 2020 -> both map to DN.
# Code 28 (old AP, pre-bifurcation) and 37 (new AP) both map to AP.
_NUMERIC_TO_ALPHA: dict[str, str] = {
    "01": "JK",  # Jammu & Kashmir
    "02": "HP",  # Himachal Pradesh
    "03": "PB",  # Punjab
    "04": "CH",  # Chandigarh
    "05": "UK",  # Uttarakhand
    "06": "HR",  # Haryana
    "07": "DL",  # Delhi (National Capital Territory)
    "08": "RJ",  # Rajasthan
    "09": "UP",  # Uttar Pradesh
    "10": "BR",  # Bihar
    "11": "SK",  # Sikkim
    "12": "AR",  # Arunachal Pradesh
    "13": "NL",  # Nagaland
    "14": "MN",  # Manipur
    "15": "MZ",  # Mizoram
    "16": "TR",  # Tripura
    "17": "ML",  # Meghalaya
    "18": "AS",  # Assam
    "19": "WB",  # West Bengal
    "20": "JH",  # Jharkhand
    "21": "OD",  # Odisha
    "22": "CT",  # Chhattisgarh
    "23": "MP",  # Madhya Pradesh
    "24": "GJ",  # Gujarat
    "25": "DN",  # Daman & Diu (pre-2020; merged with Dadra NH as DN, code 26)
    "26": "DN",  # Dadra & Nagar Haveli and Daman & Diu (merged UT, 2020)
    "27": "MH",  # Maharashtra
    "28": "AP",  # Andhra Pradesh (old code, pre-bifurcation; same state as 37)
    "29": "KA",  # Karnataka
    "30": "GA",  # Goa
    "31": "LD",  # Lakshadweep
    "32": "KL",  # Kerala
    "33": "TN",  # Tamil Nadu
    "34": "PY",  # Puducherry
    "35": "AN",  # Andaman & Nicobar Islands
    "36": "TG",  # Telangana
    "37": "AP",  # Andhra Pradesh (new code, post-bifurcation 2014)
    "38": "LA",  # Ladakh (UT, carved out of J&K 2019; S1 fix)
    "97": "OT",  # Other Territory
}

# ── Canonical alphabetic set ───────────────────────────────────────────────
# Output values of _NUMERIC_TO_ALPHA plus OR (legacy Odisha alias).
# OR is retained so Odisha data stored as "OR" (legacy abbreviation) is
# accepted; numeric "21" canonicalizes to "OD" (current standard).
_VALID_ALPHA: frozenset[str] = frozenset(
    set(_NUMERIC_TO_ALPHA.values())
    | {
        "OR",  # Odisha legacy abbreviation (numeric 21 -> OD is canonical)
    }
)

# Combined membership set exposed for external callers.
VALID_GST_STATE_CODES: frozenset[str] = frozenset(_NUMERIC_TO_ALPHA) | _VALID_ALPHA


def normalize_state_code(raw: str | None) -> str | None:
    """Canonicalize an Indian GST state code to its 2-char alphabetic form.

    Steps:
      1. Strip whitespace and uppercase the input.
      2. If the result is a numeric code (in _NUMERIC_TO_ALPHA), map it to alpha.
      3. If the result is already a valid alpha code, return it.
      4. Otherwise return None (invalid code).

    None / empty string -> None (caller treats as "field absent").

    Examples::

        normalize_state_code("27 ")  # "MH"  (numeric Maharashtra + trailing space)
        normalize_state_code("mh")   # "MH"  (lowercase alpha)
        normalize_state_code("MH")   # "MH"  (canonical form)
        normalize_state_code("27")   # "MH"  (numeric)
        normalize_state_code("29")   # "KA"  (numeric Karnataka)
        normalize_state_code("38")   # "LA"  (Ladakh, S1 fix)
        normalize_state_code("97")   # "OT"  (Other Territory)
        normalize_state_code("XX")   # None  (invalid)
        normalize_state_code("99")   # None  (not a valid numeric code)
        normalize_state_code(None)   # None  (optional field)
        normalize_state_code("")     # None  (optional field)
    """
    if raw is None:
        return None
    stripped = raw.strip().upper()
    if not stripped:
        return None
    # Numeric code -> canonical alpha (covers Vyapar-migrated data, GSTIN prefixes)
    if stripped in _NUMERIC_TO_ALPHA:
        return _NUMERIC_TO_ALPHA[stripped]
    # Already a valid alpha code (covers codebase-native and ISO 3166-2:IN data)
    if stripped in _VALID_ALPHA:
        return stripped
    return None


def is_valid_state_code(code: str) -> bool:
    """Return True iff *code* is recognised after normalisation.

    Equivalent to ``normalize_state_code(code) is not None``.
    """
    return normalize_state_code(code) is not None


__all__ = [
    "VALID_GST_STATE_CODES",
    "is_valid_state_code",
    "normalize_state_code",
]
