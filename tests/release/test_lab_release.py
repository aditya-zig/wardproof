import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def example():
    return {'lab': 'Private laboratory', 'report_type': 'Diagnostic report',
            'patient': {'name': 'नीला नमूना', 'age': 41, 'sex': 'F', 'phone': '9012345678',
                        'hospital_uhid': 'ZZ-123456'}, 'referred_by': 'Private referral',
            'collected': '2025-02-01', 'remarks': 'Recipient: नीला नमूना', 'panels': [
                {'name': 'Routine', 'results': [{'test': 'Haemoglobin', 'loinc': '718-7',
                 'value': 10.1, 'unit': 'g/dL', 'range': '12.0-16.0'}]}]}


class LabRelease(unittest.TestCase):
    def run_release(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp, out = root / 'in', root / 'out'
            inp.mkdir()
            for name, data in files.items():
                (inp / name).write_text(data, encoding='utf-8')
            proc = subprocess.run([sys.executable, '-B', str(ROOT / 'main.py'), '--input', str(inp),
                                   '--output', str(out)], env={**os.environ, 'RAKSHA_SECRET': 'test-only'},
                                  check=True, capture_output=True, text=True)
            payload = {p.relative_to(out).as_posix(): p.read_text() for p in out.rglob('*') if p.is_file()}
            # Decode escaped Unicode as well as checking the serialized documents and paths.
            visible = repr(payload) + proc.stdout + proc.stderr + ''.join(
                str(json.loads(v)) for k, v in payload.items() if k.endswith('.json'))
            for private in ('9012345678', 'नीला नमूना', 'ZZ-123456', 'Private referral', 'test-only'):
                self.assertNotIn(private, visible)
            return json.loads(payload['report.json']), payload

    def test_json_report_keeps_clinical_panel_without_identity(self):
        original = example()
        report, payload = self.run_release({'9012345678.json': json.dumps(original)})
        entry, = report['files']
        self.assertEqual(entry['status'], 'sanitized')
        document = json.loads(payload[entry['output']])
        self.assertEqual(document['panels'][0]['results'], original['panels'][0]['results'])
        self.assertEqual(json.loads(payload['records.jsonl']),
                         {'file': entry['output'], 'loc': 'doc', 'patient': None})

    def test_quarantine_ambiguous_or_malformed_json_without_partial_release(self):
        valid = json.dumps(example())
        cases = [valid.replace('"remarks":', '"remarks": "hidden", "remarks":'),
                 valid.replace('"age": 41', '"age": NaN'),
                 valid.replace('"panels":', '"private metadata": 3, "panels":'),
                 valid.replace('10.1', '"9012345678"'), '[' * 1600 + ']' * 1600]
        files = {f'bad{i}.json': data for i, data in enumerate(cases)}
        files['valid.json'] = valid
        report, payload = self.run_release(files)
        self.assertEqual(report['counts']['files_quarantined'], len(cases))
        self.assertEqual(report['counts']['files_sanitized'], 1)
        self.assertEqual(sum(p.startswith('sanitized/') for p in payload), 1)
        self.assertEqual(len(payload['records.jsonl'].splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
