"""Synthetic test suite for clinical text sanitization and meaning preservation."""

from __future__ import annotations

import logging
import unittest

from clinical.text import SanitizationResult, sanitize_record, sanitize_text


class TestEnglishClinicalSanitization(unittest.TestCase):
    def test_co_fever_preserved_vs_care_of_relative_redacted(self) -> None:
        medical = "C/O: fever x 4 days, dry cough\nK/C/O: hypertension"
        res_med = sanitize_text(medical, field="clinical_note")
        self.assertIsInstance(res_med, SanitizationResult)
        self.assertIn("C/O: fever x 4 days, dry cough", res_med.text)
        self.assertIn("K/C/O: hypertension", res_med.text)
        self.assertEqual(res_med.language, "english")

        relative = "C/O Naresh Chauhan, H.No. 42, Mohalla Shastri Nagar, PIN 226001"
        res_rel = sanitize_text(relative, field="address")
        self.assertNotIn("Naresh Chauhan", res_rel.text)
        self.assertNotIn("226001", res_rel.text)
        self.assertGreater(res_rel.counts.get("RELATIVE_NAME", 0), 0)

    def test_exact_medications_doses_units_frequencies_preserved(self) -> None:
        note = (
            "Rx\n"
            "1. Tab Ramipril 5 mg 0-0-1 x 1 month\n"
            "2. Tab Paracetamol 650mg 1-1-1 x 5 days\n"
            "3. Inj Ceftriaxone 1g IV x 2 wks\n"
            "4. Tab Levothyroxine 50 mcg 1-0-0 x 1 month\n"
            "5. Inh Salbutamol 100 mcg 2 puffs SOS\n"
            "Vitals: BP 117/82, Pulse 106, Temp 103 F, RBS 145 mg/dL, SpO2 98%."
        )
        res = sanitize_text(note, field="prescription")
        for expected in (
            "Ramipril 5 mg",
            "0-0-1 x 1 month",
            "Paracetamol 650mg",
            "1-1-1 x 5 days",
            "Ceftriaxone 1g IV x 2 wks",
            "Levothyroxine 50 mcg 1-0-0",
            "Salbutamol 100 mcg 2 puffs SOS",
            "BP 117/82",
            "Pulse 106",
            "Temp 103 F",
            "RBS 145 mg/dL",
            "SpO2 98%",
        ):
            self.assertIn(expected, res.text)
        self.assertEqual(sum(res.counts.values()), 0)

    def test_eponyms_preserved_even_with_possessive(self) -> None:
        note = (
            "K/C/O Addison's disease and Hashimoto's thyroiditis. "
            "Rule out Parkinson's disease, Bell's palsy, or Graves' disease. "
            "History of Hodgkin's lymphoma; Murphy's sign negative; Pott's spine."
        )
        res = sanitize_text(note, field="clinical_note")
        for eponym in (
            "Addison's disease",
            "Hashimoto's thyroiditis",
            "Parkinson's disease",
            "Bell's palsy",
            "Graves' disease",
            "Hodgkin's lymphoma",
            "Murphy's sign",
            "Pott's spine",
        ):
            self.assertIn(eponym, res.text)

    def test_negation_allergy_family_history_never_positive(self) -> None:
        note = (
            "C/O fever x 3 days. "
            "Denies chest pain or dyspnea. No history of diabetes. "
            "Allergic to Penicillin and Sulfa drugs. "
            "Family history: Father Ramesh Verma had coronary artery disease."
        )
        res = sanitize_text(note, field="clinical_note")
        self.assertIn("C/O fever x 3 days", res.text)
        self.assertIn("Denies chest pain or dyspnea", res.text)
        self.assertIn("No history of diabetes", res.text)
        self.assertIn("Allergic to Penicillin and Sulfa drugs", res.text)
        self.assertNotIn("Ramesh Verma", res.text)
        self.assertIn("Father", res.text)
        self.assertIn("coronary artery disease", res.text)

        positive_texts = [a.text.casefold() for a in res.assertions if a.polarity == "positive"]
        negated_texts = [a.text.casefold() for a in res.assertions if a.polarity == "negated"]
        allergy_texts = [a.text.casefold() for a in res.assertions if a.polarity == "allergy"]
        fh_texts = [a.text.casefold() for a in res.assertions if a.polarity == "family_history"]

        self.assertTrue(any("fever" in t for t in positive_texts))
        self.assertTrue(any("chest pain" in t for t in negated_texts))
        self.assertTrue(any("diabetes" in t for t in negated_texts))
        self.assertTrue(any("penicillin" in t for t in allergy_texts))
        self.assertTrue(any("coronary artery disease" in t for t in fh_texts))
        self.assertFalse(any("chest pain" in t or "diabetes" in t or "penicillin" in t for t in positive_texts))

    def test_negation_scoped_to_right_finding_comma_separated(self) -> None:
        res = sanitize_text("No fever, cough present.", field="clinical_note")
        self.assertIn("No fever", res.text)
        self.assertIn("cough present", res.text)

        positive_texts = [a.text.casefold() for a in res.assertions if a.polarity == "positive"]
        negated_texts = [a.text.casefold() for a in res.assertions if a.polarity == "negated"]

        self.assertTrue(any("fever" in t for t in negated_texts))
        self.assertFalse(any("fever" in t for t in positive_texts))
        self.assertTrue(any("cough" in t for t in positive_texts))

    def test_unmatched_free_text_name_redacted_without_context(self) -> None:
        res = sanitize_text("Meera Shah presented with fever.", field="clinical_note")
        self.assertNotIn("Meera Shah", res.text)
        self.assertIn("fever", res.text)
        self.assertGreater(res.counts.get("PATIENT_NAME", 0), 0)

    def test_clinician_vs_relative_and_unverified_doctor(self) -> None:
        # Verified clinicians (credentials or trustworthy role label) are preserved
        verified = (
            "Consulting Physician: Dr. Kavita Nair (MD Medicine)\n"
            "Signed by Dr. Arvind Kulkarni, MBBS, MS (Ortho)"
        )
        res_ok = sanitize_text(verified, field="prescription")
        self.assertIn("Dr. Kavita Nair", res_ok.text)
        self.assertIn("Dr. Arvind Kulkarni", res_ok.text)

        # Unverified or patient/relative Dr. must be redacted
        unverified = (
            "Patient: Dr. Vikram Sethi\n"
            "Attendant (S/o Dr. Mohan Lal)\n"
            "C/O Dr. Suresh Gupta\n"
            "Met Dr. Ananya Sharma near gate."
        )
        res_bad = sanitize_text(unverified, field="clinical_note")
        for leaked in ("Vikram Sethi", "Mohan Lal", "Suresh Gupta", "Ananya Sharma"):
            self.assertNotIn(leaked, res_bad.text)
        self.assertGreater(res_bad.counts.get("UNVERIFIED_DOCTOR", 0) + res_bad.counts.get("PATIENT_NAME", 0) + res_bad.counts.get("RELATIVE_NAME", 0), 0)


class TestHindiClinicalSanitization(unittest.TestCase):
    def test_hindi_patient_name_and_village_removed_medical_kept(self) -> None:
        note = (
            "नाम: मोहम्मद शाहिद   आयु: 39 वर्ष\n"
            "ग्राम: मोहनगंज कलां\n"
            "मोहम्मद शाहिद को 9 दिन से बुखार है।\n"
            "Rx\n"
            "1. Tab Paracetamol 650mg 1-1-1 x 5 days\n"
            "Dr. Ramesh Srivastava (MD Medicine)"
        )
        res = sanitize_text(note, field="prescription")
        self.assertEqual(res.language, "hindi")
        self.assertNotIn("मोहम्मद शाहिद", res.text)
        self.assertNotIn("मोहनगंज कलां", res.text)
        self.assertIn("9 दिन से बुखार", res.text)
        self.assertIn("Tab Paracetamol 650mg 1-1-1 x 5 days", res.text)
        self.assertIn("Dr. Ramesh Srivastava", res.text)
        self.assertGreater(res.counts.get("PATIENT_NAME", 0), 0)

    def test_hindi_negation_allergy_family_history(self) -> None:
        note = (
            "मरीज को सीने में दर्द नहीं है। मधुमेह से इनकार।\n"
            "पेनिसिलिन से एलर्जी है।\n"
            "पारिवारिक इतिहास: पिता मोहन लाल को उच्च रक्तचाप।"
        )
        res = sanitize_text(note, field="clinical_note")
        self.assertIn("सीने में दर्द नहीं है", res.text)
        self.assertIn("मधुमेह से इनकार", res.text)
        self.assertIn("पेनिसिलिन से एलर्जी है", res.text)
        self.assertNotIn("मोहन लाल", res.text)
        self.assertIn("उच्च रक्तचाप", res.text)

        positive_texts = [a.text for a in res.assertions if a.polarity == "positive"]
        negated_texts = [a.text for a in res.assertions if a.polarity == "negated"]
        allergy_texts = [a.text for a in res.assertions if a.polarity == "allergy"]
        fh_texts = [a.text for a in res.assertions if a.polarity == "family_history"]

        self.assertTrue(any("सीने में दर्द" in t for t in negated_texts))
        self.assertTrue(any("मधुमेह" in t for t in negated_texts))
        self.assertTrue(any("पेनिसिलिन" in t for t in allergy_texts))
        self.assertTrue(any("उच्च रक्तचाप" in t for t in fh_texts))
        self.assertEqual(positive_texts, [])


class TestHinglishClinicalSanitization(unittest.TestCase):
    def test_hinglish_nursing_note_sanitized(self) -> None:
        note = (
            "NURSING NOTES - Ward 8 (Medicine), Bed 2 - ADM000161\n"
            "Shahid sahab ka BP 117/82, pulse 106. Bukhar 103 F. Paracetamol 650 mg diya.\n"
            "Patient ne raat theek se neend li. RBS 145 mg/dL.\n"
            "Mohd. Shahid - K/C/O addison's disease. Attendant (S/o Zubair) informed about diet."
        )
        res = sanitize_text(
            note,
            field="nursing_note",
            context={"patient_names": ["Mohd. Shahid", "Shahid"]},
        )
        self.assertEqual(res.language, "hinglish")
        self.assertNotIn("Shahid", res.text)
        self.assertNotIn("Zubair", res.text)
        self.assertNotIn("ADM000161", res.text)
        self.assertIn("BP 117/82", res.text)
        self.assertIn("pulse 106", res.text)
        self.assertIn("Bukhar 103 F", res.text)
        self.assertIn("Paracetamol 650 mg", res.text)
        self.assertIn("RBS 145 mg/dL", res.text)
        self.assertIn("K/C/O addison's disease", res.text)

    def test_hinglish_negation_and_allergy(self) -> None:
        note = (
            "Patient ko bukhar nahi hai, aur saans phoolna bhi nahi hai. "
            "Sulfa se allergy hai. F/H: Papa ko heart disease tha."
        )
        res = sanitize_text(note, field="clinical_note")
        self.assertIn("bukhar nahi hai", res.text)
        self.assertIn("Sulfa se allergy hai", res.text)
        self.assertIn("Papa ko heart disease tha", res.text)

        positive_texts = [a.text.casefold() for a in res.assertions if a.polarity == "positive"]
        negated_texts = [a.text.casefold() for a in res.assertions if a.polarity == "negated"]
        allergy_texts = [a.text.casefold() for a in res.assertions if a.polarity == "allergy"]
        fh_texts = [a.text.casefold() for a in res.assertions if a.polarity == "family_history"]

        self.assertTrue(any("bukhar" in t for t in negated_texts))
        self.assertTrue(any("sulfa" in t for t in allergy_texts))
        self.assertTrue(any("heart disease" in t for t in fh_texts))
        self.assertFalse(any("bukhar" in t or "sulfa" in t for t in positive_texts))


class TestIdentifiersAndLoggingHygiene(unittest.TestCase):
    def test_seeded_private_markers_and_ids_removed(self) -> None:
        note = (
            "Name: Asha Devi   Reg No: JJH-0076900   Mob: +91 80697 73173\n"
            "Aadhaar: 3972 0583 9628   ABHA: 91-7938-3729-8403   PAN: ABCDE1234F\n"
            "Email: asha.devi@example.org   ABHA Address: asha123@abdm\n"
            "Canary: CANARY-LOTUS-9912\n"
            "Diagnosis: Type 2 Diabetes Mellitus. Tab Metformin 500 mg BD."
        )
        res = sanitize_text(
            note,
            field="clinical_note",
            context={"private_markers": ["CANARY-LOTUS-9912"]},
        )
        for secret in (
            "Asha Devi",
            "JJH-0076900",
            "80697",
            "3972 0583 9628",
            "91-7938-3729-8403",
            "ABCDE1234F",
            "asha.devi@example.org",
            "asha123@abdm",
            "CANARY-LOTUS-9912",
        ):
            self.assertNotIn(secret, res.text)
        self.assertIn("Type 2 Diabetes Mellitus", res.text)
        self.assertIn("Tab Metformin 500 mg BD", res.text)

    def test_no_raw_matches_in_logs_or_counts(self) -> None:
        secret_name = "Raghavendra Kulkarni"
        secret_phone = "+91 98123 45678"
        note = f"Name: {secret_name}\nMob: {secret_phone}\nC/O: fever\nTab Ramipril 5 mg"

        with self.assertLogs("clinical.text", level=logging.DEBUG) as cm:
            res = sanitize_text(note, field="clinical_note")

        joined_logs = "\n".join(cm.output)
        self.assertNotIn(secret_name, joined_logs)
        self.assertNotIn(secret_phone, joined_logs)
        self.assertNotIn("98123", joined_logs)
        for key, val in res.counts.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(val, int)
            self.assertNotIn(secret_name, key)
            self.assertNotIn(secret_phone, key)

    def test_sanitize_record_returns_cleaned_dict_and_aggregate_counts(self) -> None:
        record = {
            "patient_name": "Sunita Yadav",
            "notes": "C/O: headache x 2 days. Tab Paracetamol 500 mg SOS.",
            "ref_doctor": "Dr. Neeraj Mishra (MD Medicine)",
        }
        cleaned, counts = sanitize_record(record)
        self.assertNotIn("Sunita Yadav", cleaned["patient_name"])
        self.assertIn("C/O: headache x 2 days", cleaned["notes"])
        self.assertIn("Tab Paracetamol 500 mg SOS", cleaned["notes"])
        self.assertIn("Dr. Neeraj Mishra", cleaned["ref_doctor"])
        self.assertGreater(counts.get("PATIENT_NAME", 0), 0)

    def test_initials_masked_aadhaar_insurance_phone_variants_and_determinism(self) -> None:
        note = (
            "R. K. Sharma presented with fever. Meera didi ka BP 120/80.\n"
            "श्रीमती कमला देवी को खांसी है।\n"
            "Masked Aadhaar: XXXX-XXXX-9628   Policy No: POL-998812\n"
            "Alt Phone: 098765-43210   Tab Dolo 650 mg 1-0-1 x 5 days."
        )
        res1 = sanitize_text(note, field="clinical_note")
        res2 = sanitize_text(note, field="clinical_note")
        self.assertEqual(res1, res2)

        for secret in (
            "R. K. Sharma",
            "Meera didi",
            "कमला देवी",
            "XXXX-XXXX-9628",
            "POL-998812",
            "098765-43210",
        ):
            self.assertNotIn(secret, res1.text)
        self.assertIn("fever", res1.text)
        self.assertIn("BP 120/80", res1.text)
        self.assertIn("Tab Dolo 650 mg 1-0-1 x 5 days", res1.text)
        self.assertGreater(res1.counts.get("AADHAAR_MASKED", 0), 0)
        self.assertGreater(res1.counts.get("INSURANCE_ID", 0), 0)
        self.assertGreater(res1.counts.get("PHONE", 0), 0)


if __name__ == "__main__":
    unittest.main()
