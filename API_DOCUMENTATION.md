# WardProof Backend API Documentation (v1)

Local FastAPI service for the **Secret Wards Privacy Firewall**. Runs completely offline on CPU with background job execution and CORS enabled for local frontend development (`localhost:3000`, `localhost:5173`, `localhost:8000`).

**Start the API server locally:**
```sh
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

> **Note:** The official competition CLI (`python main.py --input {input} --output {output}`) uses standard-library Python only and runs completely independently of this API.

---

## Standard Error Format & Privacy Guarantees

- Never sends or logs raw PII in API responses, job status, or error messages.
- Consistent HTTP status codes: `200 OK`, `201 Created`, `202 Accepted`, `400 Bad Request`, `404 Not Found`, `409 Conflict`.
- Error payload:
```json
{
  "detail": "Job not found"
}
```

---

## Endpoints

### 1. Health Check
- **GET** `/api/v1/health`
- **Response (`200 OK`)**:
```json
{
  "status": "ok",
  "service": "wardproof-backend",
  "offline": true
}
```

### 2. Create Processing Job
- **POST** `/api/v1/jobs`
- **Request Body**:
```json
{
  "secret": "practice-release-secret"
}
```
- **Response (`201 Created`)**:
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "status": "created",
  "progress_pct": 0.0,
  "files_registered": 0,
  "files_done": 0,
  "files_total": 0,
  "created_at": "2026-11-26T14:50:00+00:00",
  "updated_at": "2026-11-26T14:50:00+00:00",
  "error": null
}
```

### 3. Upload or Register Input Files
- **POST** `/api/v1/jobs/{job_id}/files`
- **Option A (Multipart Upload)**: Send `files` form-data fields (relative paths preserved; `..` traversal rejected).
- **Option B (Local Directory)**: Query param `?input_dir=/path/to/input`.
- **Response (`200 OK`)**:
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "files_uploaded": 4,
  "files_registered": 4
}
```

### 4. Start Background Processing
- **POST** `/api/v1/jobs/{job_id}/process`
- Non-blocking; executes the two-pass privacy firewall in a background thread.
- **Response (`202 Accepted`)**:
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "status": "processing",
  "progress_pct": 0.0,
  "files_registered": 4,
  "files_done": 0,
  "files_total": 4,
  "created_at": "2026-11-26T14:50:00+00:00",
  "updated_at": "2026-11-26T14:50:01+00:00",
  "error": null
}
```

### 5. Poll Job Status & Progress
- **GET** `/api/v1/jobs/{job_id}`
- **Response (`200 OK`)**: Same schema as above (`status`: `created` | `processing` | `completed` | `failed`, `progress_pct`: `0.0..100.0`).

### 6. Processing Summary
- **GET** `/api/v1/jobs/{job_id}/summary` *(requires `completed`)*
- **Response (`200 OK`)**:
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "counts": {
    "files_total": 200,
    "files_sanitized": 194,
    "files_quarantined": 6,
    "records_processed": 645,
    "identifiers_detected": 3694,
    "records_linked": 612,
    "records_generalized": 573,
    "records_suppressed": 0,
    "records_quarantined": 6
  },
  "timing": { "seconds": 0.94 },
  "resources": { "peak_rss_mb": 42.5 }
}
```

### 7. PII Detection Breakdown
- **GET** `/api/v1/jobs/{job_id}/detections` *(requires `completed`)*
- **Response (`200 OK`)**: Aggregate counts only (never raw matched strings).
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "total_detections": 3694,
  "entities": {
    "PATIENT_NAME": 810,
    "PHONE": 307,
    "MRN": 844
  }
}
```

### 8. Pseudonymous Identity-Linkage Results
- **GET** `/api/v1/jobs/{job_id}/identities` *(requires `completed`)*
- **Response (`200 OK`)**:
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "total_records": 645,
  "linked_records": 612,
  "abstained_records": 33,
  "unique_pseudonyms": 48,
  "links": [
    {
      "file": "sanitized/discharge/1e3bc2db958070365bf3050b.txt",
      "loc": "doc",
      "patient": "PSN-7q2k9d10ab34ef12"
    }
  ]
}
```

### 9. Privacy & k-Anonymity Risk Analysis
- **GET** `/api/v1/jobs/{job_id}/privacy-analysis` *(requires `completed`)*
- **Response (`200 OK`)**:
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "privacy_risk": {
    "total_profiles": 48,
    "equivalence_classes": 21,
    "k_min": 1,
    "k1_unique_profiles": 6,
    "k2_small_profiles": 10,
    "residual_k1_ratio": 0.125
  }
}
```

### 10. Processed File List
- **GET** `/api/v1/jobs/{job_id}/files` *(requires `completed`)*
- **Response (`200 OK`)**:
```json
{
  "job_id": "a1b2c3d4e5f60718",
  "files": [
    {
      "input_sha256": "9f2c...",
      "output": "sanitized/discharge/1e3bc2db958070365bf3050b.txt",
      "status": "sanitized"
    },
    {
      "input_sha256": "51aa...",
      "output": null,
      "status": "quarantined",
      "reason": "unsupported_format"
    }
  ]
}
```

### 11. Full Official Report (`report.json`)
- **GET** `/api/v1/jobs/{job_id}/report` *(requires `completed`)*
- Returns the exact `raksha-report/1` JSON written by the pipeline.

### 12. Download Sanitized Output Archive
- **GET** `/api/v1/jobs/{job_id}/download` *(requires `completed`)*
- **Response (`200 OK`, `application/zip`)**: Streams `wardproof_{job_id}.zip` containing `sanitized/`, `report.json`, and `records.jsonl`.
