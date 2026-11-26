"""Multilingual (Latin, Devanagari, Hinglish) normalization and transliteration."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

# Devanagari -> ASCII digits
_INDIC_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Devanagari independent vowels
_DEVA_VOWELS = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
    "ऑ": "o",
    "ऍ": "e",
}

# Devanagari vowel signs (matras)
_DEVA_MATRAS = {
    "ा": "a",
    "ि": "i",
    "ी": "ee",
    "ु": "u",
    "ू": "oo",
    "ृ": "ri",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
    "ॉ": "o",
    "ॅ": "e",
}

# Devanagari consonants (with nukta variants checked before single chars)
_DEVA_NUKTA_CONSONANTS = {
    "क़": "q",
    "ख़": "kh",
    "ग़": "gh",
    "ज़": "z",
    "ड़": "d",
    "ढ़": "dh",
    "फ़": "f",
    "य़": "y",
}

_DEVA_CONSONANTS = {
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "ng",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "ny",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
}

_LABIAL_CONSONANTS = {"प", "फ", "ब", "भ", "म", "फ़"}
_VIRAMA = "\u094d"
_NUKTA = "\u093c"
_ANUSVARA = "\u0902"
_CHANDRABINDU = "\u0901"
_VISARGA = "\u0903"

# Common honorifics / Hinglish suffixes and kinship words stripped from core person names
HONORIFICS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "miss",
        "smt",
        "shri",
        "shree",
        "sri",
        "km",
        "kumari",
        "ji",
        "sahab",
        "saheb",
        "babu",
        "didi",
        "bhai",
        "bhaiya",
        "bhaiyya",
        "behen",
        "behenji",
        "chacha",
        "chachu",
        "chachi",
        "mama",
        "mamu",
        "mami",
        "papa",
        "pitaji",
        "mataji",
        "babuji",
        "tau",
        "tauji",
        "fufa",
        "bua",
        "mausi",
        "dada",
        "dadi",
        "nana",
        "nani",
        "jiji",
        "uncle",
        "aunt",
        "aunty",
        "late",
        "lt",
    }
)

# Common generic Indian name components that do not uniquely identify a person alone
GENERIC_NAME_TOKENS = frozenset(
    {
        "devi",
        "kumar",
        "kumari",
        "singh",
        "kaur",
        "lal",
        "prasad",
        "ram",
        "das",
        "nath",
        "pal",
        "chand",
        "bai",
        "bibi",
        "begum",
        "mohammad",
    }
)

# Abbreviation and spelling canonicalization
_ABBREV_MAP = {
    "md": "mohammad",
    "mohd": "mohammad",
    "mohammed": "mohammad",
    "muhammad": "mohammad",
    "muhammed": "mohammad",
    "mohamed": "mohammad",
    "mhd": "mohammad",
    "sk": "shaikh",
    "sheikh": "shaikh",
    "shk": "shaikh",
    "km": "kumari",
    "smt": "shrimati",
    "ch": "chaudhary",
    "chaudhari": "chaudhary",
    "choudhary": "chaudhary",
    "pandey": "pande",
    "tiwari": "tivari",
    "tewari": "tivari",
    "siddiqui": "sidiki",
    "siddique": "sidiki",
    "qureshi": "kureshi",
    "ansari": "ansari",
}

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_NON_ALNUM_SPACE_RE = re.compile(r"[^\w\s]", re.UNICODE)
_DEVA_RE = re.compile(r"[\u0900-\u097f]")


def _transliterate_deva_word(word: str) -> str:
    """Transliterate one Devanagari word to approximate Latin phonetics."""
    out: list[str] = []
    i = 0
    n = len(word)
    while i < n:
        ch = word[i]
        # Conjuncts with explicit virama
        if i + 2 < n and word[i : i + 3] == "क्ष":
            consonant = "ksh"
            i += 3
            is_cons = True
        elif i + 2 < n and word[i : i + 3] == "त्र":
            consonant = "tr"
            i += 3
            is_cons = True
        elif i + 2 < n and word[i : i + 3] == "ज्ञ":
            consonant = "gy"
            i += 3
            is_cons = True
        elif i + 2 < n and word[i : i + 3] == "श्र":
            consonant = "shr"
            i += 3
            is_cons = True
        elif i + 1 < n and word[i : i + 2] in _DEVA_NUKTA_CONSONANTS:
            consonant = _DEVA_NUKTA_CONSONANTS[word[i : i + 2]]
            i += 2
            is_cons = True
        elif ch in _DEVA_CONSONANTS:
            consonant = _DEVA_CONSONANTS[ch]
            i += 1
            is_cons = True
        else:
            consonant = ""
            is_cons = False

        if is_cons:
            out.append(consonant)
            # Check trailing matra or virama
            if i < n and word[i] == _VIRAMA:
                i += 1
                continue
            if i < n and word[i] in _DEVA_MATRAS:
                out.append(_DEVA_MATRAS[word[i]])
                i += 1
            elif i < n and word[i] not in (_ANUSVARA, _CHANDRABINDU, _VISARGA):
                # Inherent 'a' if followed by another Devanagari letter inside word
                out.append("a")
            elif i < n and word[i] in (_ANUSVARA, _CHANDRABINDU, _VISARGA):
                # Inherent 'a' before anusvara/visarga
                out.append("a")
            continue

        if ch in _DEVA_VOWELS:
            out.append(_DEVA_VOWELS[ch])
            i += 1
        elif ch in (_ANUSVARA, _CHANDRABINDU):
            next_ch = word[i + 1] if i + 1 < n else ""
            out.append("m" if next_ch in _LABIAL_CONSONANTS else "n")
            i += 1
        elif ch == _VISARGA:
            out.append("h")
            i += 1
        elif ch == _NUKTA:
            i += 1
        else:
            out.append(ch)
            i += 1

    res = "".join(out)
    # Remove trailing schwa on multi-syllable words if it slipped through
    return res


def transliterate_text(text: str) -> str:
    """Normalize Unicode, fold Indic digits, and transliterate Devanagari tokens to Latin."""
    cleaned = _ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", text))
    cleaned = cleaned.translate(_INDIC_DIGITS)
    if not _DEVA_RE.search(cleaned):
        return cleaned
    parts = re.split(r"([\u0900-\u097f]+)", cleaned)
    for idx, part in enumerate(parts):
        if part and _DEVA_RE.search(part):
            parts[idx] = _transliterate_deva_word(part)
    return "".join(parts)


def phonetic_fold(token: str) -> str:
    """Fold Latin/transliterated spelling variations into a compact phonetic signature."""
    t = token.casefold()
    t = _ABBREV_MAP.get(t, t)
    # Common Indian transliteration equivalences
    t = t.replace("qu", "k").replace("q", "k")
    t = t.replace("ph", "f").replace("w", "v")
    t = t.replace("z", "j")
    t = t.replace("x", "ksh")
    t = re.sub(r"ey$", "e", t)
    t = re.sub(r"y$", "i", t)
    t = t.replace("aa", "a").replace("ee", "i").replace("ii", "i")
    t = t.replace("oo", "u").replace("uu", "u")
    t = t.replace("ai", "e").replace("au", "o")
    # Collapse consecutive duplicate characters (mm->m, dd->d, nn->n)
    t = re.sub(r"(.)\1+", r"\1", t)
    # Strip trailing 'a' on longer stems (>= 5 chars) before medial schwa deletion
    if len(t) >= 5 and t.endswith("a"):
        t = t[:-1]
    # Drop medial short 'a' between consonants to align Devanagari schwa deletion
    t = re.sub(r"(?<=[bcdfghjklmnprstvy])a(?=[bcdfghjklmnprstvy])", "", t)
    return t


def normalize_name_tokens(name: str) -> tuple[str, ...]:
    """Return ordered normalized non-honorific tokens from a person name."""
    latin = transliterate_text(name).casefold()
    latin = _NON_ALNUM_SPACE_RE.sub(" ", latin)
    raw_tokens = [tok for tok in latin.split() if tok]
    tokens: list[str] = []
    for tok in raw_tokens:
        if tok in HONORIFICS:
            continue
        expanded = _ABBREV_MAP.get(tok, tok)
        tokens.append(expanded)
    return tuple(tokens)


def phonetic_name_tokens(name: str) -> tuple[str, ...]:
    """Return phonetic-folded non-honorific tokens for a name."""
    return tuple(phonetic_fold(tok) for tok in normalize_name_tokens(name))


def normalize_place(place: str | None) -> str | None:
    """Normalize a village or district name across Latin and Devanagari."""
    if not place:
        return None
    latin = transliterate_text(place).casefold()
    latin = _NON_ALNUM_SPACE_RE.sub(" ", latin)
    toks = [phonetic_fold(t) for t in latin.split() if t]
    return " ".join(toks) if toks else None


def normalize_phone(raw: str) -> str | None:
    """Normalize an Indian phone number to its 10-digit mobile form."""
    digits = re.sub(r"\D", "", transliterate_text(raw))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return None


def normalize_aadhaar(raw: str) -> str | None:
    """Normalize a 12-digit Aadhaar number (rejecting masked forms)."""
    s = transliterate_text(raw)
    if "x" in s.casefold() or "*" in s:
        return None
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 12 else None


def normalize_aadhaar_last4(raw: str) -> str | None:
    """Extract last 4 digits from masked or full Aadhaar."""
    digits = re.sub(r"\D", "", transliterate_text(raw))
    if len(digits) in (4, 12):
        return digits[-4:]
    return None


def normalize_abha(raw: str) -> str | None:
    """Normalize a 14-digit ABHA number."""
    digits = re.sub(r"\D", "", transliterate_text(raw))
    return digits if len(digits) == 14 else None


def normalize_pan(raw: str) -> str | None:
    """Normalize an Indian PAN identifier."""
    s = re.sub(r"\s+", "", transliterate_text(raw)).upper()
    return s if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", s) else None


def normalize_email(raw: str) -> str | None:
    """Normalize an email address."""
    s = transliterate_text(raw).strip().casefold()
    return s if re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w.-]+)+", s) else None


def normalize_local_id(raw: str) -> str | None:
    """Normalize a hospital-local ID (UHID, MRN, IPD, etc.)."""
    s = re.sub(r"\s+", "", transliterate_text(raw)).upper()
    s = re.sub(r"[^A-Z0-9/-]", "", s)
    return s if len(s) >= 3 and any(ch.isdigit() for ch in s) else None


def normalize_gender(raw: str | None) -> str | None:
    """Normalize gender string to 'M', 'F', 'O', or None."""
    if not raw:
        return None
    s = transliterate_text(raw).strip().casefold()
    if s in {"m", "male", "man", "boy", "purush", "mard"}:
        return "M"
    if s in {"f", "female", "woman", "girl", "mahila", "stri"}:
        return "F"
    if s in {"o", "other", "t", "transgender"}:
        return "O"
    return None


def normalize_dob(raw: str | None) -> str | None:
    """Normalize DOB to ISO YYYY-MM-DD when unambiguous."""
    if not raw:
        return None
    s = transliterate_text(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            parsed = dt.datetime.strptime(s, fmt).date()
            if 1900 <= parsed.year <= 2030:
                return parsed.isoformat()
        except ValueError:
            continue
    return None


def _tokens_match(a: str, b: str) -> bool:
    """Check whether two phonetic name tokens represent the same name token."""
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        # Allow minor 1-char edit distance on longer transliterated stems
        if abs(len(a) - len(b)) <= 1:
            if _edit_distance_le_1(a, b):
                return True
    return False


def _edit_distance_le_1(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(c1 != c2 for c1, c2 in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    # len(b) == len(a) + 1
    i = j = diffs = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diffs += 1
            if diffs > 1:
                return False
            j += 1
    return True


def compare_name_lists(names_a: tuple[tuple[str, ...], ...], names_b: tuple[tuple[str, ...], ...]) -> tuple[bool, bool, int]:
    """Compare two sets of phonetic-tokenized names.

    Returns ``(compatible, strong_match, identifying_overlap_count)``.
    - ``compatible`` is False if both sides have names and they represent distinct people.
    - ``strong_match`` is True if multi-token names match or a non-generic full token matches
      without conflicting extra given names.
    """
    if not names_a or not names_b:
        return True, False, 0

    best_overlap = 0
    best_strong = False
    any_compatible = False

    generic_phonetic = frozenset(phonetic_fold(g) for g in GENERIC_NAME_TOKENS)

    for toks_a in names_a:
        for toks_b in names_b:
            if not toks_a or not toks_b:
                continue
            full_a = [t for t in toks_a if len(t) > 1]
            full_b = [t for t in toks_b if len(t) > 1]
            init_a = [t for t in toks_a if len(t) == 1]
            init_b = [t for t in toks_b if len(t) == 1]

            matched_full = 0
            identifying_matched = 0
            used_b: set[int] = set()
            for ta in full_a:
                for idx, tb in enumerate(full_b):
                    if idx not in used_b and _tokens_match(ta, tb):
                        used_b.add(idx)
                        matched_full += 1
                        if ta not in generic_phonetic:
                            identifying_matched += 1
                        break

            # Initials can corroborate a full-token match (e.g. "S. Verma" vs "Sanjay Verma")
            matched_init = 0
            for ia in init_a:
                if any(tb.startswith(ia) for idx, tb in enumerate(full_b) if idx not in used_b):
                    matched_init += 1
            for ib in init_b:
                if any(ta.startswith(ib) for ta in full_a):
                    matched_init += 1

            if matched_full == 0:
                continue

            # Check for conflicting non-generic tokens (e.g., "Neelam Mishra" vs "Sandeep Mishra")
            unmatched_a = [t for i, t in enumerate(full_a) if not any(_tokens_match(t, full_b[j]) for j in used_b)]
            unmatched_b = [t for j, t in enumerate(full_b) if j not in used_b]
            # Account for initials explaining one unmatched token on the other side
            rem_a = [t for t in unmatched_a if not any(t.startswith(ib) for ib in init_b)]
            rem_b = [t for t in unmatched_b if not any(t.startswith(ia) for ia in init_a)]

            non_gen_rem_a = [t for t in rem_a if t not in generic_phonetic]
            non_gen_rem_b = [t for t in rem_b if t not in generic_phonetic]

            # If BOTH sides have an unmatched non-generic token (e.g. Neelam vs Sandeep),
            # they are distinct people sharing only a surname!
            if non_gen_rem_a and non_gen_rem_b:
                continue

            # Must have at least 1 identifying (non-generic) match, OR >= 2 full tokens matched
            if identifying_matched == 0 and matched_full < 2:
                continue

            any_compatible = True
            best_overlap = max(best_overlap, identifying_matched)
            is_subset_or_full = (
                (len(rem_a) == 0 and len(rem_b) == 0)
                or (matched_full >= 2)
                or (identifying_matched >= 1 and (not rem_a or not rem_b))
            )
            if is_subset_or_full:
                best_strong = True

    return any_compatible, best_strong, best_overlap
