"""k-anonymity and quasi-identifier re-identification risk analysis.

Standard-library Python only. Evaluates equivalence classes over
(age_band, sex, district) without storing or logging raw patient identities.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from identity.linkage import IdentityEvidence, generalize_age


@dataclass(frozen=True)
class PrivacyRiskReport:
    """Aggregate quasi-identifier risk metrics for a release."""

    total_profiles: int
    equivalence_classes: int
    k_min: int
    k1_unique_profiles: int
    k2_small_profiles: int
    residual_k1_ratio: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "total_profiles": self.total_profiles,
            "equivalence_classes": self.equivalence_classes,
            "k_min": self.k_min,
            "k1_unique_profiles": self.k1_unique_profiles,
            "k2_small_profiles": self.k2_small_profiles,
            "residual_k1_ratio": self.residual_k1_ratio,
        }


def analyze_equivalence_classes(
    profiles: Iterable[tuple[str | None, IdentityEvidence, str]],
) -> PrivacyRiskReport:
    """Compute k-anonymity risk metrics over linked patient profiles.

    Each item is (pseudonym, evidence, district).
    """
    seen_psn: dict[str, tuple[str, str, str]] = {}
    for psn, ev, district in profiles:
        key = psn or ev.record_id
        age_band = generalize_age(ev.age) or "unknown"
        sex = ev.sex or "unknown"
        dist = (district or "unknown").strip().casefold()
        if key not in seen_psn:
            seen_psn[key] = (age_band, sex, dist)

    if not seen_psn:
        return PrivacyRiskReport(
            total_profiles=0,
            equivalence_classes=0,
            k_min=0,
            k1_unique_profiles=0,
            k2_small_profiles=0,
            residual_k1_ratio=0.0,
        )

    eq_counts = Counter(seen_psn.values())
    total = len(seen_psn)
    k1 = sum(c for c in eq_counts.values() if c == 1)
    k2 = sum(c for c in eq_counts.values() if c == 2)
    k_min = min(eq_counts.values())
    return PrivacyRiskReport(
        total_profiles=total,
        equivalence_classes=len(eq_counts),
        k_min=k_min,
        k1_unique_profiles=k1,
        k2_small_profiles=k2,
        residual_k1_ratio=round(k1 / total, 4),
    )
