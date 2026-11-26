"""WardProof CLI: offline, deterministic, multilingual healthcare privacy firewall."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from typing import Callable

try:
    import resource
except ImportError:  # Windows fallback
    resource = None  # type: ignore[assignment]

from clinical.risk import analyze_equivalence_classes
from formats.handlers import ParsedDocument, extract_document, sanitize_document
from identity.linkage import IdentityEvidence, PatientLinkageIndex

COUNT_KEYS = (
    "files_total",
    "files_sanitized",
    "files_quarantined",
    "records_processed",
    "identifiers_detected",
    "records_linked",
    "records_generalized",
    "records_suppressed",
    "records_quarantined",
)


def _token(secret: bytes, *parts: str) -> str:
    return hmac.new(secret, "\0".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _safe_output_path(source: str, doc: ParsedDocument, secret: bytes) -> str:
    if doc.kind == "clean":
        return "sanitized/clean/" + Path(source).name
    parts = Path(source).parts
    folder = parts[0] if len(parts) > 1 else "root"
    ext = Path(source).suffix.lower() or ".txt"
    if ext == ".tsv":
        ext = ".tsv"
    return f"sanitized/{folder}/{_token(secret, 'path', source)}{ext}"


def _peak_rss_mb() -> float:
    if resource is None:
        return 0.0
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 3)


def run(
    inp: Path,
    out: Path,
    secret: bytes,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    start = time.monotonic()
    inp, out = inp.resolve(), out.resolve()
    if not inp.is_dir() or inp.is_relative_to(out) or out.is_relative_to(inp):
        raise ValueError("Invalid input/output directory relationship")
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("Output directory must be empty")
    (out / "sanitized").mkdir()

    counts: dict[str, int] = dict.fromkeys(COUNT_KEYS, 0)
    entity_totals: Counter[str] = Counter()
    linkage = PatientLinkageIndex(secret=secret)

    # Pass 1: Validate, parse, and collect linkage evidence (or quarantine).
    parsed_items: list[tuple[str, str, ParsedDocument | None, str | None]] = []
    input_files = [p for p in sorted(inp.rglob("*")) if p.is_file() or p.is_symlink()]
    for path in input_files:
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in input")
        source = path.relative_to(inp).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        try:
            doc = extract_document(source, raw)
        except (ValueError, UnicodeDecodeError) as exc:
            parsed_items.append((source, digest, None, str(exc) or "unsupported_format"))
        else:
            for ev in doc.evidences:
                linkage.add(ev)
            parsed_items.append((source, digest, doc, None))

    linkage.build()

    # Pass 2: Sanitize parsed documents and write report + linkage index.
    files_report: list[dict[str, object]] = []
    risk_profiles: list[tuple[str | None, IdentityEvidence, str]] = []
    total_files = len(parsed_items)
    with (out / "records.jsonl").open("x", encoding="utf-8") as links_file:
        for idx, (source, digest, doc, err_reason) in enumerate(parsed_items, 1):
            counts["files_total"] += 1
            if doc is None:
                counts["files_quarantined"] += 1
                counts["records_quarantined"] += 1
                files_report.append(
                    {
                        "input_sha256": digest,
                        "output": None,
                        "status": "quarantined",
                        "reason": err_reason or "unsupported_format",
                    }
                )
            else:
                out_rel = _safe_output_path(source, doc, secret)
                text_out, doc_links, doc_counts = sanitize_document(doc, linkage)
                dest = out / out_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(text_out.encode("utf-8"))

                for loc, psn in doc_links:
                    links_file.write(json.dumps({"file": out_rel, "loc": loc, "patient": psn}) + "\n")
                for ev in doc.evidences:
                    risk_profiles.append((linkage.pseudonym(ev.record_id), ev, ""))

                counts["files_sanitized"] += 1
                for k in ("identifiers_detected", "records_processed", "records_linked", "records_generalized"):
                    counts[k] += int(doc_counts.get(k, 0))
                entity_totals.update(doc_counts.get("entities") or {})

                files_report.append(
                    {
                        "input_sha256": digest,
                        "output": out_rel,
                        "status": "sanitized",
                    }
                )
            if progress_callback is not None:
                progress_callback(idx, total_files)

    risk_report = analyze_equivalence_classes(risk_profiles)
    report: dict[str, object] = {
        "schema": "raksha-report/1",
        "files": files_report,
        "counts": counts,
        "entities": dict(entity_totals),
        "privacy_risk": risk_report.to_dict(),
        "timing": {"seconds": round(time.monotonic() - start, 4)},
        "resources": {"peak_rss_mb": _peak_rss_mb()},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="WardProof offline healthcare privacy firewall")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    secret = os.environ.get("RAKSHA_SECRET", "")
    if not secret:
        parser.exit(2, "Missing release secret.\n")
    try:
        run(args.input, args.output, secret.encode("utf-8"))
    except (OSError, ValueError):
        parser.exit(1, "Release failed; discard any partial output.\n")


if __name__ == "__main__":
    main()
