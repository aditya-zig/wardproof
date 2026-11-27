"""Compare two FHIR stay views on an existing synthetic release; print aggregates only."""
import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path


def compare(root):
    paths = set()
    sanitized = (root / 'sanitized').resolve()
    for line in (root / 'records.jsonl').read_text().splitlines():
        record = json.loads(line)
        if record['loc'] == 'doc' and record['patient'] and record['file'].endswith('.json'):
            path = (root / record['file']).resolve()
            if path.is_relative_to(sanitized):
                paths.add((path, record['patient']))
    exact, bands = defaultdict(set), defaultdict(set)
    stays = cohort = band_cohort = 0
    for path, patient in paths:
        bundle = json.loads(path.read_text())
        if bundle.get('resourceType') != 'Bundle':
            continue
        resources = [entry['resource'] for entry in bundle['entry']]
        codes = {r['code']['coding'][0]['code'] for r in resources if r['resourceType'] == 'Condition'}
        for r in resources:
            if r['resourceType'] != 'Encounter':
                continue
            period = r.get('period', {})
            if not (period.get('start') and period.get('end')):
                continue
            days = (date.fromisoformat(period['end'][:10]) - date.fromisoformat(period['start'][:10])).days
            if days < 0:
                continue
            stays += 1
            cohort += days >= 9
            low = days // 3 * 3
            band_cohort += low >= 9
            for code in codes:
                exact[days, code].add(patient)
                bands[low, code].add(patient)
    def unique(groups):
        return len(set().union(*(p for p in groups.values() if len(p) == 1)))
    return {'linked_fhir_stays': stays, 'patients_with_stay_and_diagnosis': len(set().union(*exact.values())),
            'unique_patients_exact_days_and_code': unique(exact), 'unique_patients_three_day_band_and_code': unique(bands),
            'stays_at_least_9_days_exact': cohort, 'stays_at_least_9_days_in_bands': band_cohort,
            'note': 'Simulation only. 9 is a band boundary; exact stay lengths are lost. No change to released files or attacker score claimed.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    print(json.dumps(compare(parser.parse_args().release), indent=2))
