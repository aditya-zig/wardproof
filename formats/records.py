"""Small schema adapters. Never reflect arbitrary input keys, headers or narrative."""
import csv
import io
import json
import re

from clinical.text import DRUGS, DX, DURATION, FREQ, STRENGTH, structured_facts
from formats.lab_json import require
from identity.link import parse_date


def decode(data):
    if data.startswith((b'\xff\xfe',b'\xfe\xff')): return data.decode('utf-16')
    try: return data.decode('utf-8-sig')
    except UnicodeDecodeError: return data.decode('cp1252')


ALIASES={}
for field, names in {
    'key':'UHID|PatientID|Reg No|Patient ID|hospital_uhid|MRN|Hospital ID|मरीज़ आईडी', 'name':'Name|Patient Name|Naam|Patient Full Name|मरीज़ का नाम',
    'first':'FirstName', 'last':'LastName', 'village':'Village|Village/Mohalla|Gaon|City',
    'phone':'Mobile|Phone|Mobile No|Phone Number', 'dob':'DOB|Janm Tithi|DOB (MM/DD/YYYY)|Birth Date',
    'age':'Age|Umar', 'date':'Reg Date|Registration Date|Registered (MM/DD/YYYY)',
    'other':'Gender|Sex|Ling|Relation|Relative Name|Address|Tehsil|District|PIN|Aadhaar No|ABHA No|Guardian|Street|Zip|Email|Notes|Pita/Pati ka Naam|Pata|Jila|Pin Code|Aadhar',
}.items():
    for alias in names.split('|'): ALIASES[alias.casefold()]=field


def table(data,ext):
    sep='\t' if ext=='.tsv' else ','
    rows=csv.reader(io.StringIO(decode(data),newline=''),delimiter=sep,strict=True)
    header=next(rows,[]); require(header and len(header)==len(set(header)))
    cols=[ALIASES.get(h.strip().casefold()) for h in header]; unique=[c for c in cols if c!='other']
    require(None not in cols and 'key' in cols and len(unique)==len(set(unique)) and ('name' in cols or {'first','last'}<=set(cols)))
    result=[]
    for cells in rows:
        require(len(cells)==len(cols)); r=dict(zip(cols,cells)); result.append(r)
    return header,cols,result,sep


def registry_json(doc):
    require(isinstance(doc,dict) and doc.get('schema')=='dhh.registration.v3' and isinstance(doc.get('patients'),list))
    result=[]
    for p in doc['patients']:
        require(type(p) is dict)
        name=p['name'];address=p['address'];contact=p['contact']
        result.append({'key':p['uhid'],'first':name['first'],'last':name['last'],'local':name.get('local',''),
                       'village':address['village'],'dob':p['dob'],'phone':contact['mobile'] or '', 'date':p['registered_on']})
    return result


def seed(index, rows, us=False):
    for r in rows:
        name=r.get('name') or (r.get('first','')+' '+r.get('last','')); index.add(r['key'],name,r.get('village',''),r.get('phone',''),r.get('dob',''),us=us)


def registration(data,ext,index):
    header,cols,rows,sep=table(data,ext); us=any('MM/DD' in h for h in header)
    target=io.StringIO(newline=''); w=csv.writer(target,delimiter=sep); w.writerow(header)
    locs=[];detected=0
    for i,r in enumerate(rows):
        patient=index.lookup(r['key']);clean={'key':patient or '', 'date':index.shift(r.get('date',''),patient,us)}
        w.writerow([clean.get(c,'') for c in cols]);locs.append((f'row:{i}',patient));detected+=sum(bool(r.get(k)) for k in ('key','name','first','last','village','phone','dob'))
    return target.getvalue(),locs,detected


BILL_HEADER = 'bill_no uhid patient_name pmjay_id payer_pan policy_no package_code procedure admission_date discharge_date amount_inr status'.split()
BILL_PROCEDURES = {'SG039B':'Laparoscopic cholecystectomy','MG006A':'Caesarean section','SE001A':'Cataract surgery (phacoemulsification)',
                   'MG064A':'Haemodialysis session','SG001A':'Appendicectomy','SG050A':'Inguinal hernia repair',
                   'SG071A':'Whipple procedure (pancreaticoduodenectomy)','SN045A':'Deep brain stimulation'}


def billing(data,index):
    rows=csv.reader(io.StringIO(decode(data),newline=''),strict=True)
    header=next(rows,[]); require(header==BILL_HEADER)
    target=io.StringIO(newline=''); writer=csv.writer(target); writer.writerow(header)
    patients=[]; detected=0
    for i, cells in enumerate(rows):
        require(len(cells)==len(header)); raw=dict(zip(header,cells))
        code,procedure,state=(raw[k] for k in ('package_code','procedure','status'))
        require(BILL_PROCEDURES.get(code)==procedure and state in {'approved','pending','settled','rejected'})
        start,end=(parse_date(raw[k]) for k in ('admission_date','discharge_date'))
        require(start and end and start<=end)
        patient=index.lookup(raw['uhid'],raw['patient_name'])
        writer.writerow(['',patient or '', '', '', '', '', code,procedure,
                         index.shift(raw['admission_date'],patient),index.shift(raw['discharge_date'],patient),'',state])
        patients.append((f'row:{i}',patient)); detected+=sum(bool(v) for v in cells[:6])
    require(patients)
    return target.getvalue(),patients,detected


def blank_fields(obj, names):
    require(type(obj) is dict)
    return {k: '' if type(obj[k]) is str else None for k in names.split() if k in obj}


def registration_json(doc,index):
    rows=registry_json(doc); locs=[];patients=[]
    for i,(raw,r) in enumerate(zip(doc['patients'],rows,strict=True)):
        p=index.lookup(r['key']);locs.append((f'/patients/{i}',p))
        clean=blank_fields(raw,'gender dob age')
        for field,names in {'name':'first last local','guardian':'relation name','contact':'mobile email',
                            'address':'line village tehsil district pin','ids':'aadhar_no abha abha_address'}.items():
            if field in raw: clean[field]=blank_fields(raw[field],names)
        clean.update(uhid=p or '', registered_on=index.shift(r['date'],p));patients.append(clean)
    clean={'schema':'dhh.registration.v3','patients':patients,**blank_fields(doc,'exported_at')}
    if 'facility' in doc: clean['facility']=blank_fields(doc['facility'],'name type state')
    return json.dumps(clean),locs,sum(sum(bool(r.get(k)) for k in ('key','first','last','phone','dob','village')) for r in rows)


def outpatient(doc,index):
    require(type(doc) is dict and type(doc.get('visits')) is list and doc['visits']); result=[]; locs=[];detected=0
    for i,v in enumerate(doc['visits']):
        p=index.lookup(v['patient_ref']);locs.append((f'/visits/{i}',p));detected+=int(bool(v['patient_ref']))
        vit=v['vitals']; require(type(vit) is dict); safe={}
        for key,(lo,hi) in {'pulse':(10,300),'temp_f':(60,115),'spo2':(0,100),'weight_kg':(0,500)}.items():
            if key in vit and type(vit[key]) in (float,int) and lo<=vit[key]<=hi:safe[key]=vit[key]
        if 'bp' in vit and re.fullmatch('[0-9]{2,3}/[0-9]{2,3}',vit['bp']):safe['bp']=vit['bp']
        dx=[];rx=[]
        for d in v['diagnosis']:
            require(d['code'] in DX and DX[d['code']]==d['display']);dx.append({'code':d['code'],'display':d['display']})
        for m in v['rx']:
            require(m['drug'] in DRUGS and re.fullmatch(STRENGTH,m['strength']) and re.fullmatch(FREQ,m['frequency']) and re.fullmatch(DURATION,m['duration']))
            rx.append({k:m[k] for k in ('drug','strength','frequency','duration')})
        result.append({'visit_id':'','patient_ref':p or '', 'visit_date':index.shift(v['visit_date'],p), 'department':v.get('department') if v.get('department') in ('Medicine','Pulmonology','Cardiology','Paediatrics','Surgery','Orthopaedics','Nephrology','Neurology') else '', 'doctor':'',
                       'complaints':structured_facts(v.get('complaints','')), 'history':structured_facts(v.get('history','')), 'notes':structured_facts(v.get('notes','')),'vitals':safe,'diagnosis':dx,'rx':rx})
    clean={'visits':result}
    if '_export_meta' in doc: clean['_export_meta']=blank_fields(doc['_export_meta'],'system hospital exported_by generated_at source_path')
    return json.dumps(clean,ensure_ascii=False),locs,detected
