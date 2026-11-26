"""Multilingual clinical text sanitization and meaning preservation.

Standard-library Python only. Never logs raw matched PII strings.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
import re
from typing import Any, Mapping
import unicodedata

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClinicalAssertion:
    """A clinical statement with its preserved assertion polarity."""

    text: str
    polarity: str  # "positive" | "negated" | "allergy" | "family_history"


@dataclass(frozen=True)
class SanitizationResult:
    """Cleaned text plus aggregate detection counts (never raw PII matches)."""

    text: str
    counts: dict[str, int]
    language: str
    assertions: tuple[ClinicalAssertion, ...] = ()


# ---------------------------------------------------------------------------
# Language detection (English / Hindi / Hinglish)
# ---------------------------------------------------------------------------

_DEVA_RE = re.compile(r"[\u0900-\u097F]")
_HINGLISH_MARKERS = frozenset(
    {
        "sahab",
        "saheb",
        "bukhar",
        "dard",
        "nahi",
        "nahin",
        "hai",
        "hain",
        "tha",
        "thi",
        "the",
        "ka",
        "ki",
        "ke",
        "ko",
        "ne",
        "se",
        "mein",
        "raat",
        "theek",
        "neend",
        "papa",
        "mummy",
        "bhi",
        "aur",
        "koi",
        "saans",
        "phoolna",
        "diya",
        "li",
        "khansi",
        "chakkar",
        "kamzori",
        "dawai",
        "goli",
        "din",
        "subah",
        "shaam",
    }
)


def detect_language(text: str) -> str:
    """Classify clinical text into 'hindi', 'hinglish', or 'english'."""
    if not text or not text.strip():
        return "english"
    if _DEVA_RE.search(text):
        return "hindi"
    tokens = re.findall(r"[a-zA-Z]+", text.casefold())
    hits = sum(1 for tok in tokens if tok in _HINGLISH_MARKERS)
    if hits >= 2:
        return "hinglish"
    return "english"


# ---------------------------------------------------------------------------
# Protected medical spans (eponyms, clinical abbreviations, doses/vitals)
# ---------------------------------------------------------------------------

_EPONYM_RE = re.compile(
    r"\b(?:"
    r"Addison(?:'s|s)?\s+disease|"
    r"Parkinson(?:'s|s)?\s+disease|"
    r"Alzheimer(?:'s|s)?\s+disease|"
    r"Crohn(?:'s|s)?\s+disease|"
    r"Hodgkin(?:'s|s)?\s+lymphoma|"
    r"Non-Hodgkin(?:'s|s)?\s+lymphoma|"
    r"Graves(?:'|’)?\s+disease|"
    r"Bell(?:'s|s)?\s+palsy|"
    r"Cushing(?:'s|s)?\s+syndrome|"
    r"Hashimoto(?:'s|s)?\s+thyroiditis|"
    r"Kawasaki\s+disease|"
    r"Guillain[- ]Barre\s+syndrome|"
    r"Marfan(?:'s|s)?\s+syndrome|"
    r"Down(?:'s|s)?\s+syndrome|"
    r"Reye(?:'s|s)?\s+syndrome|"
    r"Wilson(?:'s|s)?\s+disease|"
    r"Raynaud(?:'s|s)?\s+phenomenon|"
    r"Babinski(?:'s|s)?\s+sign|"
    r"Murphy(?:'s|s)?\s+sign|"
    r"Kernig(?:'s|s)?\s+sign|"
    r"Brudzinski(?:'s|s)?\s+sign|"
    r"Pott(?:'s|s)?\s+spine|"
    r"Apgar\s+score|"
    r"Glasgow\s+Coma\s+Scale"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Structured PII patterns
# ---------------------------------------------------------------------------

_ABHA_NUM_RE = re.compile(r"\b\d{2}-\d{4}-\d{4}-\d{4}\b")
_ABHA_ADDR_RE = re.compile(r"\b[A-Za-z0-9._-]+@(?:abdm|ndhm|sbx)\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_AADHAAR_SPACED_RE = re.compile(r"\b[2-9]\d{3}[\s-]\d{4}[\s-]\d{4}\b")
_AADHAAR_COMPACT_RE = re.compile(r"\b[2-9]\d{11}\b")
_AADHAAR_MASKED_RE = re.compile(r"\b[Xx*]{4}[\s-][Xx*]{4}[\s-]\d{4}\b")
_AADHAAR_LABELED_RE = re.compile(
    r"((?:Aadhaar|Aadhar|UID|आधार)\s*[:\-]?\s*)(?:\d{4}[\s-]?\d{4}[\s-]?\d{4}|[Xx*]{4}[\s-]?[Xx*]{4}[\s-]?\d{4})",
    re.IGNORECASE,
)

_PHONE_LABELED_RE = re.compile(
    r"((?:Mob(?:ile)?|Ph(?:one)?|Tel|Contact|मोबाइल|फोन)\s*[:\-]?\s*)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b",
    re.IGNORECASE,
)
_PHONE_BARE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")

_INSURANCE_LABELED_RE = re.compile(
    r"((?:Insurance\s*(?:ID|No\.?)|Policy\s*(?:ID|No\.?)|TPA\s*(?:ID|No\.?)|PMJAY\s*(?:ID|No\.?)|ESIC\s*(?:ID|No\.?))\s*[:\-]?\s*)"
    r"([A-Za-z0-9][A-Za-z0-9/-]{3,24})",
    re.IGNORECASE,
)

_MRN_LABELED_RE = re.compile(
    r"((?:Reg\.?\s*No\.?|UHID|MRN|IPD(?:\s*No\.?)?|OPD\s*No\.?|Sample\s*ID|Adm(?:ission)?\s*(?:No\.?|ID)|पंजीकरण(?:\s*संख्या)?)\s*[:\-]?\s*)"
    r"([A-Za-z0-9][A-Za-z0-9/-]{3,24})",
    re.IGNORECASE,
)
_MRN_PREFIXED_RE = re.compile(
    r"\b(?:SNJ|JJH|ADM|IPD|IP|UHID|MRN)[/-]?(?:\d{2,4}[/-])?\d{3,12}\b"
)

_DOB_LABELED_RE = re.compile(
    r"((?:DOB|D\.O\.B\.|Date\s+of\s+Birth|जन्म\s*तिथि)\s*[:\-]?\s*)(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)

_PIN_LABELED_RE = re.compile(
    r"((?:PIN(?:\s*Code)?|Pincode|पिन)\s*[:\-]?\s*)(\d{6})\b",
    re.IGNORECASE,
)
_PIN_COMMA_RE = re.compile(r"(,\s*)(\d{6})\b")

# ---------------------------------------------------------------------------
# Clinician vs Relative / Unverified Dr. patterns
# ---------------------------------------------------------------------------

_CREDENTIAL_SUFFIX_RE = re.compile(
    r"^\s*(?:,?\s*(?:MBBS|MD|MS|DM|MCh|DNB|BDS|MDS|BAMS|BHMS|FRCS|FACS|PhD)\b|\([^)]*(?:MD|MS|MBBS|Medicine|Surgery|Pulmonary|Cardio|Ortho|Pediatrics|Gynae)[^)]*\))",
    re.IGNORECASE,
)
_CLINICIAN_ROLE_PREFIX_RE = re.compile(
    r"(?:Consulting\s+Physician|Attending\s+Physician|Treating\s+(?:Doctor|Physician)|Ref\.?\s*Doctor|Consultant|Signed\s+by|चिकित्सक|डॉक्टर)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
_NON_CLINICIAN_PREFIX_RE = re.compile(
    r"(?:Patient(?:\s*Name)?|Name|Pt\.?|S/o|D/o|W/o|F/o|M/o|C/O|Care\s+of|Attendant(?:\s*\([^)]*)?|Father|Mother|Husband|Wife|Spouse|नाम)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
_DOCTOR_LATIN_RE = re.compile(
    r"\bDr\.?[ \t]+([A-Z][a-zA-Z.'-]*(?:[ \t]+[A-Z][a-zA-Z.'-]*){0,3})"
)
_DOCTOR_DEVA_RE = re.compile(r"डॉ\.?[ \t]+([\u0900-\u097F]+(?:[ \t]+[\u0900-\u097F]+){0,2})")

# ---------------------------------------------------------------------------
# Names, Relatives, and Addresses (English / Hindi / Hinglish)
# ---------------------------------------------------------------------------

_PATIENT_LABEL_LATIN_RE = re.compile(
    r"((?:Patient[ \t]*Name|Patient|Pt\.?|Name)[ \t]*[:\-][ \t]*)"
    r"([A-Za-z][A-Za-z.'-]*(?:[ \t]+[A-Za-z][A-Za-z.'-]*){0,3})"
    r"(?=[ \t]+(?:Age|Sex|Gender|Reg|UHID|MRN|Mob|Phone|S/o|D/o|W/o|C/O|Address)\b|[ \t]*[,;\n\r]|$)",
    re.IGNORECASE,
)
_PATIENT_LABEL_DEVA_RE = re.compile(
    r"(नाम[ \t]*[:\-][ \t]*)([\u0900-\u097F]+(?:[ \t]+[\u0900-\u097F]+){0,3})"
    r"(?=[ \t]+(?:आयु|उम्र|पता|ग्राम|मोबाइल|फोन)[ \t]*[:\-]|[ \t]*[,;\n\r]|$)"
)
_HINDI_SUBJECT_RE = re.compile(
    r"(?<![\u0900-\u097F])([\u0900-\u097F]+(?:[ \t]+[\u0900-\u097F]+){1,2})([ \t]+को[ \t]+\d+[ \t]+दिन[ \t]+से(?=\s|[।,;\n\r]|$))"
)
_HINDI_SUBJECT_STOPWORDS = frozenset({"मरीज", "रोगी", "पिता", "माता", "बच्चे"})

_HINGLISH_HONORIFIC_RE = re.compile(
    r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2})[ \t]+(?:sahab|saheb|ji|didi|bhai)\b"
)
_HINDI_HONORIFIC_RE = re.compile(
    r"(?:(?:श्री|श्रीमती|सुश्री|कुमारी)[ \t]+(?:(?!(?:को|ने|से|का|की|के)(?=\s|$))[\u0900-\u097F])+(?:[ \t]+(?:(?!(?:को|ने|से|का|की|के)(?=\s|$))[\u0900-\u097F])+){0,2}|[\u0900-\u097F]+[ \t]+(?:जी|साहब|दीदी))"
)
_INITIAL_NAME_RE = re.compile(
    r"(?<!\d[ \t])\b((?:[A-Z]\.[ \t]*){1,2}[A-Z][a-z]{1,20})\b"
)

_RELATIVE_RELATION_RE = re.compile(
    r"(\b(?:S/o|D/o|W/o|F/o|M/o)[ \t]+)([A-Z][a-zA-Z.'-]*(?:[ \t]+[A-Z][a-zA-Z.'-]*){0,3})",
    re.IGNORECASE,
)

# C/O disambiguation: medical complaints start with lowercase or known symptom words,
# whereas Care-Of starts with H.No./House or Title-Case person name.
_MEDICAL_CO_HEADS = frozenset(
    {
        "fever",
        "cough",
        "pain",
        "headache",
        "chest",
        "breathlessness",
        "dyspnea",
        "vomiting",
        "nausea",
        "diarrhea",
        "weakness",
        "dizziness",
        "rash",
        "swelling",
        "bleeding",
        "bukhar",
        "dard",
        "khansi",
        "chakkar",
    }
)
_CARE_OF_RE = re.compile(
    r"(\b(?:C/O|Care[ \t]+of)[ \t]*[:\-]?[ \t]*)([A-Z][a-zA-Z.'-]*(?:[ \t]+[A-Z][a-zA-Z.'-]*){1,3})"
)

_FAMILY_MEMBER_NAME_RE = re.compile(
    r"(\b(?:Father|Mother|Brother|Sister|Spouse|Husband|Wife|पिता|माता|भाई|बहन|पति|पत्नी)[ \t]+)"
    r"([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2}|[\u0900-\u097F]+(?:[ \t]+[\u0900-\u097F]+){0,2})"
    r"(?=[ \t]+(?:had|has|with|ko|को|ने|का|की|के)(?=\s|[।,;\n\r]|$))",
)

_ADDRESS_DEVA_RE = re.compile(
    r"((?:ग्राम|पता|मोहल्ला|तहसील)\s*[:\-]\s*)([^\n\r,;]+)"
)
_ADDRESS_LATIN_RE = re.compile(
    r"(\b(?:H\.?\s*No\.?|House\s*No\.?|Mohalla|Gali|Village|Gram|Tehsil|Address)\s*[:\-]?\s*)([^\n\r,;]+)",
    re.IGNORECASE,
)

# Unlabeled Title-Case 2-3 word person names in free text (e.g. "Meera Shah presented with fever.")
_UNLABELED_TITLECASE_NAME_RE = re.compile(
    r"\b([A-Z][a-z]{1,20}(?:[ \t]+[A-Z][a-z]{1,20}){1,2})\b"
)
_NON_NAME_TITLECASE_WORDS = frozenset(
    {
        "tab",
        "cap",
        "inj",
        "inh",
        "syp",
        "susp",
        "drop",
        "drops",
        "gel",
        "oint",
        "cream",
        "lotion",
        "powder",
        "ramipril",
        "paracetamol",
        "metformin",
        "amlodipine",
        "telmisartan",
        "levothyroxine",
        "salbutamol",
        "pantoprazole",
        "ceftriaxone",
        "penicillin",
        "sulfa",
        "aspirin",
        "atorvastatin",
        "insulin",
        "type",
        "diabetes",
        "mellitus",
        "hypertension",
        "asthma",
        "tuberculosis",
        "disease",
        "syndrome",
        "palsy",
        "lymphoma",
        "thyroiditis",
        "fever",
        "cough",
        "pain",
        "headache",
        "chest",
        "pulmonary",
        "medicine",
        "surgery",
        "cardiology",
        "orthopedics",
        "pediatrics",
        "nursing",
        "notes",
        "opd",
        "ipd",
        "prescription",
        "diagnosis",
        "history",
        "family",
        "advice",
        "review",
        "vitals",
        "pulse",
        "temp",
        "blood",
        "pressure",
        "patient",
        "attendant",
        "father",
        "mother",
        "brother",
        "sister",
        "spouse",
        "husband",
        "wife",
        "ward",
        "bed",
        "room",
        "low",
        "salt",
        "diet",
        "consulting",
        "attending",
        "treating",
        "physician",
        "doctor",
        "consultant",
        "signed",
        "denies",
        "allergic",
        "negative",
        "positive",
        "normal",
        "next",
        "morning",
        "evening",
        "night",
        "rule",
        "out",
        "known",
        "case",
        "hospital",
        "clinic",
        "charitable",
        "multispeciality",
        "seva",
        "sadan",
        "jeevan",
        "jyoti",
        "sanjeevani",
        "arogya",
        "masked",
        "aadhaar",
        "aadhar",
        "abha",
        "policy",
        "insurance",
        "alt",
        "phone",
        "mobile",
        "mob",
        "reg",
        "no",
        "dolo",
    }
)


# ---------------------------------------------------------------------------
# Assertion / meaning classification
# ---------------------------------------------------------------------------

_ALLERGY_CUE_RE = re.compile(
    r"(?:\ballerg(?:y|ic)\b|\bnkda\b|\bno\s+known\s+drug\s+allerg|\bintolerance\b|एलर्जी)",
    re.IGNORECASE,
)
_FAMILY_CUE_RE = re.compile(
    r"(?:\bfamily\s+history\b|\bf/h\b|\bfh\s*:|\bfather\b|\bmother\b|\bpapa\b|\bmummy\b|पारिवारिक\s+इतिहास|पिता|माता)",
    re.IGNORECASE,
)
_NEGATION_CUE_RE = re.compile(
    r"(?:\bno\b|\bdenies\b|\bdenied\b|\bnegative\b|\bwithout\b|\babsent\b|\bnot\b|\brule(?:d)?\s+out\b|\bnahi\b|\bnahin\b|\bbina\b|नहीं|इनकार)",
    re.IGNORECASE,
)
_CLINICAL_CONTENT_RE = re.compile(
    r"(?:\b(?:C/O|K/C/O|H/O|Rx|BP|Pulse|Temp|RBS|SpO2|mg|mcg|IU|puffs|Tab|Inj|Inh|fever|cough|pain|diabetes|hypertension|disease|syndrome|palsy|lymphoma|thyroiditis|bukhar|dard)\b|बुखार|दर्द|मधुमेह|रक्तचाप)",
    re.IGNORECASE,
)


def extract_clinical_assertions(text: str) -> tuple[ClinicalAssertion, ...]:
    """Extract clause-level clinical assertions without flipping negation/allergy/FH to positive."""
    assertions: list[ClinicalAssertion] = []
    clauses = re.split(r"[,;\n\r.।]+|\b(?:but|however)\b", text, flags=re.IGNORECASE)
    for raw in clauses:
        clause = raw.strip()
        if not clause:
            continue
        if _ALLERGY_CUE_RE.search(clause):
            assertions.append(ClinicalAssertion(text=clause, polarity="allergy"))
        elif _FAMILY_CUE_RE.search(clause):
            assertions.append(ClinicalAssertion(text=clause, polarity="family_history"))
        elif _NEGATION_CUE_RE.search(clause):
            assertions.append(ClinicalAssertion(text=clause, polarity="negated"))
        elif _CLINICAL_CONTENT_RE.search(clause):
            assertions.append(ClinicalAssertion(text=clause, polarity="positive"))
    return tuple(assertions)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _protect_spans(text: str, pattern: re.Pattern[str]) -> tuple[str, dict[str, str]]:
    """Temporarily replace protected medical spans with inert placeholders."""
    tokens: dict[str, str] = {}

    def _repl(match: re.Match[str]) -> str:
        key = f"\x00MED{len(tokens)}\x00"
        tokens[key] = match.group(0)
        return key

    return pattern.sub(_repl, text), tokens


def _restore_spans(text: str, tokens: dict[str, str]) -> str:
    for key, val in tokens.items():
        text = text.replace(key, val)
    return text


def _redact_context_items(
    text: str,
    items: Any,
    replacement: str,
    category: str,
    counts: Counter[str],
) -> str:
    if not items:
        return text
    # Longest-first prevents partial-prefix leftovers on multi-word names.
    cleaned_items = sorted(
        {str(x).strip() for x in items if str(x).strip()},
        key=len,
        reverse=True,
    )
    for item in cleaned_items:
        pattern = re.compile(re.escape(item), re.IGNORECASE)
        text, n = pattern.subn(replacement, text)
        if n:
            counts[category] += n
    return text


def _handle_doctors(
    text: str,
    field: str,
    counts: Counter[str],
) -> str:
    """Preserve Dr. names only with trustworthy clinician role evidence."""
    field_lower = field.casefold()
    is_patient_or_rel_field = field_lower in {
        "patient_name",
        "patient",
        "attendant",
        "relative_name",
        "relative",
    }

    def _replace_latin(match: re.Match[str]) -> str:
        prefix = text[max(0, match.start() - 60) : match.start()]
        suffix = text[match.end() : min(len(text), match.end() + 60)]
        if is_patient_or_rel_field or _NON_CLINICIAN_PREFIX_RE.search(prefix):
            counts["UNVERIFIED_DOCTOR"] += 1
            return "[REDACTED_UNVERIFIED_DR]"
        if _CREDENTIAL_SUFFIX_RE.search(suffix) or _CLINICIAN_ROLE_PREFIX_RE.search(prefix):
            return match.group(0)
        counts["UNVERIFIED_DOCTOR"] += 1
        return "[REDACTED_UNVERIFIED_DR]"

    def _replace_deva(match: re.Match[str]) -> str:
        prefix = text[max(0, match.start() - 60) : match.start()]
        suffix = text[match.end() : min(len(text), match.end() + 60)]
        if is_patient_or_rel_field or _NON_CLINICIAN_PREFIX_RE.search(prefix):
            counts["UNVERIFIED_DOCTOR"] += 1
            return "[REDACTED_UNVERIFIED_DR]"
        if _CREDENTIAL_SUFFIX_RE.search(suffix) or _CLINICIAN_ROLE_PREFIX_RE.search(prefix):
            return match.group(0)
        counts["UNVERIFIED_DOCTOR"] += 1
        return "[REDACTED_UNVERIFIED_DR]"

    text = _DOCTOR_LATIN_RE.sub(_replace_latin, text)
    text = _DOCTOR_DEVA_RE.sub(_replace_deva, text)
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_text(
    text: str,
    *,
    field: str = "",
    context: Mapping[str, Any] | None = None,
) -> SanitizationResult:
    """Sanitize a clinical text field while preserving medical bytes and meaning.

    Returns cleaned text, aggregate detection counts, detected language, and
    clause-level assertions. Never logs raw matched PII strings.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str")

    ctx = context or {}
    normalized = unicodedata.normalize("NFC", text)
    language = detect_language(normalized)
    counts: Counter[str] = Counter()

    if not normalized.strip():
        return SanitizationResult(text=normalized, counts={}, language=language)

    # Direct PII-only fields can be redacted cleanly without disturbing medical text.
    if field.casefold() in {"patient_name", "patient"}:
        counts["PATIENT_NAME"] += 1
        LOGGER.debug("Sanitized field=%s detections=%d", field, 1)
        return SanitizationResult(
            text="[REDACTED_PATIENT]",
            counts=dict(counts),
            language=language,
        )

    # Protect medical eponyms before any name/proper-noun matching.
    work, protected = _protect_spans(normalized, _EPONYM_RE)

    # 1. Context-supplied markers and known names/identifiers
    work = _redact_context_items(
        work, ctx.get("private_markers"), "[REDACTED_MARKER]", "PRIVATE_MARKER", counts
    )
    work = _redact_context_items(
        work, ctx.get("canary_tokens"), "[REDACTED_MARKER]", "PRIVATE_MARKER", counts
    )
    work = _redact_context_items(
        work, ctx.get("patient_names"), "[REDACTED_PATIENT]", "PATIENT_NAME", counts
    )
    work = _redact_context_items(
        work, ctx.get("relative_names"), "[REDACTED_RELATIVE]", "RELATIVE_NAME", counts
    )
    work = _redact_context_items(
        work, ctx.get("known_identifiers"), "[REDACTED_ID]", "MRN", counts
    )

    # 2. Structured identifiers
    for pattern, repl, cat in (
        (_ABHA_NUM_RE, "[REDACTED_ABHA]", "ABHA_NUMBER"),
        (_ABHA_ADDR_RE, "[REDACTED_ABHA_ADDR]", "ABHA_ADDRESS"),
        (_EMAIL_RE, "[REDACTED_EMAIL]", "EMAIL"),
        (_PAN_RE, "[REDACTED_PAN]", "PAN"),
        (_AADHAAR_MASKED_RE, "[REDACTED_AADHAAR_MASKED]", "AADHAAR_MASKED"),
        (_AADHAAR_LABELED_RE, r"\1[REDACTED_AADHAAR]", "AADHAAR"),
        (_AADHAAR_SPACED_RE, "[REDACTED_AADHAAR]", "AADHAAR"),
        (_AADHAAR_COMPACT_RE, "[REDACTED_AADHAAR]", "AADHAAR"),
        (_PHONE_LABELED_RE, r"\1[REDACTED_PHONE]", "PHONE"),
        (_PHONE_BARE_RE, "[REDACTED_PHONE]", "PHONE"),
        (_INSURANCE_LABELED_RE, r"\1[REDACTED_INSURANCE]", "INSURANCE_ID"),
        (_MRN_LABELED_RE, r"\1[REDACTED_ID]", "MRN"),
        (_MRN_PREFIXED_RE, "[REDACTED_ID]", "MRN"),
        (_DOB_LABELED_RE, r"\1[REDACTED_DOB]", "DOB"),
        (_PIN_LABELED_RE, r"\1[REDACTED_PIN]", "PIN"),
        (_PIN_COMMA_RE, r"\1[REDACTED_PIN]", "PIN"),
    ):
        work, n = pattern.subn(repl, work)
        if n:
            counts[cat] += n

    # 3. Clinician vs relative / unverified Dr.
    work = _handle_doctors(work, field, counts)

    # 4. Labeled names, relatives, and addresses
    work, n = _PATIENT_LABEL_LATIN_RE.subn(r"\1[REDACTED_PATIENT]", work)
    if n:
        counts["PATIENT_NAME"] += n

    work, n = _PATIENT_LABEL_DEVA_RE.subn(r"\1[REDACTED_PATIENT]", work)
    if n:
        counts["PATIENT_NAME"] += n

    def _hindi_subj_repl(m: re.Match[str]) -> str:
        subj = m.group(1).strip()
        if subj in _HINDI_SUBJECT_STOPWORDS:
            return m.group(0)
        counts["PATIENT_NAME"] += 1
        return "[REDACTED_PATIENT]" + m.group(2)

    work = _HINDI_SUBJECT_RE.sub(_hindi_subj_repl, work)

    work, n = _HINGLISH_HONORIFIC_RE.subn("[REDACTED_PATIENT]", work)
    if n:
        counts["PATIENT_NAME"] += n

    work, n = _HINDI_HONORIFIC_RE.subn("[REDACTED_PATIENT]", work)
    if n:
        counts["PATIENT_NAME"] += n

    def _initial_name_repl(m: re.Match[str]) -> str:
        prefix = work[max(0, m.start() - 6) : m.start()]
        if re.search(r"\bDr\.?[ \t]+$", prefix):
            return m.group(1)
        phrase = m.group(1)
        last_word = phrase.split()[-1].casefold()
        if last_word in _NON_NAME_TITLECASE_WORDS:
            return phrase
        counts["PATIENT_NAME"] += 1
        return "[REDACTED_NAME]"

    work = _INITIAL_NAME_RE.sub(_initial_name_repl, work)

    work, n = _RELATIVE_RELATION_RE.subn(r"\1[REDACTED_RELATIVE]", work)
    if n:
        counts["RELATIVE_NAME"] += n

    def _care_of_repl(m: re.Match[str]) -> str:
        prefix, tail = m.group(1), m.group(2)
        first_word = tail.split()[0].casefold().rstrip(":.,")
        if ":" in prefix and first_word in _MEDICAL_CO_HEADS:
            return m.group(0)
        if first_word in _MEDICAL_CO_HEADS:
            return m.group(0)
        counts["RELATIVE_NAME"] += 1
        return prefix + "[REDACTED_RELATIVE]"

    work = _CARE_OF_RE.sub(_care_of_repl, work)

    work, n = _FAMILY_MEMBER_NAME_RE.subn(r"\1[REDACTED_RELATIVE]", work)
    if n:
        counts["RELATIVE_NAME"] += n

    work, n = _ADDRESS_DEVA_RE.subn(r"\1[REDACTED_ADDRESS]", work)
    if n:
        counts["ADDRESS"] += n

    work, n = _ADDRESS_LATIN_RE.subn(r"\1[REDACTED_ADDRESS]", work)
    if n:
        counts["ADDRESS"] += n

    def _unlabeled_name_repl(m: re.Match[str]) -> str:
        prefix = work[max(0, m.start() - 6) : m.start()]
        if re.search(r"\bDr\.?[ \t]+$", prefix):
            return m.group(1)
        phrase = m.group(1)
        words = phrase.casefold().split()
        if any(w in _NON_NAME_TITLECASE_WORDS for w in words):
            return phrase
        counts["PATIENT_NAME"] += 1
        return "[REDACTED_NAME]"

    work = _UNLABELED_TITLECASE_NAME_RE.sub(_unlabeled_name_repl, work)

    cleaned = _restore_spans(work, protected)
    assertions = extract_clinical_assertions(cleaned)
    aggregate = {k: v for k, v in counts.items() if v > 0}

    # Log only field name and aggregate count, never raw text or raw matches.
    LOGGER.debug(
        "Sanitized field=%s language=%s total_detections=%d",
        field or "<unspecified>",
        language,
        sum(aggregate.values()),
    )

    return SanitizationResult(
        text=cleaned,
        counts=aggregate,
        language=language,
        assertions=assertions,
    )


def sanitize_field(
    value: str,
    *,
    field: str = "",
    context: Mapping[str, Any] | None = None,
) -> SanitizationResult:
    """Alias for sanitize_text for field-oriented callers."""
    return sanitize_text(value, field=field, context=context)


def sanitize_record(
    record: Mapping[str, str],
    *,
    context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, int]]:
    """Sanitize every string field of a structured record and aggregate counts."""
    cleaned_record: dict[str, str] = {}
    total_counts: Counter[str] = Counter()
    for key, val in record.items():
        if isinstance(val, str):
            res = sanitize_text(val, field=key, context=context)
            cleaned_record[key] = res.text
            total_counts.update(res.counts)
        else:
            cleaned_record[key] = val
    return cleaned_record, {k: v for k, v in total_counts.items() if v > 0}
