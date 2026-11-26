"""WardProof patient identity linkage, date shifting, and generalization."""

from .crypto import (
    derive_date_offset,
    derive_pseudonym,
    shift_date,
    shift_iso_date,
    shift_stay,
)
from .linkage import (
    IdentityEvidence,
    PatientLinkageIndex,
    generalize_age,
    generalize_pin,
    normalize_name,
    shift_date_string,
)
from .linker import resolve_batch, resolve_record
from .models import Evidence, LinkResult
from .normalize import (
    normalize_aadhaar,
    normalize_abha,
    normalize_dob,
    normalize_email,
    normalize_gender,
    normalize_local_id,
    normalize_name_tokens,
    normalize_pan,
    normalize_phone,
    normalize_place,
    phonetic_fold,
    phonetic_name_tokens,
    transliterate_text,
)

__all__ = [
    "Evidence",
    "IdentityEvidence",
    "LinkResult",
    "PatientLinkageIndex",
    "derive_date_offset",
    "derive_pseudonym",
    "generalize_age",
    "generalize_pin",
    "normalize_aadhaar",
    "normalize_abha",
    "normalize_dob",
    "normalize_email",
    "normalize_gender",
    "normalize_local_id",
    "normalize_name",
    "normalize_name_tokens",
    "normalize_pan",
    "normalize_phone",
    "normalize_place",
    "phonetic_fold",
    "phonetic_name_tokens",
    "resolve_batch",
    "resolve_record",
    "shift_date",
    "shift_date_string",
    "shift_iso_date",
    "shift_stay",
    "transliterate_text",
]
