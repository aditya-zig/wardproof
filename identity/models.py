"""Data models for patient identity linkage and date shifting."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Evidence:
    """Normalized identifying and quasi-identifying evidence extracted from one record.

    All fields are optional except ``record_id`` and ``source_namespace``.
    Local identifiers (``local_ids``) are strictly scoped to ``source_namespace``.
    """

    record_id: str
    source_namespace: str = ""
    names: tuple[str, ...] | list[str] = field(default_factory=tuple)
    relatives: tuple[str, ...] | list[str] = field(default_factory=tuple)
    local_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    aadhaar: tuple[str, ...] | list[str] = field(default_factory=tuple)
    aadhaar_last4: tuple[str, ...] | list[str] = field(default_factory=tuple)
    abha: tuple[str, ...] | list[str] = field(default_factory=tuple)
    pan: tuple[str, ...] | list[str] = field(default_factory=tuple)
    insurance_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    emails: tuple[str, ...] | list[str] = field(default_factory=tuple)
    phones: tuple[str, ...] | list[str] = field(default_factory=tuple)
    dob: str | None = None
    age: int | None = None
    gender: str | None = None
    village: str | None = None
    district: str | None = None
    pin: str | None = None


@dataclass(frozen=True)
class LinkResult:
    """Output of the linkage boundary for a single record.

    ``pseudonym`` is ``None`` when the evidence is insufficient or ambiguous.
    ``date_offset_days`` is a deterministic, secret-keyed non-zero shift in days
    shared across all records linked to the same patient.
    """

    record_id: str
    pseudonym: str | None
    date_offset_days: int
    linked: bool
    reason: str = "linked"
