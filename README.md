# WardProof · DevForge Secret Wards (Track 3)

**Share the clinical history, not the identity.** WardProof projects synthetic Indian hospital exports onto allowlisted clinical fields, links corroborated records with keyed pseudonyms, and quarantines unsupported files. Standard-library Python 3.11+ on Linux; no network, GPU, LLM, dependency install, or model download. **Synthetic competition data only. Do not use this with real patient records.**

[Project brief (PDF)](docs/brief.pdf) · [Organizer kit and practice data](https://github.com/Reinforce-SST/Secret-Wards-ToolKit)

## Run locally

Clone the official kit **outside** this repo. Set `KIT` to its path, and run from WardProof:

```sh
KIT=../secret-wards-kit
OUT=$(mktemp -d)
RAKSHA_SECRET=practice python3 -B main.py --input "$KIT/dev/input" --output "$OUT" --summary
python3 "$KIT/validate_output.py" --input "$KIT/dev/input" --output "$OUT"
python3 "$KIT/check_dev.py" --output "$OUT"
python3 -B -m unittest discover -s tests/release -v
python3 "$KIT/check_submission.py" --repo . --run
```

`--summary` prints file coverage, quarantine, linkage and runtime without input names or values. The organizer command remains quiet without it. For the live demo, run the summary first, then show the validator's `CONTRACT OK` and the practice checker's results separately.

`practice` is a public fixture key. For other synthetic exports, inject your own high-entropy `RAKSHA_SECRET` from a secret store. Use a new empty output directory, separate from the input; discard the output if the process exits nonzero.

## Researcher demo (offline)

[Two-page project brief](docs/brief.pdf) · [18-second demo recording](docs/demo/wardproof.mp4) · [Self-contained demo HTML](docs/demo/wardproof.html) (download and open locally). The demo uses synthetic records.

```sh
DEMO=$(mktemp -d)
python3 -B tools/scenario.py "$DEMO/trial"
python3 -B tools/research_demo.py --release "$DEMO/trial/release" --output "$DEMO/viewer.html"
```

Open `viewer.html` locally in a browser. Filter for nine-day stays, select a patient, and download the cohort CSV. This viewer only reads linked text notes from the sanitized release; it does not need the input or `RAKSHA_SECRET`, and does not include every record type. The HTML and CSV contain release data: treat both as sensitive. The scenario is a small team-authored changed-format regression, not an independent held-out benchmark or the hidden evaluation.

For the official practice run above, `python3 -B tools/loss_breakdown.py --kit "$KIT" --release "$OUT"` breaks down missing and quarantined clinical 