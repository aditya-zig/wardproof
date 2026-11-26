"""Format-specific parsers, evidence extractors, and sanitizers.

Standard-library Python only. Fails closed (quarantines) on malformed,
binary, or excessively nested inputs.
"""

from __future__ import annotations

import base64
import csv
from dataclasses import dataclass, field
import io
import json
import re
from typing import Any

from clinical.text import sanitize_text
from identity.linkage import (
    IdentityEvidence,
    PatientLinkageIndex,
    generalize_age,
    generalize_pin,
    normalize_name,
    normalize_phone,
    shift_date_string,
)

MAX_FILE_BYTES = 8_000_000
MAX_JSON_DEPTH = 64
SUPPORTED_EXTS = {".csv", ".tsv", ".json", ".txt"}

_B64_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_UHID_RE = re.compile(r"\b(?:SNJ|JJH|ADM|IPD|UHID|DHH-IPD|MRN)[/-]?(?:[A-Z0-9]{1,8}[/-])?\d{3,12}\b")
_ABHA_RE = re.compile(r"\b\d{2}-\d{4}-\d{4}-\d{4}\b")
_AADHAAR_RE = re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_DATE_TOKEN_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?)?|\d{2}[/-]\d{2}[/-]\d{4})\b")

_PII_KEYS = frozenset(
    {
        "patient_name", "name", "full_name", "naam", "firstname", "first_name", "lastname", "last_name",
        "first", "last", "local", "line", "data",
        "relative_name", "father_name", "mother_name", "husband_name", "guardian", "attendant",
        "pita_pati_ka_naam", "s_o", "d_o", "w_o", "relation",
        "phone", "mobile", "mobile_no", "mob", "tel", "contact", "email",
        "aadhaar", "aadhaar_no", "aadhar", "aadhar_no", "abha", "abha_no", "abha_number", "abha_address",
        "pan", "payer_pan", "pmjay_id", "policy_no", "insurance_id", "bill_no",
        "sample_id", "visit_id", "ipd_no", "reg_no", "patientid",
        "house", "h_no", "mohalla", "gali", "landmark", "village", "village_mohalla", "gaon",
        "gram", "address", "pata", "street", "city", "tehsil",
        "dob", "dob_mm_dd_yyyy", "date_of_birth", "birthdate", "janm_tithi",
        "source_path", "exported_by",
    }
)
_ID_REF_KEYS = frozenset({"uhid", "patient_ref", "hospital_uhid", "mrn", "patient_id", "patientid", "reg_no"})
_DATE_KEYS = frozenset(
    {
        "visit_date", "admission_date", "discharge_date", "collected_on", "reported_on",
        "collected", "date", "onsetdatetime", "authoredon", "effectivedatetime",
        "recordeddate", "generated_at", "lastupdated", "timestamp",
        "reg_date", "registration_date", "registered_mm_dd_yyyy", "registered_on", "exported_at",
    }
)
_AGE_KEYS = frozenset({"age", "umar"})
_SEX_KEYS = frozenset({"gender", "sex", "ling"})
_PIN_KEYS = frozenset({"pin", "pin_code", "pincode", "postalcode", "postal_code", "zip"})
_CLINICAL_TEXT_KEYS = frozenset(
    {"complaints", "history", "notes", "clinical_notes", "chief_complaint", "summary", "text", "div"}
)


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


@dataclass
class ParsedDocument:
    """In-memory representation of a validated input file."""

    source: str
    kind: str  # "csv" | "tsv" | "opd_json" | "lab_json" | "generic_json" | "text"
    encoding: str
    payload: Any
    evidences: list[IdentityEvidence] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def _json_depth(obj: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        return depth
    if isinstance(obj, dict):
        if not obj:
            return depth + 1
        return max(_json_depth(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return depth + 1
        return max(_json_depth(v, depth + 1) for v in obj)
    return depth


def _decode_text(raw: bytes) -> tuple[str, str]:
    if not raw:
        raise ValueError("empty_file")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if b"\x00" in raw:
        raise ValueError("binary_or_null_bytes")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("unsupported_encoding")


def _strip_b64_runs(text: str) -> tuple[str, int]:
    """Remove suspicious base64 payloads so hidden PII cannot survive."""
    count = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal count
        tok = m.group(0)
        try:
            decoded = base64.b64decode(tok + "=" * (-len(tok) % 4)).decode("utf-8", errors="ignore")
        except Exception:
            return tok
        if any(c.isalpha() for c in decoded):
            count += 1
            return "[REDACTED_ATTACHMENT]"
        return tok

    return _B64_RE.sub(_repl, text), count


def _flatten_dict(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            flat.update(_flatten_dict(v, f"{prefix}{k}_"))
        else:
            flat[k] = v
    return flat


def _extract_row_evidence(record_id: str, row: dict[str, Any]) -> IdentityEvidence:
    ev = IdentityEvidence(record_id=record_id)
    flat = _flatten_dict(row)
    first_name = ""
    last_name = ""
    for k, v in flat.items():
        if v is None:
            continue
        val = str(v).strip()
        if not val:
            continue
        kl = _norm_key(k)
        if kl in _ID_REF_KEYS:
            ev.uhids.add(val)
        elif kl in {"phone", "mobile", "mobile_no", "mob", "tel", "contact"}:
            p = normalize_phone(val)
            if p:
                ev.phones.add(p)
        elif kl in {"aadhaar", "aadhaar_no", "aadhar", "aadhar_no"}:
            digits = re.sub(r"\D", "", val)
            if len(digits) == 12:
                ev.aadhaars.add(digits)
        elif kl in {"abha", "abha_no", "abha_number"}:
            digits = re.sub(r"\D", "", val)
            if len(digits) == 14:
                ev.abhas.add(digits)
        elif kl in {"pan", "payer_pan"} and _PAN_RE.fullmatch(val):
            ev.pans.add(val)
        elif kl in {"patient_name", "name", "full_name", "naam"} and not ev.name_norm:
            ev.name_norm = normalize_name(val)
            ev.raw_names.add(val)
        elif kl in {"firstname", "first_name", "first"}:
            first_name = val
        elif kl in {"lastname", "last_name", "last"}:
            last_name = val
        elif kl in {"relative_name", "s_o", "d_o", "w_o", "father_name", "husband_name", "pita_pati_ka_naam", "guardian"} and not ev.relative_norm:
            ev.relative_norm = normalize_name(val)
            ev.raw_names.add(val)
        elif kl in _SEX_KEYS and not ev.sex:
            ev.sex = val[0].upper() if val[0].upper() in {"M", "F", "O"} else ""
        elif kl in _AGE_KEYS and ev.age is None:
            m = re.search(r"\d{1,3}", val)
            if m:
                ev.age = int(m.group(0))
        elif kl == "age_sex":
            m = re.match(r"\s*(\d{1,3})\s*(?:Yrs?)?\s*/\s*([MFO])", val, re.I)
            if m:
                ev.age = int(m.group(1))
                ev.sex = m.group(2).upper()
        elif kl in {"dob", "dob_mm_dd_yyyy", "date_of_birth", "janm_tithi"} and not ev.dob:
            ev.dob = val
    if not ev.name_norm and (first_name or last_name):
        full = f"{first_name} {last_name}".strip()
        ev.name_norm = normalize_name(full)
        ev.raw_names.add(full)
    return ev


def _extract_text_evidence(record_id: str, text: str) -> tuple[IdentityEvidence, dict[str, Any]]:
    ev = IdentityEvidence(record_id=record_id)
    patient_names: list[str] = []
    relative_names: list[str] = []
    clinicians: list[str] = []

    for m in _UHID_RE.finditer(text):
        ev.uhids.add(m.group(0))
    for m in _ABHA_RE.finditer(text):
        ev.abhas.add(re.sub(r"\D", "", m.group(0)))
    for m in _AADHAAR_RE.finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) == 12:
            ev.aadhaars.add(d)
    for m in _PHONE_RE.finditer(text):
        p = normalize_phone(m.group(0))
        if p:
            ev.phones.add(p)

    m_name = re.search(
        r"(?:Patient\s*Name|Name|नाम)\s*[:\-]\s*([^\n\r,;]+?)(?=\s+(?:Age|आयु|Reg|UHID|Mob|$)|\n|$)",
        text,
        re.I,
    )
    if m_name:
        raw_name = m_name.group(1).strip()
        patient_names.append(raw_name)
        first = raw_name.split()[0]
        if len(first) >= 4:
            patient_names.append(first)
        ev.name_norm = normalize_name(raw_name)

    m_rel = re.search(r"\b(?:S/o|D/o|W/o)\s+([A-Z][a-zA-Z.'-]*(?:\s+[A-Z][a-zA-Z.'-]*){0,2})", text)
    if m_rel:
        rel_name = m_rel.group(1).strip()
        relative_names.append(rel_name)
        ev.relative_norm = normalize_name(rel_name)

    m_age_sex = re.search(r"Age(?:/Sex)?\s*[:\-]\s*(\d{1,3})\s*(?:Yrs?)?\s*/\s*([MFO])", text, re.I)
    if m_age_sex:
        ev.age = int(m_age_sex.group(1))
        ev.sex = m_age_sex.group(2).upper()
    else:
        m_age_hi = re.search(r"आयु\s*[:\-]\s*(\d{1,3})", text)
        if m_age_hi:
            ev.age = int(m_age_hi.group(1))

    # Verified clinicians in the same doc (e.g. Consultant: Dr. X (MS Surgery))
    for m_doc in re.finditer(
        r"(?:Consultant|Consulting\s+Physician|Attending\s+Physician|Ref\.?\s*Doctor|Signed\s+by)\s*[:\-]\s*(Dr\.?\s+[A-Z][a-zA-Z.'-]*(?:\s+[A-Z][a-zA-Z.'-]*){0,3})|(Dr\.?\s+[A-Z][a-zA-Z.'-]*(?:\s+[A-Z][a-zA-Z.'-]*){0,3})\s*(?:\([^)]*(?:MD|MS|MBBS|Medicine|Surgery)[^)]*\)|,\s*(?:MBBS|MD|MS))",
        text,
        re.I,
    ):
        doc = (m_doc.group(1) or m_doc.group(2) or "").strip()
        if doc:
            clinicians.append(doc)

    return ev, {
        "patient_names": patient_names,
        "relative_names": relative_names,
        "clinician_names": clinicians,
    }


def extract_document(source: str, raw: bytes) -> ParsedDocument:
    """Validate, parse, and extract linkage evidence from a single input file."""
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    ext = "." + source.rsplit(".", 1)[-1].lower() if "." in source else ""
    if ext not in SUPPORTED_EXTS:
        raise ValueError("unsupported_format")

    text, enc = _decode_text(raw)
    if not text.strip():
        raise ValueError("empty_file")

    if ext in {".csv", ".tsv"}:
        delim = "\t" if ext == ".tsv" else ","
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim, strict=True)
        header = next(reader, None)
        if not header or len(header) < 2:
            raise ValueError("malformed_table")
        rows: list[dict[str, str]] = []
        evidences: list[IdentityEvidence] = []
        for idx, cells in enumerate(reader):
            if len(cells) != len(header):
                raise ValueError("ragged_table_row")
            row = dict(zip(header, cells))
            rows.append(row)
            evidences.append(_extract_row_evidence(f"{source}#row:{idx}", row))
        return ParsedDocument(
            source=source,
            kind="tsv" if ext == ".tsv" else "csv",
            encoding=enc,
            payload=(header, rows),
            evidences=evidences,
        )

    if ext == ".json":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("malformed_json") from exc
        if _json_depth(obj) > MAX_JSON_DEPTH:
            raise ValueError("excessive_json_depth")

        # FHIR needs its own release allowlist; generic JSON is not a safe fallback.
        if isinstance(obj, dict) and "resourceType" in obj:
            raise ValueError("unsupported_fhir_release")

        if isinstance(obj, dict) and isinstance(obj.get("patients"), list):
            evidences = []
            for idx, p in enumerate(obj["patients"]):
                if isinstance(p, dict):
                    evidences.append(_extract_row_evidence(f"{source}#/patients/{idx}", p))
            return ParsedDocument(source=source, kind="patients_json", encoding=enc, payload=obj, evidences=evidences)

        if isinstance(obj, dict) and isinstance(obj.get("visits"), list):
            evidences = []
            for idx, v in enumerate(obj["visits"]):
                if isinstance(v, dict):
                    evidences.append(_extract_row_evidence(f"{source}#/visits/{idx}", v))
            return ParsedDocument(source=source, kind="opd_json", encoding=enc, payload=obj, evidences=evidences)

        if isinstance(obj, dict) and isinstance(obj.get("panels"), list) and isinstance(obj.get("patient"), dict):
            ev = _extract_row_evidence(f"{source}#doc", obj["patient"])
            return ParsedDocument(source=source, kind="lab_json", encoding=enc, payload=obj, evidences=[ev])

        if isinstance(obj, list):
            evidences = [
                _extract_row_evidence(f"{source}#/{idx}", item)
                for idx, item in enumerate(obj)
                if isinstance(item, dict)
            ]
            return ParsedDocument(source=source, kind="generic_json", encoding=enc, payload=obj, evidences=evidences)

        if isinstance(obj, dict):
            ev = _extract_row_evidence(f"{source}#doc", obj)
            return ParsedDocument(source=source, kind="generic_json", encoding=enc, payload=obj, evidences=[ev])

        raise ValueError("unsupported_json_root")

    # Plain text (.txt)
    ev, ctx_extra = _extract_text_evidence(f"{source}#doc", text)
    return ParsedDocument(
        source=source,
        kind="text",
        encoding=enc,
        payload=text,
        evidences=[ev],
        extra=ctx_extra,
    )


def _sanitize_key_name(key: str, counts: dict[str, int]) -> str:
    if _UHID_RE.search(key) or _PHONE_RE.search(key) or _PAN_RE.search(key):
        counts["identifiers_detected"] += 1
        return "[REDACTED_KEY]"
    if " " in key or "_" in key:
        res = sanitize_text(key.replace("_", " "), field="key")
        if sum(res.counts.values()) > 0:
            counts["identifiers_detected"] += sum(res.counts.values())
            return "[REDACTED_KEY]"
    return key


def _sanitize_json_value(
    key: str,
    val: Any,
    pseudonym: str | None,
    offset: int,
    counts: dict[str, int],
) -> Any:
    if isinstance(val, dict):
        return {
            _sanitize_key_name(str(k), counts): _sanitize_json_value(str(k), v, pseudonym, offset, counts)
            for k, v in val.items()
        }
    if isinstance(val, list):
        return [_sanitize_json_value(key, item, pseudonym, offset, counts) for item in val]
    if isinstance(val, str):
        val, b64_n = _strip_b64_runs(val)
        if b64_n:
            counts["identifiers_detected"] += b64_n
        kl = _norm_key(key)
        if kl in _ID_REF_KEYS:
            counts["identifiers_detected"] += 1
            return pseudonym or "[REDACTED_ID]"
        if kl in _PII_KEYS:
            counts["identifiers_detected"] += 1
            return "[REDACTED]"
        if kl in _PIN_KEYS:
            counts["records_generalized"] += 1
            return generalize_pin(val) or "[REDACTED_PIN]"
        if kl in _DATE_KEYS:
            return shift_date_string(val, offset)
        if kl in _CLINICAL_TEXT_KEYS:
            res = sanitize_text(val, field=key)
            counts["identifiers_detected"] += sum(res.counts.values())
            return res.text
        if len(val) > 25 and " " in val:
            res = sanitize_text(val, field=key)
            counts["identifiers_detected"] += sum(res.counts.values())
            return res.text
        return val
    if isinstance(val, (int, float)):
        kl = _norm_key(key)
        if kl in _AGE_KEYS:
            counts["records_generalized"] += 1
            return generalize_age(val)
        if kl in _PII_KEYS:
            counts["identifiers_detected"] += 1
            return "[REDACTED]"
        if kl in _PIN_KEYS:
            counts["records_generalized"] += 1
            return generalize_pin(str(int(val))) or "[REDACTED_PIN]"
    return val


def sanitize_document(
    doc: ParsedDocument,
    linkage: PatientLinkageIndex,
) -> tuple[str, list[tuple[str, str | None]], dict[str, Any]]:
    """Sanitize a ParsedDocument using cross-file linkage, returning (utf8_text, links, counts)."""
    entity_counts: dict[str, int] = {}
    counts: dict[str, Any] = {
        "identifiers_detected": 0,
        "records_processed": 0,
        "records_linked": 0,
        "records_generalized": 0,
        "entities": entity_counts,
    }
    links: list[tuple[str, str | None]] = []

    if doc.kind in {"csv", "tsv"}:
        header, rows = doc.payload
        delim = "\t" if doc.kind == "tsv" else ","
        out = io.StringIO(newline="")
        clean_header = [_sanitize_key_name(h, counts) for h in header]
        writer = csv.DictWriter(out, fieldnames=clean_header, delimiter=delim)
        writer.writeheader()
        for idx, row in enumerate(rows):
            rec_id = f"{doc.source}#row:{idx}"
            psn = linkage.pseudonym(rec_id)
            offset = linkage.date_offset(rec_id)
            clean_row: dict[str, str] = {}
            for orig_k, k in zip(header, clean_header):
                v = row.get(orig_k)
                kl = _norm_key(orig_k)
                val = (v or "").strip()
                if not val:
                    clean_row[k] = ""
                elif kl in _ID_REF_KEYS:
                    clean_row[k] = psn or "[REDACTED_ID]"
                    counts["identifiers_detected"] += 1
                    entity_counts["MRN"] = entity_counts.get("MRN", 0) + 1
                elif kl in _PII_KEYS:
                    clean_row[k] = "[REDACTED]"
                    counts["identifiers_detected"] += 1
                    entity_counts["PII_FIELD"] = entity_counts.get("PII_FIELD", 0) + 1
                elif kl in _AGE_KEYS:
                    clean_row[k] = generalize_age(val)
                    counts["records_generalized"] += 1
                elif kl == "age_sex":
                    m = re.match(r"\s*(\d{1,3})\s*(?:Yrs?)?\s*/\s*([MFO])", val, re.I)
                    if m:
                        clean_row[k] = f"{generalize_age(m.group(1))}/{m.group(2).upper()}"
                        counts["records_generalized"] += 1
                    else:
                        clean_row[k] = "[REDACTED]"
                elif kl in _PIN_KEYS:
                    clean_row[k] = generalize_pin(val)
                    counts["records_generalized"] += 1
                elif kl in _DATE_KEYS:
                    clean_row[k] = shift_date_string(val, offset)
                elif kl == "ref_doctor":
                    clean_row[k] = val if re.match(r"^Dr\.?\s+", val, re.I) else "[REDACTED]"
                else:
                    res = sanitize_text(val, field=orig_k)
                    counts["identifiers_detected"] += sum(res.counts.values())
                    for ek, ev_n in res.counts.items():
                        entity_counts[ek] = entity_counts.get(ek, 0) + ev_n
                    clean_row[k] = res.text
            writer.writerow(clean_row)
            links.append((f"row:{idx}", psn))
            counts["records_processed"] += 1
            if psn is not None:
                counts["records_linked"] += 1
        return out.getvalue(), links, counts

    if doc.kind == "patients_json":
        obj = json.loads(json.dumps(doc.payload))
        patients = obj.get("patients") or []
        for idx, p in enumerate(patients):
            if not isinstance(p, dict):
                continue
            rec_id = f"{doc.source}#/patients/{idx}"
            psn = linkage.pseudonym(rec_id)
            offset = linkage.date_offset(rec_id)
            patients[idx] = _sanitize_json_value("patient", p, psn, offset, counts)
            links.append((f"/patients/{idx}", psn))
            counts["records_processed"] += 1
            if psn is not None:
                counts["records_linked"] += 1
        return json.dumps(obj, ensure_ascii=False, indent=2), links, counts

    if doc.kind == "opd_json":
        obj = json.loads(json.dumps(doc.payload))
        if isinstance(obj.get("_export_meta"), dict):
            for mk in ("exported_by", "source_path"):
                if mk in obj["_export_meta"]:
                    obj["_export_meta"][mk] = "[REDACTED]"
                    counts["identifiers_detected"] += 1
        visits = obj.get("visits") or []
        for idx, v in enumerate(visits):
            if not isinstance(v, dict):
                continue
            rec_id = f"{doc.source}#/visits/{idx}"
            psn = linkage.pseudonym(rec_id)
            offset = linkage.date_offset(rec_id)
            visits[idx] = _sanitize_json_value("visit", v, psn, offset, counts)
            links.append((f"/visits/{idx}", psn))
            counts["records_processed"] += 1
            if psn is not None:
                counts["records_linked"] += 1
        return json.dumps(obj, ensure_ascii=False, indent=2), links, counts

    if doc.kind == "lab_json":
        rec_id = f"{doc.source}#doc"
        psn = linkage.pseudonym(rec_id)
        offset = linkage.date_offset(rec_id)
        obj = _sanitize_json_value("root", doc.payload, psn, offset, counts)
        links.append(("doc", psn))
        counts["records_processed"] += 1
        if psn is not None:
            counts["records_linked"] += 1
        return json.dumps(obj, ensure_ascii=False, indent=2), links, counts

    if doc.kind == "generic_json":
        rec_id = f"{doc.source}#doc"
        psn = linkage.pseudonym(rec_id)
        offset = linkage.date_offset(rec_id)
        obj = _sanitize_json_value("root", doc.payload, psn, offset, counts)
        links.append(("doc", psn))
        counts["records_processed"] += 1
        if psn is not None:
            counts["records_linked"] += 1
        return json.dumps(obj, ensure_ascii=False, indent=2), links, counts

    # Plain text (.txt)
    rec_id = f"{doc.source}#doc"
    psn = linkage.pseudonym(rec_id)
    offset = linkage.date_offset(rec_id)
    text, b64_n = _strip_b64_runs(doc.payload)
    counts["identifiers_detected"] += b64_n

    # Generalize Age/Sex lines and PINs before clinical_text
    def _age_sex_repl(m: re.Match[str]) -> str:
        counts["records_generalized"] += 1
        return f"{m.group(1)}{generalize_age(m.group(2))} Yrs/{m.group(3).upper()}"

    text = re.sub(r"(Age(?:/Sex)?\s*[:\-]\s*)(\d{1,3})\s*(?:Yrs?)?\s*/\s*([MFO])", _age_sex_repl, text, flags=re.I)

    def _pin_repl(m: re.Match[str]) -> str:
        counts["records_generalized"] += 1
        return f"{m.group(1)}{generalize_pin(m.group(2))}"

    text = re.sub(r"((?:PIN|Distt\.?\s+[\w\s]+?)\s*[-–:,]\s*)(\d{6})\b", _pin_repl, text, flags=re.I)

    # Shift explicit dates in text
    text = _DATE_TOKEN_RE.sub(lambda m: shift_date_string(m.group(0), offset), text)

    ctx = dict(doc.extra)
    merged_names = list(ctx.get("patient_names") or []) + linkage.cluster_names(rec_id)
    ctx["patient_names"] = merged_names
    res = sanitize_text(text, field="clinical_note", context=ctx)
    counts["identifiers_detected"] += sum(res.counts.values())
    for ek, ev_n in res.counts.items():
        entity_counts[ek] = entity_counts.get(ek, 0) + ev_n
    links.append(("doc", psn))
    counts["records_processed"] += 1
    if psn is not None:
        counts["records_linked"] += 1
    return res.text, links, counts
