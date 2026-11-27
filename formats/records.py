"""Small schema adapters. Never reflect arbitrary input keys, headers or narrative."""
import csv
import io
import json
import re

from clinical.text import DRUGS, DX, DURATION, FREQ, STRENGTH, structured_facts, clinician_name
from formats.lab_json import require, dumps, JsonDecimal
from formats.privacy import age_band, gender_category, district_label
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
    'age':'Age|Umar', 'gender':'Gender|Sex|Ling', 'district':'District|Jila',
    'date':'Reg Date|Registration Date|Registered (MM/DD/YYYY)',
    'other':'Relation|Relative Name|Address|Tehsil|PIN|Aadhaar No|ABHA No|Guardian|Street|Zip|Email|Notes|Pita/Pati ka Naam|Pata|Pin Code|Aadhar',
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
    require(doc.get('resourceType') != 'Bundle' and 'visits' not in doc)
    require('facility' not in doc or type(doc['facility']) is dict)
    result=[]
    for p in doc['patients']:
        require(type(p) is dict and all(type(p[k]) is dict for k in ('name','guardian','contact','address','ids') if k in p))
        name=p['name'];address=p['address'];contact=p['contact']
        result.append({'key':p['uhid'],'first':name['first'],'last':name['last'],'local':nam