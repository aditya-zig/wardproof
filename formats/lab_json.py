"""Narrow release policy for structured diagnostic panels. No free text passes through."""
import json
import re


# Clinical vocabulary, not a list of known patients or filenames. Only emit a
# test if its name, LOINC and unit agree. Unknown panels are not partly exported.
ASSAYS = {
    ('haemoglobin', '718-7', 'g/dL'), ('hemoglobin', '718-7', 'g/dL'),
    ('random blood sugar', '2345-7', 'mg/dL'), ('glucose', '2345-7', 'mg/dL'),
    ('serum creatinine', '2160-0', 'mg/dL'), ('total wbc count', '6690-2', '/uL'),
    ('serum sodium', '2951-2', 'mmol/L'), ('hba1c', '4548-4', '%'),
    ('platelet count', '777-3', '/uL'), ('tsh', '3016-3', 'mIU/L'),
}


def require(condition):
    if not condition:
        raise ValueError('Unsupported lab report')


def fields(obj, names):
    require(type(obj) is dict and obj.keys() == set(names.split()))


def decimal_value(raw):
    # Do not silently round, change scale, or serialize nonstandard floats.
    require(re.fullmatch(r'-?[0-9]{1,7}\.[0-9]{1,6}', raw))
    value = float(raw)
    require(json.dumps(value) == raw)
    return value


def unique_object(pairs):
    result = dict(pairs)
    require(len(result) == len(pairs))
    return result


def reject_constant(_):
    raise ValueError('Nonstandard JSON number')


def lab_json(data):
    doc = json.loads(data.decode('utf-8-sig'), parse_float=decimal_value,
                     parse_constant=reject_constant, object_pairs_hook=unique_object)
    fields(doc, 'lab report_type patient referred_by collected panels remarks')
    require(doc['report_type'] == 'Diagnostic report')
    patient = doc['patient']
    fields(patient, 'name age sex phone hospital_uhid')
    count = sum(bool(patient[k]) for k in ('name', 'phone', 'hospital_uhid'))
    for k in ('name', 'phone', 'hospital_uhid', 'sex'):
        patient[k] = ''
    patient['age'] = None  # Unknown, not a fabricated numeric age.
    for k in ('lab', 'referred_by', 'collected', 'remarks'):
        doc[k] = ''
    require(type(doc['panels']) is list and doc['panels'])
    for panel in doc['panels']:
        fields(panel, 'name results')
        panel['name'] = 'Routine' if panel['name'] == 'Routine' else ''
        require(type(panel['results']) is list and panel['results'])
        for result in panel['results']:
            fields(result, 'test loinc unit value range')
            require(all(type(result[k]) is str for k in ('test', 'loinc', 'unit', 'range')))
            require(result['test'].isascii() and (result['test'].lower(), result['loinc'], result['unit']) in ASSAYS)
            require(type(result['value']) in (int, float) and abs(result['value']) <= 1_000_000)
            number = r'-?[0-9]{1,6}(?:\.[0-9]{1,4})?'
            require(re.fullmatch(f'{number} *[-–] *{number}', result['range']))
    return json.dumps(doc, ensure_ascii=False, allow_nan=False), [None], count
