"""Positive projection of single-patient R4 document bundles with rewritten references."""
from datetime import datetime
import json
import re
from uuid import UUID

from clinical.text import DX, PROC, MED, STRENGTH, FREQ, DURATION
from formats.lab_json import ASSAYS, require
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
        # use a keyed per-document offset; do not link that offset to another document.
        day=index.shift(raw[:10],patient or ids[pu]); require(day)
        return day+raw[10:]

    def observation(r,component=False):
        c,=r['code']['coding']; code=c['code'];name,unit=LOINC[code];display=c.get('display',name)
        require(type(display) is str and display.isascii() and display.lower()==name.lower())
        out={'code':{'coding':[{'system':'http://loinc.org','code':code,'display':display}]}}
        if r['code'].get('text','').lower()==name.lower():out['code']['text']=r['code']['text']
        if unit:
            q=r['valueQuantity'];require(q['unit']==unit and type(q['value']) in (float,int) and abs(q['value'])<=1_000_000)
            out['valueQuantity']={'value':q['value'],'unit':unit}
            if unit=='mmHg':out['valueQuantity'].update(system='http://unitsofmeasure.org',code='mm[Hg]')
        else:
            require(not component and code=='85354-9');out['component']=[observation(v,True) for v in r['component']]
        return out

    entries=[]
    for u,r in items.items():
        if u not in ids: continue
        t=r['resourceType'];s={'resourceType':t,'id':ids[u][9:]}
        if t=='Composition':
            coding, = r['type']['coding']
            require(coding['system']=='http://snomed.info/sct' and coding['code']=='373942005')
            s.update(status=fixed(r['status'], ('preliminary','final','amended','entered-in-error')),type={'coding':[{'system':'http://snomed.info/sct','code':'373942005','display':'Discharge summary'}]},subject=subject(r),date=shifted(r['date']),author=[ref(v, ('Practitioner','Patient','Organization')) for v in r['author']],title='Discharge Summary')
            require(s['author']);s['section']=[{'entry': found} for section in r.get('section',[]) if (found:=refs(section.get('entry',[])))]
            if 'encounter' in r:s['encounter']=ref(r['encounter'], ('Encounter',))
        elif t=='Patient':
            if patient: s['identifier']=[{'system':'urn:wardproof:patient','value':patient}]
        elif t in ('Practitioner','Organization'):
            if t=='Organization':s['name']='Withheld organization'
        elif t=='Encounter':
            cls=fixed(r['class']['code'], ('IMP','AMB','EMER','OBSENC'))
            s.update(status=fixed(r['status'], ('in-progress','finished','cancelled')),subject=subject(r),**{'class':{'system':'http://terminology.hl7.org/CodeSystem/v3-ActCode','code':cls}})
            if 'period' in r:s['period']={k:shifted(r['period'][k]) for k in ('start','end') if k in r['period']}
            if 'serviceProvider' in r:s['serviceProvider']=ref(r['serviceProvider'], ('Organization',))
        elif t=='Observation':
            s.update(observation(r),status=fixed(r['status'], ('preliminary','final','amended','corrected')),subject=subject(r))
            if 'effectiveDateTime' in r:s['effectiveDateTime']=shifted(r['effectiveDateTime'])
        elif t=='Condition':
            c,=r['code']['coding'];dx=DX[c['code']]; require(c['display']==dx)
            s.update(subject=subject(r),code={'coding':[{'system':'http://hl7.org/fhir/sid/icd-10','code':c['code'],'display':dx}],'text':dx})
            if 'clinicalStatus' in r:
                state=fixed(r['clinicalStatus']['coding'][0]['code'], ('active','recurrence','relapse','inactive','remission','resolved'))
                s['clinicalStatus']={'coding':[{'system':'http://terminology.hl7.org/CodeSystem/condition-clinical','code':state}]}
            if 'verificationStatus' in r:
                coding, = r['verificationStatus']['coding']
                state=fixed(coding['code'], ('unconfirmed','provisional','differential','confirmed','refuted','entered-in-error'))
                s['verificationStatus']={'coding':[{'system':'http://terminology.hl7.org/CodeSystem/condition-ver-status','code':state}]}
                if state=='entered-in-error': require('clinicalStatus' not in s)
            if 'encounter' in r:s['encounter']=ref(r['encounter'], ('Encounter',))
            if 'recordedDate' in r:s['recordedDate']=shifted(r['recordedDate'])
        elif t=='MedicationRequest':
            drug=r['medicationCodeableConcept']['text'];require(MED.fullmatch(drug))
            s.update(status=fixed(r['status'], ('active','completed','stopped','cancelled','on-hold','draft')),intent=fixed(r['intent'], ('proposal','plan','order')),medicationCodeableConcept={'text':drug},subject=subject(r))
            s['dosageInstruction']=[]
            for d in r.get('dosageInstruction',[]):
                text=d['text'];require(re.fullmatch(DOSAGE,text));s['dosageInstruction'].append({'text':text})
            if not s['dosageInstruction']:del s['dosageInstruction']
            if 'authoredOn' in r:s['authoredOn']=shifted(r['authoredOn'])
        elif t=='Procedure':
            procedure=r['code']['text'];require(procedure in PROCEDURES)
            s.update(status=fixed(r['status'], ('in-progress','completed','stopped','not-done')),subject=subject(r),code={'text':procedure})
            if 'performedDateTime' in r:s['performedDateTime']=shifted(r['performedDateTime'])
        else:raise ValueError('Unsupported R4 resource')
        entries.append({'fullUrl':ids[u],'resource':s})
    meta='bundle-'+token(index.secret,'bundle',source)
    stamp=shifted(doc.get('timestamp',doc['entry'][0]['resource']['date']))
    clean={'resourceType':'Bundle','id':meta,'type':'document','identifier':{'system':'urn:wardproof:bundle','value':meta},'timestamp':(stamp if 'T' in stamp else stamp+'T00:00:00Z'),'entry':entries}
    return json.dumps(clean),[('doc',patient)],sum(bool(person.get(k)) for k in ('identifier','name','telecom','birthDate','address'))
