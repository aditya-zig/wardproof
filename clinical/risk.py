"""An aggregate uniqueness diagnostic, not an attacker or anonymity guarantee."""
from collections import defaultdict
from datetime import date


class RiskSummary:
    def __init__(self):
        self.groups = defaultdict(set)
        self.patients = set()

    def add(self, category, doc, records):
        if category == 'opd':
            for visit in doc['visits']:
                self._add(visit['patient_ref'], visit['visit_date'], [d['code'] for d in visit['diagnosis']])
        elif category == 'fhir':
            resources = [entry['resource'] for entry in doc['entry']]
            start = next((r.get('period', {}).get('start', '') for r in resources if r['resourceType'] == 'Encounter'), '')
            self._add(records[0][1], start, [r['code']['coding'][0]['code'] for r in resources if r['resourceType'] == 'Condition'])

    def _add(self, patient, day, codes):
        if not (patient and day and codes):
            return
        week = date.fromisoformat(day[:10]).isocalendar()[:2]
        self.patients.add(patient)
        for code in codes:
            self.groups[week, code].add(patient)

    def counts(self):
        unique = set().union(*(p for p in self.groups.values() if len(p) == 1))
        return {'patients_evaluated': len(self.patients), 'patients_with_unique_shifted_week_diagnosis': len(unique)}
