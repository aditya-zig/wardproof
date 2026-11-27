"""Narrow release policy for structured diagnostic panels. No free text passes through."""
import csv
import io
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


def parse(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = data.decode('utf-16')
    else:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('cp1252')
    return json.loads(text, parse_float=decimal_value,
                      parse_constant=reject_constant, object_pairs_hook=unique_object)


def reference_ranges(text):
    header = ['test', 'loinc', 'unit', 'reference_range']
    rows = csv.reader(io.StringIO(text), strict=True)
    require(next(rows, None) == header)
    target = io.StringIO(newline='')
    writer = csv.writer(target)
    writer.writerow(header)
    count = 0
    number = r'-?[0-9]{1,6}(?:\.[0-9]{1,4})?'
    for row in rows:
        require(len(row) == 4)
        test, code, unit, interval = row
        require(test.isascii() and (test.lower(), code, unit) in ASSAYS)
        require(re.fullmatch(f'{number} *[-–] *{number}', interval))
        writer.writerow(row)
        count += 1
    require(count)
    return target.getvalue(), [], 0


def measurement(result):
    require(all(type(result[k]) is str for k in ('test', 'loinc', 'unit')))
    require(result['test'].isascii() and (result['test'].lower(), result['loinc'], result['unit']) in ASSAYS)
    require(type(result['value']) in (int, float) and abs(result['value']) <= 1_000_000)


def bulk_lab(doc, index):
    fields(doc, 'export results')
    require(doc['export'] == 'LIMS bulk extract' and type(doc['results']) is list and doc['results'])
    patients, detected = [], 0
    for i, row in enumerate(doc['results']):
        fields(row, 'patient_name uhid test loinc value unit date')
        measurement(row)
        require(all(type(row[k]) is str for k in ('patient_name', 'uhid', 'date')))
        patient = index.lookup(row['uhid'], row['patient_name'])
        patients.append((f'/results/{i}', patient))
        detected += bool(row['patient_name']) + bool(row['uhid'])
        row.update(patient_name='', uhid=patient or '', date=index.shift(row['date'], patient))
    return json.dumps(doc, ensure_ascii=False, allow_nan=False), patients, detected


def lab_json(doc, index):
    if isinstance(doc, dict) and 'export' in doc:
        return bulk_lab(doc, index)
    fields(doc, 'lab report_type patient referred_by collected panels remarks')
    require(doc['report_type'] == 'Diagnostic report')
    patient = doc['patient']
    fields(patient, 'name age sex phone hospital_uhid')
    count = sum(bool(patient[k]) for k in ('name', 'phone', 'hospital_uhid'))
    ref = index.lookup(patient['hospital_uhid'], patient['name'])
    for k in ('name', 'phone', 'hospital_uhid', 'sex'):
        patient[k] = ''
    patient['hospital_uhid'] = ref or ''
    doc['collected'] = index.shift(str(doc['collected'])[:10], ref)
    patient['age'] = None  # Unknown, not a fabricated numeric age.
    for k in ('lab', 'referred_by', 'remarks'):
        doc[k] = ''
    require(type(doc['panels']) is list and doc['panels'])
    for panel in doc['panels']:
        fields(panel, 'name results')
        panel['name'] = 'Routine' if panel['name'] == 'Routine' else ''
        require(type(panel['results']) is list and panel['results'])
        for result in panel['results']:
            fields(result, 'test loinc unit value range')
            measurement(result)
            require(type(result['range']) is str)
            number = r'-?[0-9]{1,6}(?:\.[0-9]{1,4})?'
            require(re.fullmatch(f'{number} *[-–] *{number}', result['range']))
    return json.dumps(doc, ensure_ascii=False, allow_nan=False), [('doc', ref)], count
