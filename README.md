# WardProof · Secret Wards (Track 3)

**Goal:** share the clinical history, not the identity. From synthetic Indian hospital exports, create cleaned records, a safe processing receipt and stable pseudonyms. Demo target: two visits under different scripts, a namesake who must stay separate, and an unchanged medicine/dose. Synthetic competition data only. Not safe for real patient data.

**Inspiration:** [RedwoodAI](https://github.com/diyadesai1/RedwoodAI) separates private-identifier detection from a useful downstream document workflow. No RedwoodAI code, models or infrastructure are included. WardProof is standard-library Python, no network or model downloads. [Organizer contract and practice data](https://github.com/Reinforce-SST/Secret-Wards-ToolKit).

## Run the first slice

Linux, Python 3.11+. In a fresh checkout, clone the official team kit outside this repo; set `KIT` to its directory. Example using the sibling reference clone in this workspace:

```sh
KIT=../references/secret-wards-kit
OUT=$(mktemp -d)
RAKSHA_SECRET=practice python3 -B main.py --input "$KIT/dev/input" --output "$OUT"
python3 "$KIT/validate_output.py" --input "$KIT/dev/input" --output "$OUT"
python3 "$KIT/check_dev.py" --output "$OUT"
```

Use an empty output directory. `practice` is only for the public synthetic fixture; no secret is embedded in the output. Quarantined means *reported by input digest and not exported*, not copied to an output quarantine folder. Scope: a strict UTF-8 laboratory CSV schema and a nested diagnostic-panel JSON schema. Run `python3 -B tests/release/test_lab_release.py` for the independent CLI checks. JSON releases retain recognized assay/result/unit/range/LOINC combinations, suppress demographics, dates, narrative and provenance, and intentionally abstain from linkage. The reader quarantines unknown fields, duplicate keys, unsupported panels, and decimals it cannot round-trip without changing their written precision. Only selected lab names, numeric results, units and ranges are kept. Local hospital IDs are pseudonymized within a source file, not yet linked across sources. Ambiguous or unsupported IDs abstain. Input paths are conservatively tokenized instead of assuming any filename is safe; selective path preservation is unfinished. Coverage and utility are currently too low for submission.

## Actual practice baseline

Kit commit `6c0a85a`. On 200 files: **25 released (4 CSV, 21 JSON), 175 quarantined**, 296 records processed. Previously: 4 released, 275 records. Official format validator: `CONTRACT OK`. Practice self-check: 43/3230 personal-data flags (previously 48), 0/4 planted canaries, 631/1088 checked medical values kept (previously 389/825), linkage precision 1.00 / recall 0.07, zero raw copies. All 43 flags were filename checks on quarantined inputs: the practice script checks the original path even when no output exists. This is not a zero-leak guarantee. Medical retention is measured only on exported files, not the entire dump. Neither metric is the hidden score. Other formats, multilingual matching, residual-risk controls and date shifting remain unimplemented.

## Three proposed GitHub issues / agent handoffs

One branch and one PR per owner. Confirm the test boundaries before writing new tests. For each slice: specify observable behavior, see test fail, implement, rerun. Each owner writes tests under their own directory. No real records, raw strings in logs, or runtime reads of practice truth. No agent should edit another owner's files.

1. **A · Clinical text and structured sanitization** — `feat/clinical`; owns `clinical/`, `tests/clinical/`. Public boundary: given a record field plus context, return cleaned text + aggregate detection counts, never raw matches in logs. Start with synthetic `C/O fever` vs a relative name, a Hindi name and `Ramipril 5 mg`. Success: preserve medical bytes while removing identifiers; evaluate English, Hindi and Hinglish separately.
2. **B · Patient linkage and dates** — `feat/linkage`; owns `identity/`, `tests/identity/`. Boundary: take normalized evidence, source namespace and secret; return pseudonym or abstention plus a stable date offset. Success: corroborated records match across files/scripts; namesakes do not; a 9-day stay remains 9 days; secret rotation changes the output. No plaintext identity lookup tables on disk.
3. **C · File handling, release and independent evaluation** — `feat/release`; owns `main.py`, `raksha.toml`, `formats/`, `tests/release/`, README and final PDF. Owns integration of A/B, not their implementations. First add a second supported format without regressing malformed-file quarantine. Preserve safe paths, sanitize headers/metadata, check fresh synthetic cases and official checks. Demo only counts measured from actual exports. Track percentage of *input* records actually released alongside checker scores. Integrate at first working slice, not only at freeze.
