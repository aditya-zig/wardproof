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

    def test_registration_keeps_schema_and_does_not_invent_age(self):
        patient = {'uhid':'JJH-91480', 'name':{'first':'Meera','last':'Shah','local':'मीरा शाह'},
                   'dob':'1980-04-15','age':52,'guardian':{'relation':'mother','name':'Example Relative'},
                   'contact':{'mobile':'9123456780','email':None}, 'address':{'village':'Rampur'},
                   'ids':{'aadhar_no':999988887777}, 'registered_on':'2032-02-18'}
        doc = {'schema':'dhh.registration.v3','facility':{'name':'Sensitive Facility','type':'charitable','state':'Example State'},
               'exported_at':'2032-02-19','patients':[patient]}
        _, ledger, outputs = release({'registration/patients.json':json.dumps(doc)})
        result = json.loads(next(iter(outputs.values())))
        self.assertEqual(set(result), set(doc))
        cleaned = result['patients'][0]
        self.assertEqual(set(cleaned), set(patient))
        self.assertEqual(cleaned['uhid'], ledger[0]['patient'])
        self.assertEqual(cleaned['name'], {'first':'','last':'','local':''})
        self.assertIsNone(cleaned['age'])
        self.assertIsNone(cleaned['ids']['aadhar_no'])
        self.assertEqual(cleaned['contact'], {'mobile':'','email':None})
        self.assertNotIn('Sensitive Facility', str(result))
        self.assertNotIn('1980-04-15', str(result))
        self.assertNotEqual(cleaned['registered_on'], '2032-02-18')

    def test_short_discharge_preserves_facts_without_guessing_identity_or_year(self):
        raw = ('Discharge note\n\nPrivate Patient, W/o Private Relative, discharged in stable condition.\n'
               'Visit: 5 September\nTreated for Essential (primary) hypertension. BP 168/92. Continue Amlodipine 5 mg 0-0-1.\n')
        _, ledger, outputs = release({'discharge/Private Patient.txt':raw})
        text, = outputs.values()
        self.assertIsNone(ledger[0]['patient'])
        for value in ('Essential (primary) hypertension','BP 168/92','Amlodipine 5 mg 0-0-1'):
            self.assertIn(value,text)
        for private in ('Private Patient','Private Relative','5 September'):
            self.assertNotIn(private, str(outputs))

    def test_billing_keeps_procedure_and_stay_but_not_payer(self):
        header = 'bill_no,uhid,patient_name,pmjay_id,payer_pan,policy_no,package_code,procedure,admission_date,discharge_date,amount_inr,status'
        raw = ','.join(('BILL-PRIVATE','JJH-90440','Meera Shah','PMJAY-PRIVATE','PAN-PRIVATE','POLICY-PRIVATE',
                        'SG001A','Appendicectomy','02/03/2032','11/03/2032','38500','approved'))
        _, ledger, outputs = release({'billing/export.csv':f'{header}\n{raw}\n'})
        text = next(iter(outputs.values())); columns, row = text.splitlines()
        self.assertEqual(columns, header)
        row = dict(zip(columns.split(','),row.split(','),strict=True))
        self.assertEqual(row['procedure'],'Appendicectomy')
        self.assertEqual(row['package_code'],'SG001A')
        self.assertEqual(row['uhid'],ledger[0]['patient'])
        start,end = (date.fromisoformat(row[k]) for k in ('admission_date','discharge_date'))
        self.assertEqual((end-start).days,9)
        for key in ('bill_no','patient_name','pmjay_id','payer_pan','policy_no','amount_inr'):
            self.assertEqual(row[key],'')

    def test_context_is_not_released_as_a_positive_finding(self):
        _, _, outputs = release({'notes/example.txt': 'NURSING NOTES\nNo C/O fever\nFamily history: Parkinson\'s disease\nAllergy: Amoxicillin 500 mg\nBP 115/82\nTab Ramipril 5 mg 1-0-0\n'})
        text = next(iter(outputs.values()))
        self.assertIn('BP 115/82', text)
        self.assertIn('Ramipril 5 mg 1-0-0', text)
        for context_bound in ('C/O fever', "Parkinson's disease", 'Amoxicillin'):
            self.assertNotIn(context_bound, text)

    def test_conflicting_note_name_abstains_even_with_known_id(self):
        _, ledger, _ = release({
            'registration/patients.csv': 'Name,UHID\nMeera Shah,JJH-91480\n',
            'notes/conflict.txt': 'NURSING NOTES\nName: Anil Rao\nUHID: JJH-91480\nBP 115/82\n',
        })
        self.assertIsNotNone(next(row['patient'] for row in ledger if row['loc'] == 'row:0'))
        self.assertIsNone(next(row['patient'] for row in ledger if row['loc'] == 'doc'))

    def test_hindi_discharge_and_forwarded_labs(self):
        report, ledger, outputs = release({
            'discharge/सविता.txt': 'Example Hospital\nडिस्चार्ज सारांश\nमरीज़ का नाम: सविता राव\nपंजीकरण सं.: JJH-91480\nभर्ती की तारीख: ०२-०३-२०३२\nछुट्टी की तारीख: ११-०३-२०३२\nनिदान: निमोनिया (J18.9);\nCap Doxycycline 100 mg 1-0-1 x 15 days\n',
            'lab/chat.txt': 'Forwarded\n*Example Lab*\nReport of Fake Person\nHbA1c 7.5 % | Serum Creatinine 1.9 mg/dL |\nDolo 650 BD x 5 days lena hai\nCall 9999988888\n',
        })
        self.assertEqual(report['counts']['files_sanitized'], 2)
        notes = '\n'.join(outputs.values())
        for value in ('निमोनिया (J18.9)', 'Doxycycline 100 mg 1-0-1 x 15 days', 'HbA1c 7.5 %', 'Serum Creatinine 1.9 mg/dL', 'Dolo 650 BD x 5 days'):
            self.assertIn(value, notes)
        for private in ('सविता', 'JJH-91480', 'Fake Person', '9999988888'):
            self.assertNotIn(private, notes + str(outputs))
        days = [date.fromisoformat(s.split(': ')[1]) for s in notes.splitlines() if s.startswith('Date of ')]
        self.assertEqual((days[1] - days[0]).days, 9)
        self.assertEqual(sum(row['patient'] is None for row in ledger), 1)

    def test_fhir_attachment_removed_and_references_resolve(self):
        def entry(ref, resource_type, **fields):
            return {'fullUrl':'urn:uuid:'+ref, 'resource':{'resourceType':resource_type, 'id':ref, **fields}}
        from uuid import UUID
        a,b,c,d,e,f,g=[str(UUID(int=i)) for i in range(1,8)]
        subject={'reference':'urn:uuid:'+b,'display':'FakePatient'}
        bundle={'resourceType':'Bundle','type':'document','entry':[
            entry(a,'Composition',status='final',subject=subject,author=[{'reference':'urn:uuid:'+c}],date='2030-01-10T09:15:00+05:30',section=[{'title':'Labs','entry':[{'reference':'urn:uuid:'+d},{'reference':'urn:uuid:'+e}]}]),
            entry(b,'Patient',identifier=[{'value':'JJH-12345'}]),entry(c,'Practitioner',name=[{'text':'FakeDoctor'}]),
            entry(d,'Observation',status='preliminary',subject=subject,code={'coding':[{'code':'718-7','display':'Haemoglobin'}]},valueQuantity={'value':10.1,'unit':'g/dL'}),
            entry(e,'DocumentReference',subject=subject,content=[{'attachment':{'data':'RmFrZVBhdGllbnQ='}}]),
            entry(f,'Condition',subject=subject,code={'coding':[{'code':'A97.9','display':'Dengue, unspecified'}]},verificationStatus={'coding':[{'code':'refuted','display':'FakePatient'}]}),
            entry(g,'Encounter',subject=subject,status='finished',**{'class': {'code':'IMP'}},period={'start':'2030-01-10','end':'2030-01-19'}) ]}
        report, ledger, outputs=release({'fhir/FakePatient.json':json.dumps(bundle)})
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
        condition = next(e['resource'] for e in result['entry'] if e['resource']['resourceType']=='Condition')
        self.assertEqual(condition['verificationStatus']['coding'][0]['code'], 'refuted')
        self.assertNotIn('display', condition['verificationStatus']['coding'][0])
        period = next(e['resource']['period'] for e in result['entry'] if e['resource']['resourceType']=='Encounter')
        self.assertEqual((date.fromisoformat(period['end'])-date.fromisoformat(period['start'])).days, 9)
        self.assertEqual(report['risk_proxy']['fhir_stay_patients_evaluated'], 1)
        self.assertEqual(report['risk_proxy']['fhir_patients_with_unique_stay_diagnosis'], 1)
        # A resolvable reference can still be invalid for this R4 element.
        bundle['entry'][0]['resource']['encounter'] = {'reference':'urn:uuid:'+d}
        report, ledger, outputs = release({'fhir/wrong-target.json':json.dumps(bundle)})
        self.assertEqual(report['counts']['files_quarantined'], 1)
        self.assertEqual((ledger, outputs), ([], {}))


if __name__ == '__main__': unittest.main()
