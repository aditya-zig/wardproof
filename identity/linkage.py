"""Privacy-preserving cross-script patient linkage, date shifting, and generalization.

Standard-library Python only. Zero plaintext identity lookup tables written to disk.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import hashlib
import hmac
import re
import unicodedata

# ---------------------------------------------------------------------------
# Devanagari -> Latin phonetic transliteration (standard-library only)
# ---------------------------------------------------------------------------

_DEVA_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h",
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r",
    "ढ़": "rh", "फ़": "f",
}
_DEVA_VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_DEVA_MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
    "ं": "n", "ँ": "n", "ः": "h",
}
_VIRAMA = "्"

_HONORIFICS = frozenset(
    {
        "mr", "mrs", "ms", "miss", "shri", "smt", "kumari", "dr",
        "sahab", "saheb", "ji", "didi", "bhai", "behenji",
        "श्री", "श्रीमती", "सुश्री", "कुमारी", "जी", "साहब", "दीदी",
    }
)
_NAME_ALIASES = {
    "mohd": "mohammad",
    "md": "mohammad",
    "mohammed": "mohammad",
    "muhammad": "mohammad",
    "mhmd": "mohammad",
    "mhd": "mohammad",
}


def _transliterate_deva(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # Handle nukta combinations (e.g. ज + ़)
        if i + 1 < n and text[i + 1] == "\u093c":
            pair = ch + "\u093c"
            if pair in _DEVA_CONSONANTS:
                out.append(_DEVA_CONSONANTS[pair])
                i += 2
                if i < n and text[i] == _VIRAMA:
                    i += 1
                elif i < n and text[i] in _DEVA_MATRAS:
                    out.append(_DEVA_MATRAS[text[i]])
                    i += 1
                else:
                    out.append("a")
                continue
        if ch in _DEVA_CONSONANTS:
            out.append(_DEVA_CONSONANTS[ch])
            i += 1
            if i < n and text[i] == _VIRAMA:
                i += 1
            elif i < n and text[i] in _DEVA_MATRAS:
                out.append(_DEVA_MATRAS[text[i]])
                i += 1
            else:
                out.append("a")
        elif ch in _DEVA_VOWELS:
            out.append(_DEVA_VOWELS[ch])
            i += 1
        elif ch in _DEVA_MATRAS:
            out.append(_DEVA_MATRAS[ch])
            i += 1
        elif ch == _VIRAMA or ch == "\u093c":
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _phonetic_fold(token: str) -> str:
    t = token.casefold()
    t = _NAME_ALIASES.get(t, t)
    t = t.replace("ph", "f").replace("ee", "i").replace("oo", "u").replace("aa", "a")
    t = re.sub(r"([a-z])\1+", r"\1", t)
    # Strip trailing schwa 'a' from transliteration for cross-script alignment (e.g. shahida -> shahid)
    if len(t) > 3 and t.endswith("a"):
        t = t[:-1]
    return t


def normalize_name(name: str) -> str:
    """Normalize English/Hindi/Hinglish name into a canonical phonetic string."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).strip()
    if re.search(r"[\u0900-\u097F]", s):
        s = _transliterate_deva(s)
    tokens = re.findall(r"[a-zA-Z]+", s.casefold())
    cleaned = [_phonetic_fold(tok) for tok in tokens if tok not in _HONORIFICS]
    return " ".join(c for c in cleaned if c)


def normalize_phone(phone: str) -> str:
    """Return 10-digit Indian mobile number or empty string."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) >= 10:
        tail = digits[-10:]
        if tail[0] in "6789":
            return tail
    return ""


# ---------------------------------------------------------------------------
# Quasi-identifier generalization & HMAC date shifting
# ---------------------------------------------------------------------------


def generalize_age(age: int | str | None) -> str:
    """Generalize integer age into a 5-year band (top-coded 85+)."""
    if age is None:
        return ""
    try:
        val = int(str(age).strip())
    except ValueError:
        return ""
    if val < 0 or val > 125:
        return ""
    if val >= 85:
        return "85+"
    low = (val // 5) * 5
    return f"{low}-{low + 4}"


def generalize_pin(pin: str) -> str:
    """Generalize a 6-digit Indian PIN code to its 3-digit prefix."""
    digits = re.sub(r"\D", "", pin or "")
    if len(digits) == 6:
        return digits[:3] + "xxx"
    return ""


def _hmac_bytes(secret: bytes, domain: str, key: str) -> bytes:
    return hmac.new(secret, f"{domain}\0{key}".encode("utf-8"), hashlib.sha256).digest()


def date_offset_days(cluster_key: str, secret: bytes) -> int:
    """Deterministic non-zero day shift in [-90, -15] U [15, 90] per patient+secret."""
    digest = _hmac_bytes(secret, "date-offset", cluster_key)
    val = int.from_bytes(digest[:4], "big")
    magnitude = 15 + (val % 76)  # 15..90 days
    sign = -1 if (digest[4] & 1) else 1
    return sign * magnitude


_DATE_PATTERNS = (
    ("%Y-%m-%d", re.compile(r"^(\d{4})-(\d{2})-(\d{2})(.*)$")),
    ("%d/%m/%Y", re.compile(r"^(\d{2})/(\d{2})/(\d{4})(.*)$")),
    ("%d-%m-%Y", re.compile(r"^(\d{2})-(\d{2})-(\d{4})(.*)$")),
    ("%m/%d/%Y", re.compile(r"^(\d{2})/(\d{2})/(\d{4})(.*)$")),
)


def shift_date_string(raw: str, offset_days: int) -> str:
    """Shift ISO or DD/MM/YYYY or MM/DD/YYYY date string by offset_days, preserving format."""
    s = (raw or "").strip()
    if not s or offset_days == 0:
        return s
    # ISO datetime or date: YYYY-MM-DD...
    m_iso = re.match(r"^(\d{4}-\d{2}-\d{2})(T.*)?$", s)
    if m_iso:
        try:
            d = date.fromisoformat(m_iso.group(1)) + timedelta(days=offset_days)
            return d.isoformat() + (m_iso.group(2) or "")
        except ValueError:
            return s
    # DD/MM/YYYY or DD-MM-YYYY (fallback MM/DD/YYYY if day > 12 fails)
    m_sep = re.match(r"^(\d{2})([/-])(\d{2})\2(\d{4})(.*)$", s)
    if m_sep:
        p1, sep, p2, yr, rest = int(m_sep.group(1)), m_sep.group(2), int(m_sep.group(3)), int(m_sep.group(4)), m_sep.group(5)
        for fmt_d, fmt_m in ((p1, p2), (p2, p1)):
            try:
                d = date(yr, fmt_m, fmt_d) + timedelta(days=offset_days)
                if fmt_d == p1:
                    return f"{d.day:02d}{sep}{d.month:02d}{sep}{d.year:04d}{rest}"
                return f"{d.month:02d}{sep}{d.day:02d}{sep}{d.year:04d}{rest}"
            except ValueError:
                continue
    return s


# ---------------------------------------------------------------------------
# Cross-file / cross-script precision-first patient linkage
# ---------------------------------------------------------------------------


@dataclass
class IdentityEvidence:
    """Normalized identity evidence for a single record (in-memory only)."""

    record_id: str  # e.g. "<source_file>#<loc>"
    uhids: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    aadhaars: set[str] = field(default_factory=set)
    abhas: set[str] = field(default_factory=set)
    pans: set[str] = field(default_factory=set)
    name_norm: str = ""
    relative_norm: str = ""
    raw_names: set[str] = field(default_factory=set)
    sex: str = ""
    age: int | None = None
    dob: str = ""


class PatientLinkageIndex:
    """Precision-first clustering of records into stable HMAC pseudonyms."""

    def __init__(self, secret: bytes) -> None:
        self._secret = secret
        self._records: list[IdentityEvidence] = []
        self._parent: dict[str, str] = {}
        self._clusters: dict[str, list[IdentityEvidence]] = {}
        self._built = False

    def add(self, ev: IdentityEvidence) -> None:
        self._records.append(ev)
        self._parent[ev.record_id] = ev.record_id
        self._built = False

    def _find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def _compatible(self, r1: str, r2: str) -> bool:
        """Homonym & conflict guard: never merge records with conflicting demographics/IDs."""
        c1 = self._clusters[r1]
        c2 = self._clusters[r2]
        sexes1 = {e.sex for e in c1 if e.sex}
        sexes2 = {e.sex for e in c2 if e.sex}
        if sexes1 and sexes2 and sexes1.isdisjoint(sexes2):
            return False
        ages1 = [e.age for e in c1 if e.age is not None]
        ages2 = [e.age for e in c2 if e.age is not None]
        if ages1 and ages2 and min(abs(a - b) for a in ages1 for b in ages2) > 2:
            return False
        aad1 = {a for e in c1 for a in e.aadhaars}
        aad2 = {a for e in c2 for a in e.aadhaars}
        if aad1 and aad2 and aad1.isdisjoint(aad2):
            return False
        abha1 = {a for e in c1 for a in e.abhas}
        abha2 = {a for e in c2 for a in e.abhas}
        if abha1 and abha2 and abha1.isdisjoint(abha2):
            return False
        return True

    def _union(self, a: str, b: str) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra == rb:
            return
        if not self._compatible(ra, rb):
            return
        if len(self._clusters[ra]) < len(self._clusters[rb]):
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._clusters[ra].extend(self._clusters.pop(rb))

    def build(self) -> None:
        self._clusters = {ev.record_id: [ev] for ev in self._records}
        self._parent = {ev.record_id: ev.record_id for ev in self._records}

        # 1. Exact strong identifiers (ABHA, Aadhaar, PAN, UHID, Phone)
        by_key: dict[str, list[str]] = defaultdict(list)
        for ev in self._records:
            for k in ev.abhas:
                by_key[f"abha:{k}"].append(ev.record_id)
            for k in ev.aadhaars:
                by_key[f"aad:{k}"].append(ev.record_id)
            for k in ev.pans:
                by_key[f"pan:{k}"].append(ev.record_id)
            for k in ev.uhids:
                by_key[f"uhid:{k.casefold()}"].append(ev.record_id)
            for k in ev.phones:
                by_key[f"phone:{k}"].append(ev.record_id)

        for ids in by_key.values():
            head = ids[0]
            for other in ids[1:]:
                self._union(head, other)

        # 2. Corroborated cross-script name matching (name + relative OR name + sex + age)
        by_name: dict[str, list[IdentityEvidence]] = defaultdict(list)
        for ev in self._records:
            if ev.name_norm and len(ev.name_norm.split()) >= 2:
                by_name[ev.name_norm].append(ev)

        for ev_list in by_name.values():
            for i, e1 in enumerate(ev_list):
                for e2 in ev_list[i + 1 :]:
                    corroborated = False
                    if e1.relative_norm and e2.relative_norm and e1.relative_norm == e2.relative_norm:
                        corroborated = True
                    elif e1.dob and e2.dob and e1.dob == e2.dob:
                        corroborated = True
                    elif e1.sex and e2.sex and e1.sex == e2.sex and e1.age is not None and e2.age is not None and abs(e1.age - e2.age) <= 1:
                        corroborated = True
                    if corroborated:
                        self._union(e1.record_id, e2.record_id)

        self._built = True

    def _cluster_key(self, root: str) -> str:
        members = self._clusters[root]
        strong: list[str] = []
        for ev in members:
            strong.extend(f"abha:{x}" for x in ev.abhas)
            strong.extend(f"aad:{x}" for x in ev.aadhaars)
            strong.extend(f"pan:{x}" for x in ev.pans)
            strong.extend(f"uhid:{x.casefold()}" for x in ev.uhids)
            strong.extend(f"phone:{x}" for x in ev.phones)
        if strong:
            return min(strong)
        return "rec:" + min(ev.record_id for ev in members)

    def _has_linkable_evidence(self, ev: IdentityEvidence) -> bool:
        return bool(ev.abhas or ev.aadhaars or ev.pans or ev.uhids or ev.phones or (ev.name_norm and (ev.relative_norm or ev.dob or (ev.sex and ev.age is not None))))

    def pseudonym(self, record_id: str) -> str | None:
        """Return stable 'PSN-<hex>' for corroborated/identified records, or None to abstain."""
        if not self._built:
            self.build()
        if record_id not in self._parent:
            return None
        root = self._find(record_id)
        members = self._clusters[root]
        if not any(self._has_linkable_evidence(m) for m in members):
            return None
        key = self._cluster_key(root)
        token = _hmac_bytes(self._secret, "patient", key).hex()[:16]
        return f"PSN-{token}"

    def date_offset(self, record_id: str) -> int:
        """Return stable patient-level day offset (or 0 if unlinked)."""
        if not self._built:
            self.build()
        if record_id not in self._parent:
            return 0
        root = self._find(record_id)
        key = self._cluster_key(root)
        return date_offset_days(key, self._secret)

    def cluster_names(self, record_id: str) -> list[str]:
        """Return all observed name variants for this record's linked cluster."""
        if not self._built:
            self.build()
        if record_id not in self._parent:
            return []
        root = self._find(record_id)
        names: set[str] = set()
        for ev in self._clusters[root]:
            for nm in ev.raw_names:
                names.add(nm)
                for tok in nm.split():
                    if len(tok) >= 4:
                        names.add(tok)
        return sorted(names, key=len, reverse=True)
