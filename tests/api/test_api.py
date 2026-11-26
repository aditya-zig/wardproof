"""End-to-end tests for the FastAPI WardProof backend."""

from __future__ import annotations

import io
import time
import unittest
import zipfile

from fastapi.testclient import TestClient

from api.app import create_app
from api.jobs import JobManager


class TestWardProofAPI(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(JobManager())
        self.client = TestClient(self.app)

    def test_health_endpoint(self) -> None:
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "service": "wardproof-backend", "offline": True})

    def test_full_job_lifecycle_upload_process_poll_and_download(self) -> None:
        # 1. Create job
        create_resp = self.client.post("/api/v1/jobs", json={"secret": "api-test-secret"})
        self.assertEqual(create_resp.status_code, 201)
        job_id = create_resp.json()["job_id"]

        # 2. Upload synthetic files (valid CSV + valid TXT + malformed JSON)
        csv_bytes = (
            b"UHID,Patient Name,Gender,Age,Mobile,Reg Date\n"
            b"SNJ/26/101,Meera Shah,F,44,+91 98765 43210,10/01/2026\n"
        )
        txt_bytes = (
            b"Patient Name: Meera Shah   Age/Sex: 44 Yrs/F\n"
            b"UHID: SNJ/26/101\n"
            b"C/O: fever x 3 days. Tab Ramipril 5 mg 0-0-1.\n"
        )
        bad_json = b"{not valid json"

        up_resp = self.client.post(
            f"/api/v1/jobs/{job_id}/files",
            files=[
                ("files", ("registration/reg.csv", csv_bytes, "text/csv")),
                ("files", ("notes/note.txt", txt_bytes, "text/plain")),
                ("files", ("misc/broken.json", bad_json, "application/json")),
            ],
        )
        self.assertEqual(up_resp.status_code, 200)
        self.assertEqual(up_resp.json()["files_uploaded"], 3)

        # 3. Start background processing
        proc_resp = self.client.post(f"/api/v1/jobs/{job_id}/process")
        self.assertEqual(proc_resp.status_code, 202)

        # 4. Poll until completed
        status_data = {}
        for _ in range(50):
            st = self.client.get(f"/api/v1/jobs/{job_id}")
            self.assertEqual(st.status_code, 200)
            status_data = st.json()
            if status_data["status"] == "completed":
                break
            time.sleep(0.05)
        self.assertEqual(status_data["status"], "completed")
        self.assertEqual(status_data["progress_pct"], 100.0)

        # 5. Summary, detections, identities, privacy-analysis, files, report
        summary = self.client.get(f"/api/v1/jobs/{job_id}/summary").json()
        self.assertEqual(summary["counts"]["files_total"], 3)
        self.assertEqual(summary["counts"]["files_sanitized"], 2)
        self.assertEqual(summary["counts"]["files_quarantined"], 1)

        detections = self.client.get(f"/api/v1/jobs/{job_id}/detections").json()
        self.assertGreater(detections["total_detections"], 0)
        self.assertNotIn("Meera Shah", str(detections))

        identities = self.client.get(f"/api/v1/jobs/{job_id}/identities").json()
        self.assertEqual(identities["linked_records"], 2)
        self.assertEqual(identities["unique_pseudonyms"], 1)

        privacy = self.client.get(f"/api/v1/jobs/{job_id}/privacy-analysis").json()
        self.assertEqual(privacy["privacy_risk"]["total_profiles"], 1)

        files_list = self.client.get(f"/api/v1/jobs/{job_id}/files").json()
        self.assertEqual(len(files_list["files"]), 3)

        report = self.client.get(f"/api/v1/jobs/{job_id}/report").json()
        self.assertEqual(report["schema"], "raksha-report/1")

        # 6. Download zip archive and verify no PII leaked in sanitized TXT
        dl = self.client.get(f"/api/v1/jobs/{job_id}/download")
        self.assertEqual(dl.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
            names = zf.namelist()
            self.assertIn("report.json", names)
            self.assertIn("records.jsonl", names)
            txt_entries = [n for n in names if n.startswith("sanitized/") and n.endswith(".txt")]
            self.assertEqual(len(txt_entries), 1)
            san_txt = zf.read(txt_entries[0]).decode("utf-8")
            self.assertNotIn("Meera Shah", san_txt)
            self.assertIn("Tab Ramipril 5 mg", san_txt)

    def test_path_traversal_and_missing_job_errors(self) -> None:
        self.assertEqual(self.client.get("/api/v1/jobs/doesnotexist").status_code, 404)
        job_id = self.client.post("/api/v1/jobs", json={"secret": "s"}).json()["job_id"]
        bad = self.client.post(
            f"/api/v1/jobs/{job_id}/files",
            files=[("files", ("../../evil.txt", b"Meera Shah", "text/plain"))],
        )
        self.assertEqual(bad.status_code, 400)
        self.assertNotIn("Meera Shah", bad.text)


if __name__ == "__main__":
    unittest.main()
