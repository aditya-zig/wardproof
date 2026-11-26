"""Thread-safe background job manager for WardProof API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import uuid
import zipfile

from main import run as run_firewall


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_relpath(raw_name: str) -> Path:
    """Validate uploaded relative path against traversal attacks."""
    cleaned = raw_name.replace("\\", "/").lstrip("/")
    rel = Path(cleaned)
    if not cleaned or rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Invalid relative file path")
    return rel


@dataclass
class JobState:
    """In-memory state for a single privacy-processing job (no raw PII stored)."""

    job_id: str
    workspace: Path
    input_dir: Path
    output_dir: Path
    secret: bytes
    status: str = "created"  # created | processing | completed | failed
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    files_registered: int = 0
    files_done: int = 0
    files_total: int = 0
    error: str | None = None
    custom_input_dir: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def progress_pct(self) -> float:
        if self.status == "completed":
            return 100.0
        if self.files_total <= 0:
            return 0.0
        return round(100.0 * self.files_done / self.files_total, 2)

    def to_status_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "files_registered": self.files_registered,
            "files_done": self.files_done,
            "files_total": self.files_total,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }


class JobManager:
    """Manages job lifecycles, isolated temp workspaces, and background execution."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path(tempfile.mkdtemp(prefix="wardproof_jobs_"))
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create_job(self, secret: str) -> JobState:
        if not secret or not secret.strip():
            raise ValueError("secret must be non-empty")
        job_id = uuid.uuid4().hex[:16]
        ws = self._base_dir / job_id
        inp = ws / "input"
        out = ws / "output"
        inp.mkdir(parents=True, exist_ok=True)
        job = JobState(
            job_id=job_id,
            workspace=ws,
            input_dir=inp,
            output_dir=out,
            secret=secret.encode("utf-8"),
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def add_uploaded_file(self, job: JobState, filename: str, content: bytes) -> None:
        if job.status in {"processing", "completed"}:
            raise ValueError("Cannot add files after processing has started")
        rel = _safe_relpath(filename)
        dest = (job.input_dir / rel).resolve()
        if not dest.is_relative_to(job.input_dir.resolve()):
            raise ValueError("Invalid file destination")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        with job._lock:
            job.files_registered += 1
            job.updated_at = _utc_now()

    def register_input_dir(self, job: JobState, directory: Path) -> int:
        if job.status in {"processing", "completed"}:
            raise ValueError("Cannot register input after processing has started")
        resolved = directory.resolve()
        if not resolved.is_dir():
            raise ValueError("Input directory does not exist")
        count = sum(1 for p in resolved.rglob("*") if p.is_file())
        with job._lock:
            job.custom_input_dir = resolved
            job.files_registered = count
            job.updated_at = _utc_now()
        return count

    def start_processing(self, job: JobState) -> None:
        with job._lock:
            if job.status == "processing":
                raise ValueError("Job is already processing")
            if job.status == "completed":
                raise ValueError("Job is already completed")
            src = job.custom_input_dir or job.input_dir
            if not any(p.is_file() for p in src.rglob("*")):
                raise ValueError("No input files registered for job")
            if job.output_dir.exists():
                shutil.rmtree(job.output_dir)
            job.status = "processing"
            job.files_done = 0
            job.files_total = job.files_registered
            job.error = None
            job.updated_at = _utc_now()

        def _worker() -> None:
            def _on_progress(done: int, total: int) -> None:
                with job._lock:
                    job.files_done = done
                    job.files_total = total
                    job.updated_at = _utc_now()

            try:
                run_firewall(src, job.output_dir, job.secret, progress_callback=_on_progress)
                with job._lock:
                    job.status = "completed"
                    job.files_done = job.files_total
                    job.updated_at = _utc_now()
            except Exception:
                with job._lock:
                    job.status = "failed"
                    job.error = "Processing failed; check input validity"
                    job.updated_at = _utc_now()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def read_report(self, job: JobState) -> dict:
        report_path = job.output_dir / "report.json"
        if not report_path.is_file():
            raise FileNotFoundError("Report not available")
        return json.loads(report_path.read_text(encoding="utf-8"))

    def read_links(self, job: JobState) -> list[dict]:
        links_path = job.output_dir / "records.jsonl"
        if not links_path.is_file():
            return []
        return [
            json.loads(line)
            for line in links_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def build_zip_bytes(self, job: JobState) -> bytes:
        if job.status != "completed" or not job.output_dir.is_dir():
            raise FileNotFoundError("Sanitized output not available")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(job.output_dir.rglob("*")):
                if p.is_file():
                    zf.write(p, arcname=p.relative_to(job.output_dir).as_posix())
        return buf.getvalue()
