"""Positive projection of single-patient R4 document bundles with rewritten references."""
from datetime import datetime
from decimal import Decimal
import json
import re
from uuid import UUID

from clinical.text import DX, PROC, MED, STRENGTH, FREQ, DURATION
from formats.lab_json import ASSAYS, require, dumps
from identity.link import token

LOINC={code:(name,unit) for name,code,unit in sorted(ASSAYS,reverse=True)}
LOINC.update({'2345-7':('Random Blood Sugar','mg/dL'),'85354-9':('Blood pressure panel',None),'8480-6':('Systolic blood pressure','mmHg'),'8462-4':('Diastolic blood pressure','mmHg')})
PROCEDURES=PROC|{'Cataract surgery (phacoemulsification)','Deep brain stimulation','Whipple procedure (pancreaticoduodenectomy)'}
DOSAGE=STRENGTH+r' (?:OD|BD|SOS)(?: x '+DURATION+r')? \('+FREQ+r'\)(?: (?:before breakfast|after lunch|after food|in 1 litre water|when breathless|morning|empty stomach|at night|after meals|if fever|x '+DURATION+r'))?'


def bundle(doc,index,source):
    require(doc.get('type')=='document' and doc['entry'][0]['resource']['resourceType']=='Composition')
    items={}
    for e in doc['entry']:
        url=e['fullUrl']; require(re.fullmatch(r'urn:uuid:[0-9a-f-]{36}',url) and url not in items)
        require(e['resource']['id']==str(UUID(url[9:])))
        items[url]=e['resource']
    people=[(u,r) for u,r in items.items() if r['resourceType']=='Patient'];require(len(people)==1)
    require(sum(r['resourceType']=='Encounter' for r in items.values()) <= 1)
    pu,person=people[0]
    candidates={p for i in person.get('identifier',[]) if (p:=index.lookup(i.get('value','')))}
    patient=next(iter(candidates)) if len(candidates)==1 else None
    ids={u:'urn:uuid:'+str(UUID(token(index.secret,'fhir',source,u)+'00000000',version=4)) for u,r in items.items() if r['resourceType']!='DocumentReference'}

    def fixed(value, allowed):
        require(value in allowed)
        return value

    def ref(r, targets=None):
        url=r['reference']
        if targets: require(items[url]['resourceType'] in targets)
        return {'reference':ids[url]}
    def subject(r):
        require(r['subject']['reference']==pu)
        return ref(r['subject'])
    def refs(rs): return [ref(r) for r in rs if r['reference'] in ids]
    def shifted(raw):
        require(type(raw) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:[+-][0-9]{2}:[0-9]{2}|Z))?',raw))
        datetime.fromisoformat(raw)
        # R4 document bundles require a composition date. For an unresolved patient,
        # use a keyed per-document offset; do n