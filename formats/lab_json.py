"""Narrow release policy for structured diagnostic panels. No free text passes through."""
import csv
import io
import json
import re
from formats.privacy import age_band, gender_category
from decimal import Decimal, InvalidOperation


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


class JsonDecimal(Decimal):
    """A Decimal that also remembers the exact JSON token it came from."""
    def __new__(cls, raw):
        value = super().__new__(cls, raw)
        value.raw = raw
        return value


def decimal_value(raw):
    # JSON decimals and exponent notation remain exact; never round through float.
    require(re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', raw))
    try:
        value = JsonDecimal(raw)
    except InvalidOperation as exc:
        raise ValueError('Invalid JSON number') from exc
    require(value.is_finite() and abs(value.adjusted()) <= 308)
    return value


def dumps(value, **kwargs):
    """Serialize JsonDecimal tokens as JSON numbers without changing their spelling."""
    strings = set()
    def scan(item):
        if isinstance(item, str): strings.add(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                if isinstance(key, str): strings.add(key)
                scan(child)
        elif isinstance(item, (list, tuple)):
            for child in item: scan(child)
    scan(value)
    markers = {}
    def convert(item):
        if isinstance(item, JsonDecimal):
            i = len(markers)
            marker = f'__WARDPROOF_JSON_NUMBER_{i:08d}__'
            while marker in strings:
                i += 1; marker = f'__WARDPROOF_JSON_NUMBER_{i:08d}__'
            strings.add(marker); markers[marker] = item.raw
            return marker
        if isinstance(item, dict): return {key: convert(child) for key, child in item.items()}
        if isinstance(item, list): return [convert(child) 