"""Positive selection: reconstruct clinical facts, never pass through a note body."""
import re

from identity.link import parse_date

DRUGS = ('Paracetamol','Ramipril','Dolo','Amlodipine','Artesunate','Atorvastatin','Azithromycin','Ceftriaxone','Doxycycline','Ferrous sulphate + Folic acid','Glimepiride','Levothyroxine','Metformin','ORS','Pantoprazole','Rifampicin + Isoniazid','Salbutamol inhaler','Telmisartan','Insulin Glargine','Amoxicillin','Ibuprofen','Aspirin')
DX = {'A01.0':'Typhoid fever','A09':'Infectious gastroenteritis and colitis, unspecified','A15.0':'Tuberculosis of lung','A82.9':'Rabies, unspecified','A97.9':'Dengue, unspecified','B54':'Unspecified malaria','B55.0':'Visceral leishmaniasis (kala-azar)','D64.9':'Anaemia, unspecified','E03.9':'Hypothyroidism, unspecified','E11.9':'Type 2 diabetes mellitus without complications','E27.1':"Addison's disease",'E83.0':"Wilson's disease",'G51.0':"Bell's palsy",'I10':'Essential (primary) hypertension','I25.1':'Atherosclerotic heart disease','J18.9':'Pneumonia, unspecified organism','J44.9':'Chronic obstructive pulmonary disease, unspecified','J45.9':'Asthma, unspecified','K50.9':"Crohn's disease, unspecified",'N18.3':'Chronic kidney disease, stage 3','N39.0':'Urinary tract infection, site not specified','G20':"Parkinson's disease"}
PROC = {'Appendicectomy','Inguinal hernia repair','Laparoscopic cholecystectomy','Normal vaginal delivery','Caesarean section','Cataract extraction'}
STRENGTH=r'[0-9]{1,3}(?:\.[0-9]{1,2})? *(?:mcg|mg|g|mL|units|sachet)(?: *\+ *[0-9]{1,3}(?:\.[0-9]{1,2})? *(?:mcg|mg|g))?'
FREQ=r'(?:[012]-[012]-[012]|[12] puffs|IV|OD|BD|TDS|SOS|after each loose stool)'
DURATION=r'[0-9]{1,2} (?:days?|wks?|weeks?|months?)'
DRUG='(?:'+'|'.join(re.escape(x) for x in DRUGS)+')'
MED=re.compile(r'(?<!\w)(?:(?:Tab|Cap|Inj|Inh|Syp)\.? )?'+DRUG+' '+STRENGTH+r'(?: '+FREQ+r')?(?: x '+DURATION+r')?(?!\w)', re.I|re.ASCII)
FACT=re.compile(r'(?<!\w)(?:C/O:? (?:fever|cough|headache|pain abdomen|breathlessness)(?: (?:x|for) [0-9]{1,2} days?)?|BP [0-9]{2,3}/[0-9]{2,3}(?: mmHg)?|pulse [0-9]{2,3}(?:/min)?|SpO2 [0-9]{2,3}%|Temp [0-9]{2,3}(?:\.[0-9])? F|RBS [0-9]{2,3} mg/dL|Bukhar [0-9]{2,3} F|[0-9]{1,2} दिन से बुखार|(?:Haemoglobin|Random Blood Sugar|Serum Creatinine) [0-9]{1,3}(?:\.[0-9]{1,2})? (?:g/dL|mg/dL))(?!\w)',re.I|re.ASCII)
DIAG=re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(label)+r'(?: \('+re.escape(code)+r'\))?' for code,label in DX.items())+r')(?!\w)',re.I|re.ASCII)
# Preserve recognized phrases with their context, never arbitrary text around them.
CLINICAL_FIELD = re.compile(
    r'(?:C/O:? (?:generali[sz]ed weakness|headache and giddiness|cough with expectoration|loose stools|'
    r'fever|cough|headache|pain abdomen|burning micturition|breathlessness(?: on exertion)?)'
    r' (?:x|for) [0-9]{1,2} (?:days?|weeks?)'
    r'|[0-9०-९]{1,2} (?:दिन|हफ़्ते|हफ्ते) से (?:पेट दर्द|चक्कर आना|बुखार|खांसी)'
    r'|[0-9]{1,2} (?:din|hafte) se (?:bukhar|khansi|kamzori|chakkar aana|pet mein dard|saans phoolna)'
    r'|(?:bukhar|khansi|kamzori|chakkar aana|pet mein dard|saans phoolna) [0-9]{1,2} (?:din|hafte) se'
    r'|(?:K/C/O DM2 x|H/O (?:TB|snake bite)) [0-9]{1,2} yrs(?: back(?:, completed ATT)?)?'
    r'|K/C/O (?:HTN on treatment|hypothyroidism)|No H/O DM/HTN'
    r'|HbA1c [0-9]{1,2}(?:\.[0-9]{1,2})? %)', re.I | re.ASCII,
)


HINDI_DX = {
    'पेशाब में संक्रमण':'N39.0', 'फेफड़ों की टीबी':'A15.0', 'किडनी की पुरानी बीमारी':'N18.3',
    'सीओपीडी':'J44.9', 'उच्च रक्तचाप':'I10', 'दस्त और उल्टी':'A09', 'निमोनिया':'J18.9',
    'मलेरिया':'B54', 'टाइप 2 डायबिटीज़':'E11.9', 'काला-अज़ार':'B55.0', 'दमा':'J45.9', 'रेबीज़':'A82.9',
}
HINDI_DIAG = re.compile('|'.join(re.escape(f'{label} ({code})') for label, code in HINDI_DX.items()))
DOLO = re.compile(r'(?<!\w)Dolo (?:500|650) '+FREQ+r' x '+DURATION+r'(?!\w)', re.I)
CHAT_LAB = re.compile(r'(?:Haemoglobin [0-9]{1,3}(?:\.[0-9]{1,2})? g/dL|(?:Random Blood Sugar|Serum Creatinine) [0-9]{1,3}(?:\.[0-9]{1,2})? mg/dL|HbA1c [0-9]{1,3}(?:\.[0-9]{1,2})? %)')
PRIVATE_LINE = re.compile(r'^\s*(?:Patient Name|Name|नाम|मरीज़ का नाम|Address|पता|Mobile|मोबाइल|Attendant|पति का नाम|पिता का नाम|DOB)\s*:', re.I)

CONTEXT = re.compile(r'\b(?:no|not|denies|denied|negative for|without|allerg\w*|family history|rule[ -]out|hold|stop|discontinue\w*)\b|नहीं|इंकार|एलर्जी', re.I)


def facts(text):
    spans=[]
    for line in text.splitlines():
        if PRIVATE_LINE.match(line) or CONTEXT.search(line): continue
        matches=[*MED.finditer(line), *FACT.finditer(line), *DIAG.finditer(line), *HINDI_DIAG.finditer(line)]
        spans.extend(m.group() for m in sorted(matches,key=lambda m:m.start()))
    return '\n'.join(spans)


def structured_facts(text):
    return text if CLINICAL_FIELD.fullmatch(text) else facts(text)


def forwarded_lab(text):
    if not re.search(r'(?im)^Forwarded\s*\n\*[^\n]+\*\s*\nReport of [^\n]+', text): raise ValueError
    values=[field.strip() for line in text.splitlines() if '|' in line for field in line.split('|') if CHAT_LAB.fullmatch(field.strip())]
    if not values: raise ValueError
    doses = [m.group() for line in text.splitlines() if not CONTEXT.search(line) and not re.match(r'^Report of\b', line, re.I) for m in DOLO.finditer(line)]
    return '\n'.join([*values, *doses, '']), [('doc',None)], 1


def capture(pattern,text):
    m=re.search(pattern,text,re.I|re.M); return m[1].strip() if m else ''


def note(text,index):
    if re.match(r'(?i)^Discharge note[ \t]*\r?\n', text):
        clinical=facts('\n'.join(line for line in text.splitlines() if line.startswith('Treated for ')))
        if not clinical: raise ValueError
        # No verified identifier or full date in this layout; never infer either.
        identifiers=2 if re.search(r'(?im)^.+, (?:W/o|S/o|D/o|H/o) .+, discharged\b', text) else 0
        return clinical+'\n', [('doc',None)], identifiers
    if not re.search(r'(?im)^(?:DISCHARGE SUMMARY|डिस्चार्ज सारांश|NURSING NOTES\b|.*(?:OPD Prescription|ओपीडी पर्चा)$|Rx\s*$)',text):
        return forwarded_lab(text)
    key=capture(r'(?<!\w)(?:UHID|Reg No|पंजीकरण सं\.):[ \t]*([^\s]+)',text)
    name=capture(r'^(?:नाम|Name|Patient Name|मरीज़ का नाम):[ \t]*(.+?)(?:\s{2,}|$)',text)
    village=capture(r'^(?:ग्राम|Village):[ \t]*([^\n\r]+)',text)
    patient=index.lookup(key,name,village)
    clinical=facts(text)
    if not clinical: raise ValueError
    lines=['Patient: '+patient] if patient else []
    dates = {label: capture('^(?:'+pattern+r'):[ \t]*([\d./-]+)',text) for label,pattern in (
        ('Date of Admission','Date of Admission|भर्ती की तारीख'), ('Date of Discharge','Date of Discharge|छुट्टी की तारीख'),
        ('Date','Date|तारीख'))}
    us='arogya' in text.splitlines()[0].casefold()
    start,end=dates['Date of Admission'],dates['Date of Discharge']
    if start and end:
        for mode in (us,not us):
            a,b=parse_date(start,mode),parse_date(end,mode)
            if a and b and a<=b:
                us=mode
                break
        else:
            dates['Date of Admission']=dates['Date of Discharge']=''
    for label,raw in dates.items():
        shifted=index.shift(raw,patient,us)
        if shifted: lines.append(label+': '+shifted)
    return '\n'.join([*lines,clinical,'']), [('doc',patient)], sum(bool(x) for x in (name,village,key))
