"""Run a fixed synthetic researcher scenario and report measured outcomes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from research_demo import cohort


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='new directory for the synthetic experiment')
    args = parser.parse_args()
    root = args.workspace
    root.mkdir(mode=0o700)
    fixtures = {
        'registrations/west.tsv': ('Hospital ID\tPatient Full Name\tMobile\tDOB\n'
                                   'WEST-101\tIshita Sen\t+९१ ९३४५६७८९०१\t1992-08-20\n'
                                   'WEST-102\tIshita Sen\t9345678902\t1990-08-20\n').encode('utf-16'),
        'registrations/east.csv': ('मरीज़ आईडी,मरीज़ का नाम,Mobile,DOB\n'
                                   'EAST-101,इशिता सेन,9345678901,1992-08-20\n').encode(),
        'notes/journey.txt': ('डिस्चार्ज सारांश\nUHID: EAST-१०१\nभर्ती की तारीख: २०३२-०१-०३\n'
                              'छुट्टी की तारीख: २०३२-०१-१२\nTab Ramipril 5 mg 1-0-0 x 9 days\n').encode(),
        'notes/followup.txt': ('NURSING NOTES\nUHID: WEST-101\nDate: 2032-01-21\nBP 124/78 mmHg\n').encode(),
        'files/unsupported.bin': b'SYNTHETIC-PRIVATE-MARKER',
    }
    for rel, contents in fixtures.items():
        path = root / 'input' / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    pipeline = Path(__file__).resolve().parents[1] / 'main.py'

    def run_pipeline(folder, key):
        release = root / folder
        result = subprocess.run([sys.executable, '-B', str(pipeline), '--input', str(root/'input'), '--output', str(release)],
                                env={**os.environ, 'RAKSHA_SECRET': key}, capture_output=True, check=True)
        if result.stdout or result.stderr:
            raise SystemExit('Expected quiet pipeline execution')
        report = json.loads((release / 'report.json').read_text())
        return release, report, {row['input_sha256']: row for row in report['files']}

    release, report, by_hash = run_pipeline('release', 'synthetic-scenario-key')
    rotated, _, _ = run_pipeline('rotated', 'different-synthetic-key')
    ledger = {(row['file'], row['loc']): row['patient'] for row in map(json.loads, (release/'records.jsonl').read_text().splitlines())}
    labels = [('registrations/west.tsv', 'row:0', 'target'), ('registrations/west.tsv', 'row:1', 'namesake'),
              ('registrations/east.csv', 'row:0', 'target'), ('notes/journey.txt', 'doc', 'target'),
              ('notes/followup.txt', 'doc', 'target')]
    records = [(person, ledger.get((by_hash.get(hashlib.sha256(fixtures[rel]).hexdigest(), {}).get('output'), loc)))
               for rel, loc, person in labels]
    wrong = missed = 0
    for i, (person, alias) in enumerate(records):
        for other, other_alias in records[i+1:]:
            linked = alias is not None and alias == other_alias
            wrong += linked and person != other
            missed += not linked and person == other
    patients = cohort(release)
    dates = lambda p: sorted((event['date'], event['end'], event['days']) for events in p.values() for event in events if event['days'] is not None)
    stays = dates(patients)
    rotated_patients = cohort(rotated)
    artifacts = b'\n'.join(path.read_bytes() for path in release.rglob('*') if path.is_file())
    leaked = any(marker in artifacts for marker in (b'Ishita Sen', 'इशिता सेन'.encode(), b'WEST-101', b'EAST-101', b'9345678901', b'SYNTHETIC-PRIVATE-MARKER'))
    dose_kept = any('Tab Ramipril 5 mg 1-0-0 x 9 days' in event['facts'] for events in patients.values() for event in events)
    timeline_kept = any(len(events) == 2 and any('BP 124/78 mmHg' in event['facts'] for event in events)
                        for events in patients.values())
    quarantined = by_hash[hashlib.sha256(fixtures['files/unsupported.bin']).hexdigest()]['status'] == 'quarantined'
    rotated_stays = dates(rotated_patients)
    key_rotates = bool(stays and rotated_stays and patients.keys().isdisjoint(rotated_patients) and stays != rotated_stays
                       and [row[2] for row in stays] == [row[2] for row in rotated_stays])
    result = {'files_released': report['counts']['files_sanitized'], 'false_merges': wrong, 'missed_links': missed,
              'expected_9_day_stays': 1, 'observed_9_day_stays': sum(days == 9 for _, _, days in stays),
              'dose_kept': dose_kept, 'linked_followup_and_bp_kept': timeline_kept, 'private_marker_leaked': leaked, 'unsupported_file_quarantined': quarantined,
              'key_rotation_changes_alias_and_dates_but_not_stay_length': key_rotates}
    print(json.dumps(result, indent=2))
    if wrong or missed or len(stays) != 1 or stays[0][2] != 9 or not dose_kept or not timeline_kept or leaked or not quarantined or not key_rotates:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
