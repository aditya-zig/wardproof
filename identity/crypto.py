"""Keyed HMAC pseudonymization and interval-preserving date shifting.

No lookup tables or raw secrets are ever written to disk.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (no I, L, O, U)


def _as_secret_bytes(secret: bytes | str) -> bytes:
    raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if not raw:
        raise ValueError("secret must be non-empty")
    return raw


def derive_pseudonym(cluster_key: str, secret: bytes | str, length: int = 10) -> str:
    """Derive a non-reversible, secret-keyed pseudonym from a canonical cluster key."""
    if length < 6 or length > 24:
        raise ValueError("length must be between 6 and 24")
    key = _as_secret_bytes(secret)
    digest = hmac.new(key, b"psn|" + cluster_key.encode("utf-8"), hashlib.sha256).digest()
    val = int.from_bytes(digest[:16], "big")
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[val & 31])
        val >>= 5
    return "PSN-" + "".join(chars)


def derive_date_offset(cluster_key: str, secret: bytes | str, max_days: int = 180) -> int:
    """Derive a deterministic, non-zero per-patient date shift in [-max_days, +max_days]."""
    if max_days < 1:
        raise ValueError("max_days must be positive")
    key = _as_secret_bytes(secret)
    digest = hmac.new(key, b"shift|" + cluster_key.encode("utf-8"), hashlib.sha256).digest()
    span = 2 * max_days
    offset = (int.from_bytes(digest[:8], "big") % span) - max_days
    return offset if offset != 0 else 1


def shift_date(value: dt.date, offset_days: int) -> dt.date:
    """Shift a calendar date by ``offset_days``."""
    return value + dt.timedelta(days=offset_days)


def shift_iso_date(iso_date: str, offset_days: int) -> str:
    """Shift an ISO-8601 date string (YYYY-MM-DD) by ``offset_days``."""
    parsed = dt.date.fromisoformat(iso_date.strip())
    return shift_date(parsed, offset_days).isoformat()


def shift_stay(admit: dt.date, discharge: dt.date, offset_days: int) -> tuple[dt.date, dt.date]:
    """Shift an admission/discharge pair by the same offset so stay length is preserved."""
    return shift_date(admit, offset_days), shift_date(discharge, offset_days)
