"""Compare research aggregates before and after release on organizer synthetic data."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from statistics import median


def measure(paths):
    stays, diagnoses, labs = [], Counter(), defaultdict(list)
    for source, path in paths:
        if source.startswith('fhir/') and source.endswith('.json'):
            bundle = json.loads(path.read_bytes())
            for entry in bundle['entry']:
                item = entry['resource']
                if item['resourceType'] == 'Encounter':
                    period = item.get('period', {})
                    if period.get('start') and period.get('end'):
                        days = (date.fromisoformat(period['end'][:10]) - date.fromisoformat(period['start'][:10])).days
                        stays.append(days)
                elif item['resourceType'] == 'Condition':
                    diagnoses.update(c['code'] for c in item['code']['coding'])
        elif source.startswith('lab/') and source.endswith('.csv'):
            raw = path.read_bytes()
            if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
                text = raw.decode('utf-16')
            else:
                try:
                    text = raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    text = raw.decode('cp1252')
            for row in csv.DictReader(io.StringIO(text)):
                result = row.get('result') or ''
                if row.get('test') and row.get('unit') and result and result[0] not in '<>':
                    try:
                        value = Decimal(result)
                    except ArithmeticError:
                        continue
                    if value.is_finite():
                        labs[row['test'].casefold(), row['unit']].append(value)
    return stays, diagnoses, labs


def check(kit, release):
    inputs = kit / 'dev/input'
    truth = json.loads((kit / 'dev/truth/truth.json').read_bytes())['files']
    released = defaultdict(list)
    for entry in json.loads((release / 'report.json').read_bytes())['files']:
        released[entry['input_sha256']].append(entry)
    before, after, quarantine = [], [], Counter()
    ambiguous = 0
    for source, info in truth.items():
        path = inputs / source
        matches = released.get(hashlib.sha256(path.read_bytes()).hexdigest(), [])
        # Identical quarantined inputs have the same disposition and no output
        # path to disambiguate. Count each source once; do not guess for exports.
        statuses = {row['status'] for row in matches}
        if statuses == {'quarantined'}:
            quarantine[info['category'], info['expect']] += 1
        if info['expect'] != 'sanitize' or not (
            (source.startswith('fhir/') and source.endswith('.json'))
            or (source.startswith('lab/') and source.endswith('.csv'))
        ):
            continue
        if len(matches) != 1 and statuses != {'quarantined'}:
            ambiguous += 1
            continue
        entry = matches[0]
        before.append((source, path))
        if entry['status'] == 'sanitized':
            target = (release / entry['output']).resolve()
            if not target.is_relative_to((release / 'sanitized').resolve()):
                raise ValueError('Report points outside sanitized output')
            after.append((source, target))
    raw_stays, raw_dx, raw_labs = measure(before)
    clean_stays, clean_dx, clean_labs = measure(after)
    return {
        'scope': 'Official synthetic practice: FHIR encounters and condition codes, numeric lab CSV results grouped by test and unit',
        'missing_or_ambiguous_report_matches': ambiguous,
        'quarantines_by_category_and_expected_handling': {f'{category}/{expect}': n for (category, expect), n in sorted(quarantine.items())},
        'fhir_stays_9_days_or_longer': {'input': sum(d >= 9 for d in raw_stays), 'release': sum(d >= 9 for d in clean_stays)},
        'fhir_stay_histogram_unchanged': Counter(raw_stays) == Counter(clean_stays),
        'fhir_diagnosis_distribution_unchanged': raw_dx == clean_dx,
        'fhir_diagnosis_codings': {'input': raw_dx.total(), 'release': clean_dx.total()},
        'lab_test_unit_groups': {'input': len(raw_labs), 'release': len(clean_labs)},
        'lab_measurements': {'input': sum(map(len, raw_labs.values())), 'release': sum(map(len, clean_labs.values()))},
        'lab_groups_with_unchanged_medians': sum(key in clean_labs and median(values) == median(clean_labs[key]) for key, values in raw_labs.items()),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.kit, args.release), indent=2))
