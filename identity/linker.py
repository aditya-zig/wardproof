"""In-memory, deterministic patient record linkage and abstention engine.

Never writes plaintext lookup tables or raw identifiers to disk.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib

from .crypto import derive_date_offset, derive_pseudonym
from .models import Evidence, LinkResult
from .normalize import (
    compare_name_lists,
    normalize_aadhaar,
    normalize_aadhaar_last4,
    normalize_abha,
    normalize_dob,
    normalize_email,
    normalize_gender,
    normalize_local_id,
    normalize_pan,
    normalize_phone,
    normalize_place,
    phonetic_fold,
    phonetic_name_tokens,
)


@dataclass(frozen=True)
class _NormRecord:
    orig_index: int
    record_id: str
    source_namespace: str
    canonical_sig: str
    names: tuple[tuple[str, ...], ...]
    relatives: tuple[tuple[str, ...], ...]
    local_ids: frozenset[tuple[str, str]]
    aadhaar: frozenset[str]
    aadhaar_last4: frozenset[str]
    abha: frozenset[str]
    pan: frozenset[str]
    insurance_ids: frozenset[str]
    emails: frozenset[str]
    phones: frozenset[str]
    dob: str | None
    birth_year: int | None
    age: int | None
    gender: str | None
    village: str | None
    district: str | None
    pin: str | None


@dataclass
class _ClusterState:
    members: list[int] = field(default_factory=list)
    member_sigs: list[str] = field(default_factory=list)
    names: list[tuple[str, ...]] = field(default_factory=list)
    relatives: list[tuple[str, ...]] = field(default_factory=list)
    local_ids: set[tuple[str, str]] = field(default_factory=set)
    aadhaar: set[str] = field(default_factory=set)
    aadhaar_last4: set[str] = field(default_factory=set)
    abha: set[str] = field(default_factory=set)
    pan: set[str] = field(default_factory=set)
    insurance_ids: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    dobs: set[str] = field(default_factory=set)
    birth_years: set[int] = field(default_factory=set)
    ages: set[int] = field(default_factory=set)
    genders: set[str] = field(default_factory=set)
    villages: set[str] = field(default_factory=set)
    districts: set[str] = field(default_factory=set)
    pins: set[str] = field(default_factory=set)

    @classmethod
    def from_record(cls, idx: int, rec: _NormRecord) -> _ClusterState:
        return cls(
            members=[idx],
            member_sigs=[rec.canonical_sig],
            names=list(rec.names),
            relatives=list(rec.relatives),
            local_ids=set(rec.local_ids),
            aadhaar=set(rec.aadhaar),
            aadhaar_last4=set(rec.aadhaar_last4),
            abha=set(rec.abha),
            pan=set(rec.pan),
            insurance_ids=set(rec.insurance_ids),
            emails=set(rec.emails),
            phones=set(rec.phones),
            dobs={rec.dob} if rec.dob else set(),
            birth_years={rec.birth_year} if rec.birth_year is not None else set(),
            ages={rec.age} if rec.age is not None else set(),
            genders={rec.gender} if rec.gender else set(),
            villages={rec.village} if rec.village else set(),
            districts={rec.district} if rec.district else set(),
            pins={rec.pin} if rec.pin else set(),
        )

    def merge_from(self, other: _ClusterState) -> None:
        self.members.extend(other.members)
        self.member_sigs.extend(other.member_sigs)
        for n in other.names:
            if n not in self.names:
                self.names.append(n)
        for r in other.relatives:
            if r not in self.relatives:
                self.relatives.append(r)
        self.local_ids |= other.local_ids
        self.aadhaar |= other.aadhaar
        self.aadhaar_last4 |= other.aadhaar_last4
        self.abha |= other.abha
        self.pan |= other.pan
        self.insurance_ids |= other.insurance_ids
        self.emails |= other.emails
        self.phones |= other.phones
        self.dobs |= other.dobs
        self.birth_years |= other.birth_years
        self.ages |= other.ages
        self.genders |= other.genders
        self.villages |= other.villages
        self.districts |= other.districts
        self.pins |= other.pins


def _normalize_evidence(orig_index: int, ev: Evidence) -> _NormRecord:
    ns = ev.source_namespace.strip().casefold()
    names = tuple(dict.fromkeys(toks for n in ev.names if (toks := phonetic_name_tokens(n))))
    rels = tuple(dict.fromkeys(toks for r in ev.relatives if (toks := phonetic_name_tokens(r))))
    local_ids = frozenset((ns, lid) for raw in ev.local_ids if (lid := normalize_local_id(raw)))
    aadhaar = frozenset(a for raw in ev.aadhaar if (a := normalize_aadhaar(raw)))
    last4 = frozenset(l4 for raw in ev.aadhaar_last4 if (l4 := normalize_aadhaar_last4(raw))) | frozenset(
        a[-4:] for a in aadhaar
    )
    abha = frozenset(a for raw in ev.abha if (a := normalize_abha(raw)))
    pan = frozenset(p for raw in ev.pan if (p := normalize_pan(raw)))
    ins = frozenset(i for raw in ev.insurance_ids if (i := normalize_local_id(raw)))
    emails = frozenset(e for raw in ev.emails if (e := normalize_email(raw)))
    phones = frozenset(p for raw in ev.phones if (p := normalize_phone(raw)))
    dob = normalize_dob(ev.dob)
    birth_year = int(dob[:4]) if dob else None
    age = ev.age if isinstance(ev.age, int) and 0 <= ev.age <= 125 else None
    gender = normalize_gender(ev.gender)
    village = normalize_place(ev.village)
    district = normalize_place(ev.district)
    pin = raw_pin if ev.pin and (raw_pin := "".join(c for c in ev.pin if c.isdigit())) and len(raw_pin) == 6 else None

    sig_parts = [
        ns,
        ",".join(" ".join(t) for t in sorted(names)),
        ",".join(" ".join(t) for t in sorted(rels)),
        ",".join(f"{s}:{v}" for s, v in sorted(local_ids)),
        ",".join(sorted(aadhaar)),
        ",".join(sorted(abha)),
        ",".join(sorted(pan)),
        ",".join(sorted(ins)),
        ",".join(sorted(emails)),
        ",".join(sorted(phones)),
        dob or "",
        str(age) if age is not None else "",
        gender or "",
        village or "",
        district or "",
        pin or "",
        ev.record_id,
    ]
    canonical_sig = hashlib.sha256("\0".join(sig_parts).encode("utf-8")).hexdigest()

    return _NormRecord(
        orig_index=orig_index,
        record_id=ev.record_id,
        source_namespace=ns,
        canonical_sig=canonical_sig,
        names=names,
        relatives=rels,
        local_ids=local_ids,
        aadhaar=aadhaar,
        aadhaar_last4=last4,
        abha=abha,
        pan=pan,
        insurance_ids=ins,
        emails=emails,
        phones=phones,
        dob=dob,
        birth_year=birth_year,
        age=age,
        gender=gender,
        village=village,
        district=district,
        pin=pin,
    )


def _detect_shared_phones(records: list[_NormRecord]) -> set[str]:
    """Identify phones shared by multiple incompatible individuals (e.g. household phones)."""
    by_phone: dict[str, list[_NormRecord]] = defaultdict(list)
    for rec in records:
        for ph in rec.phones:
            by_phone[ph].append(rec)

    shared: set[str] = set()
    for ph, group in by_phone.items():
        if len(group) < 2:
            continue
        genders = {r.gender for r in group if r.gender}
        if len(genders) > 1:
            shared.add(ph)
            continue
        dobs = {r.dob for r in group if r.dob}
        if len(dobs) > 1:
            shared.add(ph)
            continue
        ages = [r.age for r in group if r.age is not None]
        if ages and (max(ages) - min(ages) > 3):
            shared.add(ph)
            continue
        named = [r for r in group if r.names]
        if len(named) >= 2:
            base = named[0]
            for other in named[1:]:
                compat, _, _ = compare_name_lists(base.names, other.names)
                if not compat:
                    shared.add(ph)
                    break
    return shared


def _pair_conflicts(a: _NormRecord, b: _NormRecord) -> bool:
    """Fast pair-level hard conflict check."""
    if a.aadhaar and b.aadhaar and a.aadhaar.isdisjoint(b.aadhaar):
        return True
    if a.aadhaar_last4 and b.aadhaar_last4 and a.aadhaar_last4.isdisjoint(b.aadhaar_last4):
        return True
    if a.abha and b.abha and a.abha.isdisjoint(b.abha):
        return True
    if a.pan and b.pan and a.pan.isdisjoint(b.pan):
        return True
    if a.emails and b.emails and a.emails.isdisjoint(b.emails):
        return True
    if a.gender and b.gender and a.gender != b.gender:
        return True
    if a.dob and b.dob and a.dob != b.dob:
        return True
    if a.age is not None and b.age is not None and abs(a.age - b.age) > 3:
        return True
    if a.birth_year is not None and b.birth_year is not None and abs(a.birth_year - b.birth_year) > 0:
        return True
    if a.names and b.names:
        compat, _, _ = compare_name_lists(a.names, b.names)
        if not compat:
            return True
    if a.relatives and b.relatives:
        rel_compat, _, _ = compare_name_lists(a.relatives, b.relatives)
        if not rel_compat:
            return True
    return False


def _clusters_conflict(ca: _ClusterState, cb: _ClusterState, allow_geo_diff: bool) -> bool:
    """Cluster-level conflict check to prevent transitive over-merging."""
    if ca.aadhaar and cb.aadhaar and ca.aadhaar.isdisjoint(cb.aadhaar):
        return True
    if ca.aadhaar_last4 and cb.aadhaar_last4 and ca.aadhaar_last4.isdisjoint(cb.aadhaar_last4):
        return True
    if ca.abha and cb.abha and ca.abha.isdisjoint(cb.abha):
        return True
    if ca.pan and cb.pan and ca.pan.isdisjoint(cb.pan):
        return True
    if ca.emails and cb.emails and ca.emails.isdisjoint(cb.emails):
        return True
    if ca.genders and cb.genders and ca.genders.isdisjoint(cb.genders):
        return True
    if ca.dobs and cb.dobs and ca.dobs.isdisjoint(cb.dobs):
        return True
    all_ages = ca.ages | cb.ages
    if all_ages and (max(all_ages) - min(all_ages) > 3):
        return True
    all_byears = ca.birth_years | cb.birth_years
    if len(all_byears) > 1:
        return True
    # Check DOB vs age consistency across clusters
    if all_byears and all_ages:
        by = next(iter(all_byears))
        for ag in all_ages:
            implied_by = 2026 - ag
            if abs(implied_by - by) > 4:
                return True
    if ca.names and cb.names:
        compat, _, _ = compare_name_lists(tuple(ca.names), tuple(cb.names))
        if not compat:
            return True
    if ca.relatives and cb.relatives:
        rel_compat, _, _ = compare_name_lists(tuple(ca.relatives), tuple(cb.relatives))
        if not rel_compat:
            return True
    if not allow_geo_diff:
        if ca.districts and cb.districts and ca.districts.isdisjoint(cb.districts):
            return True
        if ca.villages and cb.villages and ca.villages.isdisjoint(cb.villages):
            return True
    return False


def _score_pair(a: _NormRecord, b: _NormRecord, shared_phones: set[str]) -> tuple[int, bool]:
    """Return ``(score, allow_geo_diff)``. ``0`` means insufficient evidence to link."""
    if _pair_conflicts(a, b):
        return 0, False

    # Tier 1: Global unique ID match
    if (
        (a.aadhaar and not a.aadhaar.isdisjoint(b.aadhaar))
        or (a.abha and not a.abha.isdisjoint(b.abha))
        or (a.pan and not a.pan.isdisjoint(b.pan))
        or (a.insurance_ids and not a.insurance_ids.isdisjoint(b.insurance_ids))
        or (a.emails and not a.emails.isdisjoint(b.emails))
    ):
        return 100, True

    # Tier 2: Same-source-namespace local ID match
    if a.local_ids and not a.local_ids.isdisjoint(b.local_ids):
        return 90, True

    name_compat, name_strong, name_ident = compare_name_lists(a.names, b.names)

    # Tier 3: Phone match (guarded against shared household phones)
    common_phones = a.phones & b.phones
    if common_phones:
        non_shared = common_phones - shared_phones
        if non_shared:
            if not a.names or not b.names or (name_compat and name_ident >= 1):
                return 80, True
        else:
            # Shared household phone requires compatible identifying name match
            if a.names and b.names and name_compat and name_ident >= 1:
                return 74, True

    # Tier 4: Cross-file / cross-script corroborated name matches
    if not (a.names and b.names and name_compat and name_ident >= 1):
        return 0, False

    # Name + exact DOB
    if a.dob and b.dob and a.dob == b.dob:
        return 85, True

    # Name + compatible relative name
    if a.relatives and b.relatives:
        rel_compat, _, rel_ident = compare_name_lists(a.relatives, b.relatives)
        if rel_compat and rel_ident >= 1:
            return 76, False

    # Strong/full name + Aadhaar last 4 + (age or village/district)
    if a.aadhaar_last4 and not a.aadhaar_last4.isdisjoint(b.aadhaar_last4) and name_strong:
        if (a.age is not None and b.age is not None) or (a.village and a.village == b.village) or (a.district and a.district == b.district):
            return 78, False

    # Strong/full name + same village + compatible age (or DOB year)
    if name_strong and a.village and b.village and a.village == b.village:
        if a.age is not None and b.age is not None and abs(a.age - b.age) <= 2:
            return 68, False

    return 0, False


def _has_standalone_anchor(rec: _NormRecord, shared_phones: set[str]) -> bool:
    """Return True if a singleton record carries enough evidence to hold a pseudonym."""
    if rec.aadhaar or rec.abha or rec.pan or rec.insurance_ids or rec.emails or rec.local_ids:
        return True
    if rec.phones - shared_phones:
        return True
    if rec.phones and rec.names:
        _, _, name_ident = compare_name_lists(rec.names, rec.names)
        if name_ident >= 1:
            return True
    if rec.names and rec.dob:
        return True
    if rec.names and rec.relatives:
        _, _, rel_ident = compare_name_lists(rec.relatives, rec.relatives)
        _, _, name_ident = compare_name_lists(rec.names, rec.names)
        if name_ident >= 1 and rel_ident >= 1:
            return True
    return False


def _cluster_key(cluster: _ClusterState) -> str:
    """Derive a deterministic, input-order-independent canonical key for a linked cluster."""
    if cluster.aadhaar:
        return "aadhaar:" + min(cluster.aadhaar)
    if cluster.abha:
        return "abha:" + min(cluster.abha)
    if cluster.pan:
        return "pan:" + min(cluster.pan)
    if cluster.insurance_ids:
        return "ins:" + min(cluster.insurance_ids)
    if cluster.emails:
        return "email:" + min(cluster.emails)
    if cluster.local_ids:
        ns, lid = min(cluster.local_ids)
        return f"local:{ns}:{lid}"
    if cluster.phones:
        name_part = min(" ".join(n) for n in cluster.names) if cluster.names else ""
        return f"phone:{min(cluster.phones)}:{name_part}"
    name_part = min(" ".join(n) for n in cluster.names) if cluster.names else ""
    if cluster.dobs:
        return f"ndob:{name_part}:{min(cluster.dobs)}"
    if cluster.relatives:
        rel_part = min(" ".join(r) for r in cluster.relatives)
        return f"nrel:{name_part}:{rel_part}"
    if cluster.villages:
        age_part = str(min(cluster.ages)) if cluster.ages else ""
        return f"nvil:{name_part}:{min(cluster.villages)}:{age_part}"
    return "cluster:" + ",".join(sorted(cluster.member_sigs))


def _generate_blocks(records: list[_NormRecord]) -> dict[str, list[int]]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for idx, rec in enumerate(records):
        for val in rec.aadhaar:
            blocks[f"aad:{val}"].append(idx)
        for val in rec.abha:
            blocks[f"abha:{val}"].append(idx)
        for val in rec.pan:
            blocks[f"pan:{val}"].append(idx)
        for val in rec.insurance_ids:
            blocks[f"ins:{val}"].append(idx)
        for val in rec.emails:
            blocks[f"em:{val}"].append(idx)
        for ns, lid in rec.local_ids:
            blocks[f"loc:{ns}:{lid}"].append(idx)
        for ph in rec.phones:
            blocks[f"ph:{ph}"].append(idx)
        if rec.dob:
            blocks[f"dob:{rec.dob}"].append(idx)
        for name_toks in rec.names:
            for tok in name_toks:
                if len(tok) > 1:
                    blocks[f"nt:{tok}"].append(idx)
        for rel_toks in rec.relatives:
            for tok in rel_toks:
                if len(tok) > 1:
                    blocks[f"rt:{tok}"].append(idx)
    return blocks


def resolve_batch(
    evidences: list[Evidence] | tuple[Evidence, ...],
    secret: bytes | str,
    *,
    max_date_shift_days: int = 180,
) -> list[LinkResult]:
    """Link corroborated records in memory and return pseudonyms + stable date offsets.

    Weak or uncorroborated records abstain with ``pseudonym=None`` while still receiving
    a deterministic, secret-dependent ``date_offset_days`` so any internal stay intervals
    remain shiftable and consistent.
    """
    if not evidences:
        return []

    normed = [_normalize_evidence(i, ev) for i, ev in enumerate(evidences)]
    # Sort deterministically by canonical signature so clustering is order-invariant
    sorted_recs = sorted(normed, key=lambda r: r.canonical_sig)
    n = len(sorted_recs)
    shared_phones = _detect_shared_phones(sorted_recs)

    blocks = _generate_blocks(sorted_recs)
    seen_pairs: set[tuple[int, int]] = set()
    edges: list[tuple[int, bool, int, int]] = []
    for indices in blocks.values():
        if len(indices) < 2:
            continue
        for pos_a in range(len(indices)):
            i = indices[pos_a]
            for pos_b in range(pos_a + 1, len(indices)):
                j = indices[pos_b]
                pair = (i, j) if i < j else (j, i)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                score, allow_geo = _score_pair(sorted_recs[pair[0]], sorted_recs[pair[1]], shared_phones)
                if score > 0:
                    edges.append((score, allow_geo, pair[0], pair[1]))

    # Highest-confidence merges first; tie-break deterministically
    edges.sort(key=lambda e: (-e[0], e[2], e[3]))

    parent = list(range(n))
    clusters = {i: _ClusterState.from_record(i, sorted_recs[i]) for i in range(n)}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _score, allow_geo, i, j in edges:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        if _clusters_conflict(clusters[ri], clusters[rj], allow_geo_diff=allow_geo):
            continue
        # Merge smaller or higher index into lower root deterministically
        keep, drop = (ri, rj) if ri < rj else (rj, ri)
        parent[drop] = keep
        clusters[keep].merge_from(clusters.pop(drop))

    aliases: dict[int, tuple[str, str]] = {}
    for root, cluster in clusters.items():
        if len(cluster.members) >= 2 or _has_standalone_anchor(sorted_recs[root], shared_phones):
            key = _cluster_key(cluster)
            aliases[root] = key, derive_pseudonym(key, secret)
    alias_counts = Counter(psn for _, psn in aliases.values())

    results_by_orig: dict[int, LinkResult] = {}
    for root, cluster in clusters.items():
        representative = sorted_recs[root]
        key = f"abstain:{representative.source_namespace}:{representative.canonical_sig}"
        pseudonym = None
        reason = "insufficient_evidence"
        if root in aliases:
            cluster_key, candidate = aliases[root]
            if alias_counts[candidate] == 1:
                key, pseudonym, reason = cluster_key, candidate, "linked"
            else:
                # Do not publish a shared alias for clusters kept separate.
                reason = "ambiguous_pseudonym"
        offset = derive_date_offset(key, secret, max_days=max_date_shift_days)
        for idx in cluster.members:
            rec = sorted_recs[idx]
            results_by_orig[rec.orig_index] = LinkResult(
                record_id=rec.record_id,
                pseudonym=pseudonym,
                date_offset_days=offset,
                linked=pseudonym is not None,
                reason=reason,
            )

    return [results_by_orig[i] for i in range(len(evidences))]


def resolve_record(
    evidence: Evidence,
    source_namespace: str,
    secret: bytes | str,
    *,
    max_date_shift_days: int = 180,
) -> LinkResult:
    """Single-record boundary taking normalized evidence, source namespace, and secret."""
    scoped = Evidence(
        record_id=evidence.record_id,
        source_namespace=source_namespace or evidence.source_namespace,
        names=evidence.names,
        relatives=evidence.relatives,
        local_ids=evidence.local_ids,
        aadhaar=evidence.aadhaar,
        aadhaar_last4=evidence.aadhaar_last4,
        abha=evidence.abha,
        pan=evidence.pan,
        insurance_ids=evidence.insurance_ids,
        emails=evidence.emails,
        phones=evidence.phones,
        dob=evidence.dob,
        age=evidence.age,
        gender=evidence.gender,
        village=evidence.village,
        district=evidence.district,
        pin=evidence.pin,
    )
    return resolve_batch([scoped], secret, max_date_shift_days=max_date_shift_days)[0]
