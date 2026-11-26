"""Offline release pipeline for supported synthetic clinical exports."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import resource
import time

from formats.fhir import bundle
from formats.lab_json import lab_json, parse, ASSAYS
from formats.records import decode, outpatient, registration, registration_json, registry_json, seed, table
from identity.link import Index, token
from clinical.text import note
from clinical.risk import RiskSummary

HEADER = 'sample_id patient_name age_sex uhid ref_doctor test result unit ref_range collected_on reported_on'.split()
TESTS = {'haemoglobin', 'hemoglobin', 'creatinine', 'serum creatinine', 'glucose', 'platelet count', 'sodium', 'potassium', 'tsh', 'wbc', 'hba1c', 'crp'}
UNITS = {'g/dL', 'mg/dL', 'mmol/L', 'mEq/L', '%', 'mg/L', 'IU/L', 'µIU/mL', '/µL', 'cells/µL'}
TESTS.update(test for test, _, _ in ASSAYS)
UNITS.update(unit for _, _, unit in ASSAYS)
NUMBER = r'[<>]?[0-9]{1,6}(?:\.[0-9]{1,4})?'
INVALID = (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError, csv.Error)


def lab_csv(data, index):
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
        patient = index.lookup(row['uhid'])
        if patient:
            clean['uhid'] = patient
            for key in ('collected_on', 'reported_on'):
                clean[key] = index.shift(row[key], patient)
        writer.writerow(clean)
        patients.append((f'row:{len(patients)}', patient))
        identifiers += sum(bool(row[k]) for k in ('sample_id', 'patient_name', 'uhid'))
    return target.getvalue(), patients, identifiers


def run(inp, out, secret):
    start = time.monotonic()
    inp, out = inp.resolve(), out.resolve()
    if not inp.is_dir() or inp.is_relative_to(out) or out.is_relative_to(inp):
        raise ValueError
    os.umask(0o077)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError
    (out / 'sanitized').mkdir()
    counts = dict.fromkeys(('files_total', 'files_sanitized', 'files_quarantined', 'records_processed', 'identifiers_detected', 'records_linked', 'records_generalized', 'records_suppressed', 'records_quarantined'), 0)
    files = []
    paths = sorted(inp.rglob('*'))
    if any(p.is_symlink() for p in paths): raise ValueError
    index = Index(secret)
    for path in paths:
        if not path.is_file() or path.stat().st_size >= 8_000_000: continue
        ext = path.suffix.lower()
        try:
            if ext in ('.tsv','.csv'):
                header, _, rows, _ = table(path.read_bytes(), ext)
                seed(index, rows, any('MM/DD' in h for h in header))
            elif ext == '.json':
                seed(index, registry_json(parse(path.read_bytes())))
        except INVALID: continue
    index.finish()
    risk = RiskSummary()
    with (out / 'records.jsonl').open('x', encoding='utf-8') as links:
        for path in paths:
            if path.is_symlink():
                raise ValueError
            if not path.is_file():
                continue
            source = path.relative_to(inp).as_posix()
            with path.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            entry = {'input_sha256': digest, 'output': None, 'status': 'quarantined', 'reason': 'unsupported_format'}
            ext = path.suffix.lower()
            if ext in {'.csv', '.tsv', '.txt', '.json'} and path.stat().st_size < 8_000_000:
                try:
                    data = path.read_bytes()
                    if ext == '.json':
                        doc = parse(data)
                        if isinstance(doc, dict) and doc.get('resourceType') == 'Bundle':
                            text, patients, identifiers = bundle(doc, index, source)
                            category = 'fhir'
                        else:
                            if 'visits' in doc: handler, category = outpatient, 'opd'
                            elif 'patients' in doc: handler, category = registration_json, 'registration'
                            else: handler, category = lab_json, 'lab'
                            text, patients, identifiers = handler(doc, index)
                    elif ext == '.txt':
                        text, patients, identifiers = note(decode(data), index)
                        category = 'notes'
                    else:
                        try:
                            text, patients, identifiers = registration(data, ext, index)
                            category = 'registration'
                        except ValueError:
                            if ext != '.csv': raise
                            text, patients, identifiers = lab_csv(data, index)
                            category = 'lab'
                except INVALID:
                    pass
                else:
                    if category in {'opd', 'fhir'}:
                        risk.add(category, json.loads(text), patients)
                    # Keep recognized neutral path components, pseudonymize the rest in place.
                    folders = {'registration','prescriptions','notes','discharge','opd','lab','fhir'}
                    parts = path.relative_to(inp).parts
                    parents = [part if part in folders else 'dir-' + token(secret, 'dir', *parts[:i+1])
                               for i, part in enumerate(parts[:-1])]
                    stem = path.stem if re.fullmatch(r'(?:patients|visits|prescriptions|results|report|registration|sample)(?:_[0-9]{1,4})?', path.stem) else token(secret,'path',source)
                    name = '/'.join(('sanitized', *parents, stem + path.suffix))
                    (out / name).parent.mkdir(parents=True, exist_ok=True)
                    (out / name).write_bytes(text.encode())
                    entry = {'input_sha256': digest, 'output': name, 'status': 'sanitized'}
                    for loc, patient in patients:
                        links.write(json.dumps({'file': name, 'loc': loc, 'patient': patient}) + '\n')
                    counts['records_processed'] += len(patients)
                    counts['records_linked'] += sum(p is not None for _, p in patients)
                    counts['identifiers_detected'] += identifiers
            counts['files_' + entry['status']] += 1
            counts['files_total'] += 1
            files.append(entry)
    report = {'schema': 'raksha-report/1', 'files': files, 'counts': counts,
              'risk_proxy': risk.counts(),
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
