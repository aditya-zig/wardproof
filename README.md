# WardProof · Secret Wards (Track 3)

**Goal:** Share the clinical history, not the identity. WardProof is an offline, CPU-only, LLM-free privacy firewall for multilingual Indian hospital exports (English, Devanagari Hindi, and Hinglish) built with standard-library Python only.

## Architecture

1. **Clinical Text & Meaning (`clinical/text.py`)**:
   - Multilingual PII redaction (English, Hindi, Hinglish) across names, initials, honorifics, relatives (`S/o`, `D/o`, `W/o`, `C/O <name>`), addresses, phones (ASCII and Devanagari digits), Aadhaar/masked Aadhaar, ABHA, PAN, MRN/UHID, insurance IDs, and unverified `Dr.` mentions.
   - Preserves medical bytes and meaning: `C/O` medical complaints, `K/C/O`, `H/O`, exact doses/units/frequencies (`Ramipril 5 mg`, `650mg 1-1-1 x 5 days`), vitals, medical eponyms (`Addison's disease`, `Parkinson's disease`), verified clinicians, and scoped negation/allergy/family-history assertions.
   - Zero raw PII in logs or aggregate detection counts.
2. **Cross-Script Patient Linkage & Privacy (`identity/linkage.py`)**:
   - Devanagari-to-Latin phonetic transliteration and name normalization (`Mohammad` / `Mohd` / `मोहम्मद`).
   - Precision-first Union-Find clustering with homonym/conflict guards (abstains when evidence is ambiguous).
   - Deterministic `HMAC-SHA256` pseudonyms (`PSN-...`) and patient-consistent day offsets (`±15–90` days) keyed by `RAKSHA_SECRET` so length of stay and visit intervals remain exact.
   - Quasi-identifier generalization: 5-year age bands (`85+` top-coded), 3-digit PIN prefixes (`XXXxxx`), District-level location.
3. **Multi-Format Ingestion & Strict Quarantine (`formats/handlers.py`, `main.py`)**:
   - Supports `.csv` (UTF-8, cp1252), `.tsv` (UTF-16), `.json` (OPD nested visits, FHIR R4 Bundles, Lab panels, Registration arrays), `.txt` (prescriptions, nursing notes, discharge summaries), and `clean/` medical references.
   - Tokenizes output filenames (`HMAC-SHA256`), strips base64 payloads and metadata/key/header PII, and strictly quarantines binary, empty, malformed, or excessively nested (`>64` depth) files by `input_sha256` without copying raw bytes.

## Quick Start & Verification

```sh
RAKSHA_SECRET=practice python3 -B main.py --input ../secret-wards-kit/dev/input --output out
python3 ../secret-wards-kit/validate_output.py --input ../secret-wards-kit/dev/input --output out
python3 ../secret-wards-kit/check_dev.py --output out
python3 ../secret-wards-kit/check_submission.py --repo . --run
python3 -m unittest discover -s tests -v
```

## Measured Practice Results (`dev/input`, 200 files)

- **Format validator (`validate_output.py`)**: `CONTRACT OK`
- **Personal data leaked (`check_dev.py`)**: `154 / 3230` (`4.8%`, down from `3230` baseline) — `0.0%` filename leaks, `0.0%` base64 leaks, `0.0%` DOB/ABHA/PAN/Insurance/Masked-Aadhaar/House leaks.
- **Canaries leaked**: `0 / 4`
- **Medical data kept**: `4676 / 4855` (`96.3%`)
- **Patient linking**: Precision `1.00`, Recall `0.65`, F0.5 `0.90` (`0` wrongful merges)
- **Raw copies**: `0`
