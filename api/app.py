"""FastAPI application for the WardProof Secret Wards Privacy Firewall."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.jobs import JobManager, JobState


class CreateJobRequest(BaseModel):
    secret: str = Field(..., min_length=1, description="Per-release HMAC secret (never written to output).")


class RegisterDirectoryRequest(BaseModel):
    input_dir: str = Field(..., min_length=1, description="Local directory path containing input records.")


def _require_job(manager: JobManager, job_id: str) -> JobState:
    job = manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _require_completed(job: JobState) -> None:
    if job.status == "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=job.error or "Job failed")
    if job.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Job is {job.status}, not completed")


def create_app(job_manager: JobManager | None = None) -> FastAPI:
    """Create a configured FastAPI instance with CORS and background job routes."""
    manager = job_manager or JobManager()

    app = FastAPI(
        title="WardProof Secret Wards Privacy Firewall API",
        version="1.0.0",
        description="Offline, CPU-only, LLM-free healthcare de-identification and linkage API.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "service": "wardproof-backend", "offline": True}

    @app.post("/api/v1/jobs", status_code=status.HTTP_201_CREATED)
    def create_job(req: CreateJobRequest) -> dict[str, object]:
        try:
            job = manager.create_job(secret=req.secret)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return job.to_status_dict()

    @app.post("/api/v1/jobs/{job_id}/files")
    async def upload_or_register_files(
        job_id: str,
        files: Annotated[list[UploadFile] | None, File()] = None,
        input_dir: str | None = None,
    ) -> dict[str, object]:
        job = _require_job(manager, job_id)
        if input_dir:
            try:
                count = manager.register_input_dir(job, Path(input_dir))
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            return {"job_id": job.job_id, "files_registered": count, "mode": "directory"}

        if not files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide multipart files or input_dir")

        uploaded = 0
        for uf in files:
            content = await uf.read()
            try:
                manager.add_uploaded_file(job, uf.filename or f"file_{uploaded}", content)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            uploaded += 1
        return {"job_id": job.job_id, "files_uploaded": uploaded, "files_registered": job.files_registered}

    @app.post("/api/v1/jobs/{job_id}/process", status_code=status.HTTP_202_ACCEPTED)
    def process_job(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        try:
            manager.start_processing(job)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return job.to_status_dict()

    @app.get("/api/v1/jobs/{job_id}")
    def get_job_status(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        return job.to_status_dict()

    @app.get("/api/v1/jobs/{job_id}/summary")
    def get_job_summary(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        _require_completed(job)
        report = manager.read_report(job)
        return {
            "job_id": job.job_id,
            "counts": report.get("counts", {}),
            "timing": report.get("timing", {}),
            "resources": report.get("resources", {}),
        }

    @app.get("/api/v1/jobs/{job_id}/detections")
    def get_job_detections(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        _require_completed(job)
        report = manager.read_report(job)
        entities = report.get("entities", {})
        return {
            "job_id": job.job_id,
            "total_detections": report.get("counts", {}).get("identifiers_detected", 0),
            "entities": entities,
        }

    @app.get("/api/v1/jobs/{job_id}/identities")
    def get_job_identities(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        _require_completed(job)
        links = manager.read_links(job)
        unique_psns = sorted({r["patient"] for r in links if r.get("patient")})
        abstained = sum(1 for r in links if r.get("patient") is None)
        return {
            "job_id": job.job_id,
            "total_records": len(links),
            "linked_records": len(links) - abstained,
            "abstained_records": abstained,
            "unique_pseudonyms": len(unique_psns),
            "links": links,
        }

    @app.get("/api/v1/jobs/{job_id}/privacy-analysis")
    def get_privacy_analysis(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        _require_completed(job)
        report = manager.read_report(job)
        return {
            "job_id": job.job_id,
            "privacy_risk": report.get("privacy_risk", {}),
        }

    @app.get("/api/v1/jobs/{job_id}/files")
    def list_job_files(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        _require_completed(job)
        report = manager.read_report(job)
        return {
            "job_id": job.job_id,
            "files": report.get("files", []),
        }

    @app.get("/api/v1/jobs/{job_id}/report")
    def get_job_report(job_id: str) -> dict[str, object]:
        job = _require_job(manager, job_id)
        _require_completed(job)
        return manager.read_report(job)

    @app.get("/api/v1/jobs/{job_id}/download")
    def download_sanitized_zip(job_id: str) -> StreamingResponse:
        job = _require_job(manager, job_id)
        _require_completed(job)
        zip_bytes = manager.build_zip_bytes(job)
        headers = {"Content-Disposition": f'attachment; filename="wardproof_{job.job_id}.zip"'}
        return StreamingResponse(io.BytesIO(zip_bytes), media_type="application/zip", headers=headers)

    return app


app = create_app()
