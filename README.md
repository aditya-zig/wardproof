# WardProof · DevForge Secret Wards (Track 3)

**Share the clinical history, not the identity.** WardProof projects synthetic Indian hospital exports onto allowlisted clinical fields, links corroborated records with keyed pseudonyms, and quarantines unsupported files. Standard-library Python 3.11+ on Linux; no network, GPU, LLM, dependency install, or model download. **Synthetic competition data only. Do not use this with real patient records.**

[Project brief (PDF)](docs/brief.pdf) · [Organizer kit and practice data](https://github.com/Reinforce-SST/Secret-Wards-ToolKit)

## Run locally

Clone the official kit **outside** this repo. Set `KIT` to its path, and run from WardProof:

```sh
KIT=../secret-wards-kit
OUT=$(mktemp -d)
RAKSHA_SECRET=practice python3 -B main.py --input "$KIT/dev/input" --output "$OUT"
python3 "$KIT/validate_output.py" --input "$KIT/dev/input" --output "$OUT"
python3 "$KIT/check_dev.py" --output "$OUT"
python3 -B -m unittest discover -s tests/release -v
python3 "$KIT/check_submission.py" --repo . --run
```

`practice` is a public fixture key. For other synthetic exports, inject your own high-entropy `RAKSHA_SECRET` from a secret store. Use a new empty output directory, separate from the input; discard the output if the process exits nonzero.

## Pipeline and trust boundary

```text
CSV / TSV / JSON / FHIR / notes → recognize supported schemas
     ├─ registry evidence in RAM → corroborate or abstain → HMAC pseudonym
     └─ project allowlisted clinical values, shift dates, rewrite IDs and paths
            → sanitized/ + records.jsonl + report.json
Unsupported / malformed → digest and quarantine status only; no exported copy
```

- **Structured data:** Recognized registration and lab CSV/TSV/JSON, OPD JSON, and a narrow single-patient FHIR R4 document subset. FHIR references are regenerated and attachments, narrative and source metadata removed. It is not a generic FHIR validator.
- **Clinical text:** Positive projection of recognized medicines, doses, observations and diagnoses, not an unfiltered note with names blotted out. `C/O fever` survives; `C/O FakeRelative` does not. Selected Hindi discharge diagnoses and dates, and lab values in forwarded text panels, are supported. Forwarded panels without corroborated identity remain unlinked. Lines with recognized negation, family history, allergy and stop markers are withheld rather than turned into positive findings. Unrecognized context can still be lost. Supported FHIR condition verification codes are preserved. Clinician names and unrecognized clinical spans are not retained.
- **Linkage and privacy:** Explicit Devanagari transliteration plus phonetic matching. Cross-facility linkage requires phone, DOB and compatible name; a text reference without an ID can match a unique full name and village. Ambiguous candidates abstain. Keyed date offsets preserve intervals within a patient. Age and location are dropped, not generalized. Unknown names and paths are not emitted. Rare diagnoses and exact stay lengths can still be identifying.
- **Storage:** No raw intermediates, identity indexes, secrets, or quarantine copies on disk. Input is read-only from WardProof's perspective. New directories and files are private by default; no raw strings are logged. Store raw inputs and released data on an encrypted volume and keep its credentials outside this repo. The app does not encrypt the input volume itself. Treat output as sensitive, not anonymous.

## Measured on the official synthetic practice set

Kit `6c0a85a`: **175/200 files released**, 25 quarantined, 749 ledger records, 701 with a pseudonym. Organizer validator: `CONTRACT OK`. Same-key runs reproduced the release and ledger; key rotation changed the pseudonyms. Verified in a Linux network namespace with no network access on two logical CPUs. The release took about **0.14 s** and **23 MiB peak RSS** on this machine.

- Practice checker: **3,541/4,687 medical values retained (75.5%)**. The checker does not count all medical values in quarantined files, so report file coverage separately.
- Linkage precision **1.00**, recall **0.80**, F0.5 **0.95**; 0 wrong merges measured. This is not evidence that matching never merges distinct people.
- **0/3,230** personal-data flags, **0/4 canaries**, zero unchanged copies of unsupported files. These figures are not a privacy guarantee or hidden score.
- Risk diagnostic: **50/51 evaluated patients** had at least one unique `(shifted ISO week, diagnosis code)` pair in released OPD/FHIR records. Age and location do not enter the pair because WardProof removes them. For FHIR stays, **16/19 evaluated patients** had a unique `(calendar-day stay length, diagnosis code)` pair. Both are uniqueness proxies, not the contest's attack. Shifting dates does not hide the length of a stay.
- Independently authored regression fixtures cover Hindi-to-Latin matching, namesakes, a 9-day interval, dose preservation, alternate headers and date formats, FHIR references and attachment suppression, and malformed/unsupported-file quarantine. Not evaluated on a hidden dataset.

### Problem-statement gaps

- The organizer's checker accepts the output, but the written spec also asks for original paths and schemas where safe. WardProof preserves recognized neutral path components and nesting; it pseudonymizes other components in place. It rebuilds the supported FHIR subset rather than preserving arbitrary input structure.
- The system keeps recognized clinical values, not every clinical detail. It drops clinician names rather than distinguishing them from all relatives, and abstains on weak identity evidence. An encrypted volume must be configured separately. The practice checks do not reproduce the official hidden attack.

[RedwoodAI](https://github.com/diyadesai1/RedwoodAI) inspired the privacy-first document workflow; no code, models, or services from it are used.
