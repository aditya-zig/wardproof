import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import date

ROOT = Path(__file__).resolve().parents[2]


def release(files, secret='fixture-key'):
    with tempfile.TemporaryDirectory() as tmp:
        inp, out = Path(tmp)/'in', Path(tmp)/'out'
        inp.mkdir()
        for path, text in files.items():
            dest = inp/path
            dest.parent.mkdir(exist_ok=True, parents=True)
            dest.write_bytes(text if isinstance(text, bytes) else text.encode())
        p = subprocess.run([sys.executable, '-B', str(ROOT/'main.py'), '--input', str(inp), '--output', str(out)],
                           env={**os.environ, 'RAKSHA_SECRET': secret}, capture_output=True, check=True)
        assert not p.stdout and not p.stderr
        report = json.loads((out/'report.json').read_text())
        records = [json.loads(s) for s in (out/'records.jsonl').read_text().splitlines()]
        outputs = {p.relative_to(out).as_posix(): p.read_text() for p in (out/'sanitized').rglob('*') if p.is_file()}
        return report, records, outputs


class Journey(unittest.TestCase):
    def test_cli_summary_counts_quarantine_without_printing_input_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = Path(tmp)/'in', Path(tmp)/'out'
            inp.mkdir()
            (inp/'PRIVATE_FIXTURE.pdf').write_text('PRIVATE_CONTENT')
            result = subprocess.run(
                [sys.executable, '-B', str(ROOT/'main.py'), '--input', str(inp), '--output', str(out), '--summary'],
                env={**os.environ, 'RAKSHA_SECRET': 'fixture-key'}, text=True, capture_output=True, check=True,
            )
            self.assertIn('0/1 released · 1 quarantined', result.stdout)
            self.assertIn('0/0 assigned a pseudonym · 0 unlinked', result.stdout)
            self.assertNotIn('PRIVATE_', result.stdout)
            self.assertNotIn('fixture-key', result.stdout)
            self.assertEqual(result.stderr, '')

    def test_link_across_scripts_not_namesakes_and_keep_time_and_dose(self):
        files = {'registration/demo.tsv': 'Name\tUHID\tMobile\tVillage\tAge\nMeera Shah\tDEMO-1001\t9123456780\tRampur\t44\nMeera Shah\tDEMO-1002\t9123456790\tGopalpur\t54\n'.encode('utf-16'),
                 'prescriptions/मीरा.txt': 'OPD Prescription\nनाम: मीरा शाह   आयु: 44 वर्ष\nग्राम: रामपुर\nRx\n1. Tab Ramipril 5 mg 1-0-0 x 9 days\nC/O fever\nC/O FakeRelative\n',
                 'discharge/secret.txt': 'DIS