"""Independent synthetic test suite for patient linkage and date shifting (Issue #2)."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from identity import (
    Evidence,
    LinkResult,
    derive_date_offset,
    derive_pseudonym,
    resolve_batch,
    resolve_record,
    shift_date,
    shift_iso_date,
    shift_stay,
)


SECRET_A = b"synthetic-test-secret-alpha-2026"
SECRET_B = b"synthetic-test-secret-beta-2026"


class TestLinkageAndDates(unittest.TestCase):
    def test_abbreviated_and_transliterated_names_link_with_corroboration(self) -> None:
        records = [
            Evidence(
                record_id="reg:0",
                source_namespace="hospital_east",
                names=["Mohammad Irfan Ansari"],
                relatives=["Tariq Ansari"],
                local_ids=["EAST-1042"],
                phones=["+91 98112 33445"],
                age=41,
                gender="M",
                village="Bijnor Kalan",
                district="Bijnor",
            ),
            Evidence(
                record_id="note:1",
                source_namespace="hospital_east",
                names=["Md. Irfan Ansari", "Irfan sahab"],
                relatives=["Tariq"],
                gender="M",
            ),
            Evidence(
                record_id="rx:2",
                source_namespace="clinic_north",
                names=["मोहम्मद इरफ़ान अंसारी"],
                age=41,
                village="बिजनौर कलां",
            ),
            Evidence(
                record_id="lab:3",
                source_namespace="lab_central",
                names=["Mohd. Irfan"],
                phones=["09811233445"],
                gender="M",
            ),
            Evidence(
                record_id="fwd:4",
                source_namespace="whatsapp",
                names=["Irfan ji"],
                relatives=["Tariq Chachu"],
                phones=["98112 33445"],
            ),
        ]

        results = resolve_batch(records, SECRET_A)
        pseudonyms = {r.record_id: r.pseudonym for r in results}
        offsets = {r.record_id: r.date_offset_days for r in results}

        self.assertIsNotNone(pseudonyms["reg:0"])
        self.assertEqual(len(set(pseudonyms.values())), 1)
        self.assertEqual(len(set(offsets.values())), 1)
        self.assertNotEqual(offsets["reg:0"], 0)

    def test_relatives_corroborate_fragmented_hindi_and_english_records(self) -> None:
        records = [
            Evidence(
                record_id="reg:0",
                source_namespace="hosp_a",
                names=["Kavita Chauhan"],
                relatives=["Devendra Chauhan"],
                local_ids=["HA-9001"],
                dob="1988-06-14",
                gender="F",
                village="Rampur Maniharan",
            ),
            Evidence(
                record_id="frag:1",
                source_namespace="hosp_a",
                names=["Kavita"],
                relatives=["Devendra"],
                gender="F",
            ),
            Evidence(
                record_id="rx:2",
                source_namespace="hosp_b",
                names=["कविता चौहान"],
                relatives=["देवेंद्र चौहान"],
                gender="F",
            ),
        ]

        results = resolve_batch(records, SECRET_A)
        psns = [r.pseudonym for r in results]
        self.assertTrue(all(p is not None for p in psns))
        self.assertEqual(len(set(psns)), 1)

    def test_shared_household_phone_does_not_merge_distinct_people(self) -> None:
        records = [
            Evidence(
                record_id="wife:0",
                source_namespace="clinic_1",
                names=["Neelam Mishra"],
                phones=["+91-9123456789"],
                age=34,
                gender="F",
                village="Chandauli",
            ),
            Evidence(
                record_id="husband:1",
                source_namespace="clinic_1",
                names=["Sandeep Mishra"],
                phones=["9123456789"],
                age=39,
                gender="M",
                village="Chandauli",
            ),
            Evidence(
                record_id="unnamed:2",
                source_namespace="clinic_1",
                phones=["9123456789"],
            ),
            Evidence(
                record_id="wife_followup:3",
                source_namespace="clinic_2",
                names=["Neelam Mishra"],
                phones=["9123456789"],
                age=34,
                gender="F",
            ),
        ]

        by_id = {r.record_id: r for r in resolve_batch(records, SECRET_A)}
        self.assertIsNotNone(by_id["wife:0"].pseudonym)
        self.assertIsNotNone(by_id["husband:1"].pseudonym)
        self.assertNotEqual(by_id["wife:0"].pseudonym, by_id["husband:1"].pseudonym)
        # Wife follow-up corroborates wife (same name, gender, age, shared phone)
        self.assertEqual(by_id["wife:0"].pseudonym, by_id["wife_followup:3"].pseudonym)
        # Unnamed record with only a shared household phone must abstain
        self.assertIsNone(by_id["unnamed:2"].pseudonym)

    def test_conflicting_ids_and_demographics_block_merge(self) -> None:
        records = [
            Evidence(
                record_id="p1",
                source_namespace="hosp_1",
                names=["Prakash Tiwari"],
                aadhaar=["412345678901"],
                phones=["9822011223"],
                dob="1979-03-10",
                gender="M",
                village="Gonda Khas",
            ),
            Evidence(
                record_id="p2_conflict_aadhaar",
                source_namespace="hosp_2",
                names=["Prakash Tiwari"],
                aadhaar=["498765432109"],
                phones=["9822011223"],
                dob="1979-03-10",
                gender="M",
                village="Gonda Khas",
            ),
            Evidence(
                record_id="p3_conflict_abha",
                source_namespace="hosp_2",
                names=["Suresh Verma"],
                abha=["91-1111-2222-3333"],
                dob="1981-07-15",
                gender="M",
            ),
            Evidence(
                record_id="p4_conflict_abha",
                source_namespace="hosp_3",
                names=["Suresh Verma"],
                abha=["91-4444-5555-6666"],
                dob="1981-07-15",
                gender="M",
            ),
            Evidence(
                record_id="p5_conflict_dob",
                source_namespace="hosp_4",
                names=["Prakash Tiwari"],
                phones=["9822011223"],
                dob="1985-11-02",
                gender="M",
            ),
            Evidence(
                record_id="p6_conflict_pan",
                source_namespace="hosp_4",
                names=["Mahesh Gupta"],
                pan=["ABCDE1234F"],
                gender="M",
            ),
            Evidence(
                record_id="p7_conflict_pan",
                source_namespace="hosp_5",
                names=["Mahesh Gupta"],
                pan=["ZYXWV9876A"],
                gender="M",
            ),
        ]

        by_id = {r.record_id: r for r in resolve_batch(records, SECRET_A)}
        keys = [
            "p1",
            "p2_conflict_aadhaar",
            "p3_conflict_abha",
            "p4_conflict_abha",
            "p5_conflict_dob",
            "p6_conflict_pan",
            "p7_conflict_pan",
        ]
        psns = [by_id[k].pseudonym for k in keys]
        self.assertTrue(all(p is not None for p in psns))
        self.assertEqual(len(set(psns)), len(keys))

    def test_duplicate_generated_aliases_are_not_published(self) -> None:
        records = [
            Evidence(record_id="a", source_namespace="hospital_a", local_ids=["L-1001"]),
            Evidence(record_id="b", source_namespace="hospital_b", local_ids=["L-1002"]),
        ]
        self.assertTrue(all(result.linked for result in resolve_batch(records, SECRET_A)))

        with patch("identity.linker.derive_pseudonym", return_value="PSN-fixed"):
            results = resolve_batch(records, SECRET_A)
        for result in results:
            self.assertIsNone(result.pseudonym)
            self.assertFalse(result.linked)
            self.assertEqual(result.reason, "ambiguous_pseudonym")

    def test_distinct_namesakes_never_merge(self) -> None:
        records = [
            Evidence(
                record_id="ritu_young:0",
                source_namespace="hosp_a",
                names=["Ritu Sharma"],
                relatives=["Harish Sharma"],
                local_ids=["HA-111"],
                age=28,
                gender="F",
                village="Nandpur",
                district="Aligarh",
            ),
            Evidence(
                record_id="ritu_young:1",
                source_namespace="hosp_b",
                names=["ऋतु शर्मा"],
                relatives=["हरीश शर्मा"],
                age=28,
                gender="F",
                village="नंदपुर",
                district="Aligarh",
            ),
            Evidence(
                record_id="ritu_elder:0",
                source_namespace="hosp_a",
                names=["Ritu Sharma"],
                relatives=["Mahesh Sharma"],
                local_ids=["HA-999"],
                age=63,
                gender="F",
                village="Kalyanpur",
                district="Aligarh",
            ),
        ]

        by_id = {r.record_id: r for r in resolve_batch(records, SECRET_A)}
        self.assertEqual(by_id["ritu_young:0"].pseudonym, by_id["ritu_young:1"].pseudonym)
        self.assertIsNotNone(by_id["ritu_elder:0"].pseudonym)
        self.assertNotEqual(by_id["ritu_young:0"].pseudonym, by_id["ritu_elder:0"].pseudonym)

    def test_source_namespace_isolates_local_ids(self) -> None:
        records = [
            Evidence(
                record_id="a1",
                source_namespace="hospital_alpha",
                names=["Sanjay Verma"],
                local_ids=["OPD-404"],
                age=32,
                gender="M",
            ),
            Evidence(
                record_id="b1",
                source_namespace="hospital_beta",
                names=["Vikram Joshi"],
                local_ids=["OPD-404"],
                age=50,
                gender="M",
            ),
            Evidence(
                record_id="a2",
                source_namespace="hospital_alpha",
                names=["S. Verma"],
                local_ids=["OPD-404"],
                gender="M",
            ),
        ]

        by_id = {r.record_id: r for r in resolve_batch(records, SECRET_A)}
        self.assertEqual(by_id["a1"].pseudonym, by_id["a2"].pseudonym)
        self.assertNotEqual(by_id["a1"].pseudonym, by_id["b1"].pseudonym)

    def test_weak_evidence_returns_null_pseudonym(self) -> None:
        records = [
            Evidence(record_id="bare_first", source_namespace="notes", names=["Deepak"]),
            Evidence(record_id="bare_name", source_namespace="notes", names=["Kiran Devi"]),
            Evidence(record_id="clean_doc", source_namespace="clean"),
            Evidence(record_id="village_only", source_namespace="notes", village="Nandpur", age=40),
        ]
        results = resolve_batch(records, SECRET_A)
        for r in results:
            self.assertIsNone(r.pseudonym, f"Expected abstention for {r.record_id}")
            self.assertFalse(r.linked)

        single = resolve_record(
            Evidence(record_id="single_weak", source_namespace="notes", names=["Deepak"]),
            "notes",
            SECRET_A,
        )
        self.assertIsNone(single.pseudonym)

    def test_nine_day_stay_and_cross_record_intervals_preserved(self) -> None:
        records = [
            Evidence(
                record_id="adm",
                source_namespace="hosp_x",
                names=["Anjali Kulkarni"],
                aadhaar=["556677889900"],
                gender="F",
            ),
            Evidence(
                record_id="disch",
                source_namespace="hosp_x",
                names=["Anjali Kulkarni"],
                aadhaar=["556677889900"],
                gender="F",
            ),
        ]
        by_id = {r.record_id: r for r in resolve_batch(records, SECRET_A)}
        offset = by_id["adm"].date_offset_days
        self.assertEqual(offset, by_id["disch"].date_offset_days)
        self.assertNotEqual(offset, 0)

        admit = dt.date(2026, 4, 10)
        discharge = dt.date(2026, 4, 19)
        self.assertEqual((discharge - admit).days, 9)

        shifted_admit, shifted_discharge = shift_stay(admit, discharge, offset)
        self.assertEqual((shifted_discharge - shifted_admit).days, 9)
        self.assertNotEqual(shifted_admit, admit)
        self.assertEqual(shift_iso_date("2026-04-10", offset), shifted_admit.isoformat())
        self.assertEqual(shift_date(discharge, offset), shifted_discharge)

    def test_determinism_order_invariance_and_secret_rotation(self) -> None:
        records = [
            Evidence(
                record_id="r1",
                source_namespace="s1",
                names=["Farhan Siddiqui"],
                relatives=["Rashid Siddiqui"],
                local_ids=["S1-200"],
                dob="1991-08-22",
                gender="M",
            ),
            Evidence(
                record_id="r2",
                source_namespace="s2",
                names=["फ़रहान सिद्दीक़ी"],
                relatives=["रशीद सिद्दीक़ी"],
                dob="1991-08-22",
                gender="M",
            ),
        ]
        res_a1 = {r.record_id: r for r in resolve_batch(records, SECRET_A)}
        res_a2 = {r.record_id: r for r in resolve_batch(list(reversed(records)), SECRET_A)}
        res_b = {r.record_id: r for r in resolve_batch(records, SECRET_B)}

        self.assertEqual(res_a1["r1"].pseudonym, res_a2["r1"].pseudonym)
        self.assertEqual(res_a1["r1"].date_offset_days, res_a2["r1"].date_offset_days)
        self.assertNotEqual(res_a1["r1"].pseudonym, res_b["r1"].pseudonym)
        self.assertNotEqual(res_a1["r1"].date_offset_days, res_b["r1"].date_offset_days)

        # Verify non-reversibility (pseudonym is not an unkeyed hash or raw token)
        psn = res_a1["r1"].pseudonym or ""
        self.assertTrue(psn.startswith("PSN-"))
        self.assertNotIn("farhan", psn.lower())
        self.assertNotIn("200", psn)
        raw_sha = hashlib.sha256(b"Farhan Siddiqui").hexdigest().upper()
        self.assertNotIn(psn[4:], raw_sha)

    def test_no_plaintext_lookup_tables_written_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd_before = os.getcwd()
            try:
                os.chdir(tmp)
                records = [
                    Evidence(
                        record_id="rec1",
                        source_namespace="hosp_z",
                        names=["Meera Nair"],
                        aadhaar=["667788990011"],
                        gender="F",
                    ),
                ]
                _ = resolve_batch(records, SECRET_A)
                _ = derive_pseudonym("aadhaar:667788990011", SECRET_A)
                _ = derive_date_offset("aadhaar:667788990011", SECRET_A)
                written = list(Path(tmp).rglob("*"))
                self.assertEqual(written, [])
            finally:
                os.chdir(cwd_before)


if __name__ == "__main__":
    unittest.main()
