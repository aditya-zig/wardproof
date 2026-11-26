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
    def test_link_across_scripts_not_namesakes_and_keep_time_and_dose(self):
        files = {'registration/demo.tsv': 'Name\tUHID\tMobile\tVillage\tAge\nMeera Shah\tDEMO-1001\t9123456780\tRampur\t44\nMeera Shah\tDEMO-1002\t9123456790\tGopalpur\t54\n'.encode('utf-16'),
                 'prescriptions/मीरा.txt': 'OPD Prescription\nनाम: मीरा शाह   आयु: 44 वर्ष\nग्राम: रामपुर\nRx\n1. Tab Ramipril 5 mg 1-0-0 x 9 days\nC/O fever\nC/O FakeRelative\n',
                 'discharge/secret.txt': 'DISCHARGE SUMMARY\nUHID: DEMO-1001\nDate of Admission: 2031-03-02\nDate of Discharge: 2031-03-11\nC/O fever\n'}
        report, ledger, outputs = release(files)
        self.assertEqual(report['counts']['files_sanitized'], 3)
        reg = [r['patient'] for r in ledger if r['loc'].startswith('row:')]
        self.assertTrue(all(reg)); self.assertNotEqual(*reg)
        docs = [r for r in ledger if r['loc']=='doc']; self.assertEqual(len(docs), 2)
        self.assertTrue(all(r['patient']==reg[0] for r in docs)); text='\n'.join(outputs.values())
        self.assertIn('Ramipril 5 mg 1-0-0 x 9 days',text); self.assertIn('C/O fever',text)
        for raw in ['9123456780','FakeRelative','DEMO-100','मीरा','Meera','Rampur','रामपुर','2031-03-02']:
            self.assertNotIn(raw, str(outputs))
        dates = [date.fromisoformat(s.split(': ')[1]) for s in text.splitlines() if s.startswith('Date of ')]
        self.assertEqual((dates[1]-dates[0]).days,9)
        self.assertEqual(release(files)[1:],(ledger,outputs)); self.assertNotEqual(release(files,'second')[1],ledger)

    def test_alternate_headers_dates_and_overlap_abstention(self):
        files = {
            'one/registrar.tsv': 'Patient ID\tPatient Name\tPhone Number\tCity\tBirth Date\tRegistration Date\n'
                                 'DEMO-1234\tNaina Rao\t+91 9876543212\tSundarpur\t22.08.1987\t01.03.2032\n'
                                 'DEMO-1235\tNaina Rao\t9876543213\tSundarpur\t1987-08-22\t2032-03-01\n',
            'two/registrar.csv': 'FirstName,LastName,PatientID,Phone,DOB (MM/DD/YYYY)\nNaina,Rao,SITE-9981,9876543212,08/22/1987\n',
            'prescriptions/नैना.txt': 'OPD Prescription\nनाम: नैना राव\nग्राम: सुंदरपुर\nRx\nTab Metformin 500 mg BD x 7 days\n',
            'misc/scan.pdf': '%PDF-1.3 synthetic-private-marker',
        }
        report, ledger, outputs = release(files)
        self.assertEqual(report['counts']['files_sanitized'], 3)
        self.assertEqual(report['counts']['files_quarantined'], 1)
        visits = [r['patient'] for r in ledger if r['loc'] != 'doc']
        self.assertEqual(visits[0], visits[2]); self.assertNotEqual(visits[0], visits[1])
        self.assertIsNone(next(r['patient'] for r in ledger if r['loc'] == 'doc'))
        self.assertNotIn('01.03.2032', str(outputs))
        self.assertNotIn('synthetic-private-marker', str(outputs))
        self.assertIn('Metformin 500 mg BD x 7 days', str(outputs))

    def test_fhir_attachment_removed_and_references_resolve(self):
        def entry(ref, resource_type, **fields):
            return {'fullUrl':'urn:uuid:'+ref, 'resource':{'resourceType':resource_type, 'id':ref, **fields}}
        from uuid import UUID
        a,b,c,d,e=[str(UUID(int=i)) for i in range(1,6)]
        subject={'reference':'urn:uuid:'+b,'display':'FakePatient'}
        bundle={'resourceType':'Bundle','type':'document','entry':[
            entry(a,'Composition',status='final',subject=subject,author=[{'reference':'urn:uuid:'+c}],date='2030-01-10T09:15:00+05:30',section=[{'title':'Labs','entry':[{'reference':'urn:uuid:'+d},{'reference':'urn:uuid:'+e}]}]),
            entry(b,'Patient',identifier=[{'value':'JJH-12345'}]),entry(c,'Practitioner',name=[{'text':'FakeDoctor'}]),
            entry(d,'Observation',status='preliminary',subject=subject,code={'coding':[{'code':'718-7','display':'Haemoglobin'}]},valueQuantity={'value':10.1,'unit':'g/dL'}),
            entry(e,'DocumentReference',subject=subject,content=[{'attachment':{'data':'RmFrZVBhdGllbnQ='}}]) ]}
        _, ledger, outputs=release({'fhir/FakePatient.json':json.dumps(bundle)})
        self.assertEqual(len(outputs),1); result=json.loads(next(iter(outputs.values())))
        self.assertNotIn('FakePatient',str(outputs)); self.assertNotIn('RmFrZVBhdGllbnQ=',str(outputs));self.assertNotIn(b,str(outputs))
        urls={e['fullUrl'] for e in result['entry']}
        for e in result['entry']:
            r=e['resource']
            if 'subject' in r: self.assertIn(r['subject']['reference'], urls)
            if r['resourceType']=='Observation':
                self.assertEqual(r['valueQuantity']['value'],10.1)
                self.assertEqual(r['status'],'preliminary')
        self.assertEqual(result['entry'][1]['resource']['identifier'][0]['value'],ledger[0]['patient'])


if __name__ == '__main__': unittest.main()
