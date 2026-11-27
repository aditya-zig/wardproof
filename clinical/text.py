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
    r'(