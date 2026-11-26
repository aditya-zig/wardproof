"""Cross-script patient linkage, HMAC pseudonymization, date shifting, and generalization."""

from identity.linkage import (
    IdentityEvidence,
    PatientLinkageIndex,
    generalize_age,
    generalize_pin,
    normalize_name,
    normalize_phone,
    shift_date_string,
)

__all__ = [
    "IdentityEvidence",
    "PatientLinkageIndex",
    "generalize_age",
    "generalize_pin",
    "normalize_name",
    "normalize_phone",
    "shift_date_string",
]
