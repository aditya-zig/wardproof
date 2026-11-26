"""Offline release pipeline for supported synthetic laboratory exports."""
import argparse
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import resource
import time

from formats.lab_json import lab_json

HEADER = 'sample_id patient_name age_sex uhid ref_doctor test result unit ref_range collected_on reported_on'.split()
TESTS = {'haemoglobin', 'hemoglobin', 'creatinine', 'serum creatinine', 'glucose', 'platelet count', 'sodium', 'potassium', 'tsh', 'wbc', 'hba1c', 'crp'}
UNITS = {'g/dL', 'mg/dL', 'mmol/L', 'mEq/L', '%', 'mg/L', 'IU/L', 'µIU/mL', '/µL', 'cells/µL'}
NUMBER = r'[<>]?\d{1,5}(?:\.\d{1,4})?'


def token(secret, *parts):
    return hmac.new(secret, '\0'.join(parts).encode(), hashlib.sha256).hexdigest()[:24]


def lab_csv(data, source, secret):
    table = csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''), strict=True)
    if next(table, None) != HEADER:
        raise ValueError
    target = io.StringIO(newline='')
    writer = csv.DictWriter(target, HEADER)
    writer.writeheader()
    patients, identifiers = [], 0
    for cells in table:
        if len(cells) != len(HEADER):
            raise ValueError
        row = dict(zip(HEADER, cells))
        clean = {}
        if row['test'].casefold() in TESTS:
            clean['test'] = row['test']
        if row['unit'] in UNITS:
            clean['unit'] = row['unit']
        if re.fullmatch(NUMBER, row['result']):
            clean['result'] = row['result']
        if re.fullmatch(f'{NUMBER} *[-–] *{NUMBER}', row['ref_range']):
            clean['ref_range'] = row['ref_range']
        # File-scoped IDs for now: do not equate two hospitals' local identifiers.
        uhid = row['uhid'].strip()
        if re.fullmatch(r'[A-Za-z]{1,12}-\d{3,16}', uhid):
            patient = token(secret, 'id', source, uhid)
            clean['uhid'] = 'PSN-' + patient
        writer.writerow(clean)
        patients.append(clean.get('uhid'))
        identifiers += sum(bool(row[k]) for k in ('sample_id', 'patient_name', 'uhid'))
    return target.getvalue(), patients, identifiers


def run(inp, out, secret):
    start = time.monotonic()
    inp, out = inp.resolve(), out.resolve()
    if not inp.is_dir() or inp.is_relative_to(out) or out.is_relative_to(inp):
        raise ValueError
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError
    (out / 'sanitized').mkdir()
    counts = dict.fromkeys(('files_total', 'files_sanitized', 'files_quarantined', 'records_processed', 'identifiers_detected', 'records_linked', 'records_generalized', 'records_suppressed', 'records_quarantined'), 0)
    files = []
    with (out / 'records.jsonl').open('x', encoding='utf-8') as links:
        for path in sorted(inp.rglob('*')):
            if path.is_symlink():
                raise ValueError
            if not path.is_file():
                continue
            source = path.relative_to(inp).as_posix()
            with path.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            entry = {'input_sha256': digest, 'output': None, 'status': 'quarantined', 'reason': 'unsupported_format'}
            ext = path.suffix.lower()
            if ext in {'.csv', '.json'} and path.stat().st_size < 8_000_000:
                try:
                    data = path.read_bytes()
                    if ext == '.json':
                        text, patients, identifiers = lab_json(data)
                    else:
                        text, patients, identifiers = lab_csv(data, source, secret)
                except (ValueError, RecursionError, csv.Error):
                    pass
                else:
                    # Do not disclose unverified filenames or folder names in the release.
                    name = 'sanitized/lab/' + token(secret, 'path', source) + ext
                    (out / name).parent.mkdir(exist_ok=True)
                    (out / name).write_bytes(text.encode())
                    entry = {'input_sha256': digest, 'output': name, 'status': 'sanitized'}
                    for i, patient in enumerate(patients):
                        loc = 'doc' if ext == '.json' else f'row:{i}'
                        links.write(json.dumps({'file': name, 'loc': loc, 'patient': patient}) + '\n')
                    counts['records_processed'] += len(patients)
                    counts['records_linked'] += sum(p is not None for p in patients)
                    counts['identifiers_detected'] += identifiers
            counts['files_' + entry['status']] += 1
            counts['files_total'] += 1
            files.append(entry)
    report = {'schema': 'raksha-report/1', 'files': files, 'counts': counts,
              'timing': {'seconds': round(time.monotonic() - start, 4)},
              'resources': {'peak_rss_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}}
    (out / 'report.json').write_text(json.dumps(report), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('input', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    secret = os.environ.get('RAKSHA_SECRET', '')
    if not secret:
        parser.exit(2, 'Missing release secret.\n')
    try:
        run(args.input, args.output, secret.encode())
    except (OSError, ValueError):
        parser.exit(1, 'Release failed; discard any partial output.\n')
