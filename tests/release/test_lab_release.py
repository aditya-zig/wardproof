import csv
import io
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
                (inp / name).write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
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

    def test_csv_decodes_utf16_and_abstains_on_conflicting_name(self):
        registry = {'schema':'dhh.registration.v3', 'patients':[{'uhid':'JJH-91480',
                    'name':{'first':'Example','last':'Patient'}, 'registered_on':'2032-01-01',
                    'address':{'village':'Rampur'}, 'contact':{'mobile':''}, 'dob':'1980-01-01'}]}
        header = 'sample_id,patient_name,age_sex,uhid,ref_doctor,test,result,unit,ref_range,collected_on,reported_on'
        row = 'Private sample,नीला नमूना,,JJH-91480,,Haemoglobin,<10.10,g/dL,12–16,2032-01-02,2032-01-03'
        for 