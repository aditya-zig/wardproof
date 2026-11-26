"""Synthetic unit tests for cross-script patient linkage, date shifting, and generalization."""

from __future__ import annotations

import unittest

from identity.linkage import (
    IdentityEvidence,
    PatientLinkageIndex,
    generalize_age,
    generalize_pin,
    normalize_name,
    shift_date_string,
)


class TestPatientLinkage(unittest.TestCase):
    def test_cross_script_corroborated_records_match_and_homonyms_stay_separate(self) -> None:
        idx = PatientLinkageIndex(secret=b"test-secret-1")
        # Same person in English registration + Hindi prescription (corroborated by sex+age)
        idx.add(IdentityEvidence(record_id="reg#row:0", uhids={"SNJ/26/001"}, name_norm=normalize_name("Mohammad Shahid"), sex="M", age=39))
        idx.add(IdentityEvidence(record_id="rx#doc", name_norm=normalize_name("मोहम्मद शाहिद"), sex="M", age=39))
        # Namesake homonym (different age and sex/relative) must NOT merge
        idx.add(IdentityEvidence(record_id="other#row:0", uhids={"JJH-0099"}, name_norm=normalize_name("Mohammad Shahid"), sex="M", age=67))
        # Weak uncorroborated record must abstain
        idx.add(IdentityEvidence(record_id="weak#doc", name_norm=normalize_name("Meera")))

        p1 = idx.pseudonym("reg#row:0")
        p2 = idx.pseudonym("rx#doc")
        p3 = idx.pseudonym("other#row:0")
        p4 = idx.pseudonym("weak#doc")

        self.assertIsNotNone(p1)
        self.assertEqual(p1, p2)
        self.assertNotEqual(p1, p3)
        self.assertIsNone(p4)

    def test_date_shift_preserves_length_of_stay_and_rotates_with_secret(self) -> None:
        idx1 = PatientLinkageIndex(secret=b"secret-alpha")
        idx1.add(IdentityEvidence(record_id="ds#doc", uhids={"UHID-100"}))
        off1 = idx1.date_offset("ds#doc")
        adm = shift_date_string("2026-01-13", off1)
        dis = shift_date_string("2026-01-22", off1)

        from datetime import date
        self.assertEqual((date.fromisoformat(dis) - date.fromisoformat(adm)).days, 9)

        idx2 = PatientLinkageIndex(secret=b"secret-beta")
        idx2.add(IdentityEvidence(record_id="ds#doc", uhids={"UHID-100"}))
        self.assertNotEqual(idx1.pseudonym("ds#doc"), idx2.pseudonym("ds#doc"))
        self.assertNotEqual(off1, idx2.date_offset("ds#doc"))

    def test_generalization_helpers(self) -> None:
        self.assertEqual(generalize_age(48), "45-49")
        self.assertEqual(generalize_age(91), "85+")
        self.assertEqual(generalize_pin("229073"), "229xxx")


if __name__ == "__main__":
    unittest.main()
