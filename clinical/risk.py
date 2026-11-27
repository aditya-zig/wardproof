"""An aggregate uniqueness diagnostic, not an attacker or anonymity guarantee."""
from collections import defaultdict
from datetime import date


class RiskSummary:
    def __init__(self):
        self.groups = defaultdict(set)
        self.patients = set()
        self.stays = defaultdict(set)
        self.stay_patients = set()

    def add(self, category, doc, records):
        if category == 'opd':
            for visit in doc['visits']:
                self._add(visit['patient_ref'], visit['visit_date'], [d['code'] for d in visit['diagnosis']])
        elif category == 'fhir':
            resources = [entry['resource'] for entry in doc['entry']]
            period = next((r.get('period', {}) for r in resources if r['resourceType'] == 'Encounter'), {})
            start, end = period.get('start'), period.get('end')
            codes = [r['code']['coding'][0]['code'] for r in resources if r['resourceType'] == 'Condition']
            patient = records[0][1]
            self._add(patient, start, codes)
            if patient and start and end and codes:
                days = (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
                if days >= 0:
                    self.stay_patients.add(patient)
                    for code in codes:
                        self.stays[days, code].add(patient)

    def _add(self, patient, day, codes):
        if not (patient and day and codes):
            return
        week = date.fromisoformat(day[:10]).isocalendar()[:2]
        self.patients.add(patient)
        for code in codes:
            self.groups[week, code].add(patient)

    def counts(self):
        unique = set().union(*(p for p in self.groups.values() if len(p) == 1))
        unique_stays = set().union(*(p for p in self.stays.values() if len(p) == 1))
        return {'patients_evaluated': len(self.patients), 'patients_with_unique_shifted_week_diagnosis': len(unique),
                'fhir_stay_patients_evaluated': len(self.stay_patients), 'fhir_patients_with_unique_stay_diagnosis': len(unique_stays)}
