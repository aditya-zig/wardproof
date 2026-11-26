"""End-to-end synthetic release pipeline tests (formats, linkage, quarantine, determinism)."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from main import run


class TestReleasePipeline(unittest.TestCase):
    def test_fhir_documents_are_quarantined_without_release_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp, out = root / "input", root / "output"
            inp.mkdir()
            fixtures = (
                {"resourceType": "Bundle", "type": "collection", "entry": []},
                {"resourceType": "Observation", "status": "final", "code": {"text": "Temperature"}},
            )
            for i, document in enumerate(fixtures):
                (inp / f"resource-{i}.json").write_text(json.dumps(document), encoding="utf-8")

            report = run(inp, out, b"synthetic-secret")

            self.assertEqual(report["counts"]["files_quarantined"], len(fixtures))
            for file in report["files"]:
                self.assertEqual(file["status"], "quarantined")
                self.assertEqual(file["reason"], "unsupported_fhir_release")
                self.assertIsNone(file["output"])
            self.assertEqual(list((out / "sanitized").iterdir()), [])
            self.assertEqual((out / "records.jsonl").read_text(encoding="utf-8"), "")

    def _build_synthetic_input(self, root: Path) -> None:
        (root / "registration").mkdir()
        (root / "discharge").mkdir()
        (root / "misc").mkdir()
        (root / "clean").mkdir()

        # 1. Registration CSV
        (root / "registration" / "reg.csv").write_text(
            "UHID,Patient Name,Gender,Age,Relative Name,Village/Mohalla,District,PIN,Mobile,Reg Date\n"
            "SNJ/26/001,Ramesh Verma,M,48,Suresh Verma,Kalyanpur,Sitapur,261001,+91 98765 43210,10/01/2026\n",
            encoding="utf-8",
        )
        # 2. Discharge summary with 9-day stay + eponyms + meds
        (root / "discharge" / "ds_001.txt").write_text(
            "DISCHARGE SUMMARY\n"
            "Patient Name: Ramesh Verma   Age/Sex: 48 Yrs/M\n"
            "UHID: SNJ/26/001\n"
            "S/o Suresh Verma\n"
            "Date of Admission: 2026-01-10\n"
            "Date of Discharge: 2026-01-19\n"
            "Consultant: Dr. Kavita Nair (MD Medicine)\n"
            "K/C/O Addison's disease. C/O: fever x 3 days.\n"
            "1. Tab Ramipril 5 mg 0-0-1 x 1 month\n",
            encoding="utf-8",
        )
        # 3. Malformed JSON + binary PDF (must quarantine, never copy raw)
        (root / "misc" / "broken.json").write_text("{bad json", encoding="utf-8")
        (root / "misc" / "scan.pdf").write_bytes(b"%PDF-1.4\nRamesh Verma\n%%EOF")
        # 4. Reference note goes through normal text processing.
        (root / "clean" / "protocol.txt").write_text("Standard fever protocol: Paracetamol 650 mg SOS.\n", encoding="utf-8")

    def test_end_to_end_sanitization_quarantine_determinism_and_secret_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            inp = tmp_path / "input"
            inp.mkdir()
            self._build_synthetic_input(inp)

            out1 = tmp_path / "out1"
            out2 = tmp_path / "out2"
            out3 = tmp_path / "out3"

            run(inp, out1, b"secret-one")
            run(inp, out2, b"secret-one")
            run(inp, out3, b"secret-two")

            # Determinism: identical secret -> identical report counts & sanitized outputs
            r1 = json.loads((out1 / "report.json").read_text(encoding="utf-8"))
            r2 = json.loads((out2 / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(r1["counts"], r2["counts"])
            self.assertEqual(r1["counts"]["files_sanitized"], 3)
            self.assertEqual(r1["counts"]["files_quarantined"], 2)

            # Secret rotation: different secret -> different pseudonyms
            links1 = [json.loads(line) for line in (out1 / "records.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            links3 = [json.loads(line) for line in (out3 / "records.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            psns1 = {l["patient"] for l in links1 if l["patient"]}
            psns3 = {l["patient"] for l in links3 if l["patient"]}
            self.assertEqual(len(psns1), 1)  # reg + ds linked to same pseudonym!
            self.assertNotEqual(psns1, psns3)

            # Verify no PII leaked & medical + LOS preserved in discharge summary
            output_paths = [f["output"] for f in r1["files"] if f["output"] is not None]
            for path in output_paths:
                self.assertRegex(path, r"^sanitized/[0-9a-f]{24}\.(?:csv|txt)$")
            notes = [path for path in output_paths if path.endswith(".txt")]
            self.assertEqual(len(notes), 2)
            note_texts = {(out1 / path).read_text(encoding="utf-8"): path for path in notes}
            protocol = [text for text in note_texts if "Paracetamol 650 mg SOS" in text]
            self.assertEqual(len(protocol), 1)
            self.assertIn(note_texts[protocol[0]], {link["file"] for link in links1})
            ds_text = next(text for text in note_texts if "DISCHARGE SUMMARY" in text)
            self.assertNotIn("Ramesh Verma", ds_text)
            self.assertNotIn("Suresh Verma", ds_text)
            self.assertIn("45-49 Yrs/M", ds_text)
            self.assertIn("Dr. Kavita Nair", ds_text)
            self.assertIn("Addison's disease", ds_text)
            self.assertIn("Tab Ramipril 5 mg 0-0-1 x 1 month", ds_text)

            # Verify 9-day LOS preserved after date shifting
            import re
            adm_m = re.search(r"Date of Admission:\s*(\d{4}-\d{2}-\d{2})", ds_text)
            dis_m = re.search(r"Date of Discharge:\s*(\d{4}-\d{2}-\d{2})", ds_text)
            self.assertIsNotNone(adm_m)
            self.assertIsNotNone(dis_m)
            self.assertEqual((date.fromisoformat(dis_m.group(1)) - date.fromisoformat(adm_m.group(1))).days, 9)


if __name__ == "__main__":
    unittest.main()
