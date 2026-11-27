"""Build an offline researcher demo from a WardProof release, not from raw records."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re


def cohort(release):
    links = {}
    for line in (release / 'records.jsonl').read_text().splitlines():
        row = json.loads(line)
        if row['loc'] == 'doc' and re.fullmatch(r'PSN-[a-f0-9]{24}', row['patient'] or ''):
            links[row['file']] = row['patient']
    root = (release / 'sanitized').resolve()
    patients = {}
    for name, patient in links.items():
        path = (release / name).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() != '.txt':
            continue
        lines = path.read_text(encoding='utf-8').splitlines()
        if f'Patient: {patient}' not in lines:
            continue
        facts = [line for line in lines if line and not line.startswith(('Patient:', 'Date'))]
        dates = dict(line.split(': ', 1) for line in lines if re.fullmatch(r'Date(?: of (?:Admission|Discharge))?: \d{4}-\d{2}-\d{2}', line))
        start, end = dates.get('Date of Admission'), dates.get('Date of Discharge')
        stay = (date.fromisoformat(end) - date.fromisoformat(start)).days if start and end else None
        events = patients.setdefault(patient, [])
        events.append({'date': start or dates.get('Date'), 'end': end, 'days': stay, 'facts': facts})
    return patients


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new HTML file outside the release')
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.release.resolve()):
        parser.error('write the viewer outside the release')
    patients = cohort(args.release)
    counts = json.loads((args.release / 'report.json').read_text())['counts']
    template = Path(__file__).with_name('research_viewer.html').read_text()
    data = json.dumps({'patients': patients, 'counts': counts}, ensure_ascii=True).replace('<', r'\u003c')
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as dest:
        dest.write(template.replace('__RELEASE_DATA__', data))


if __name__ == '__main__':
    main()
