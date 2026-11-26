"""Per-run, memory-only identity evidence. Never serialize indexes or raw keys."""
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import hmac
import re
import unicodedata


def token(secret, *parts):
    return hmac.new(secret, '\0'.join(parts).encode(), hashlib.sha256).hexdigest()[:24]


LETTERS = dict(zip('कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहळ', 'k kh g gh n ch chh j jh n t th d dh n t th d dh n p ph b bh m y r l v sh sh s h l'.split()))
VOWELS = dict(zip('अआइईउऊऋएऐओऔािीुूृेैोौंँः्', ['a','a','i','i','u','u','ri','e','ai','o','au','a','i','i','u','u','ri','e','ai','o','au','n','n','h','']))


def phonetic(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(LETTERS.get(c, VOWELS.get(c, c)) for c in text)
    return ' '.join(re.sub(r'(.)\1+',r'\1',re.sub('[aeiou]', '', w.replace('w','v'))) for w in re.findall('[a-z]+',text)).strip()


def uid(raw):
    if not isinstance(raw,str): return ''
    raw = raw.strip().upper()
    return raw if re.fullmatch(r'[A-Z]{2,12}[0-9]{0,4}[-/](?:[0-9]{1,4}[-/])?[0-9]{3,16}',raw) else ''


def parse_date(raw, us=False):
    if not isinstance(raw, str): return None
    raw = ''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in raw.strip())
    for fmt in ('%Y-%m-%d','%m/%d/%Y' if us else '%d/%m/%Y','%d-%m-%Y','%d.%m.%Y'):
        try: return datetime.strptime(raw,fmt).date()
        except (ValueError,TypeError): pass
    return None


class Index:
    def __init__(self, secret):
        self.secret=secret
        self.names=defaultdict(set); self.evidence=defaultdict(set); self.persons={}; self.conflicts=set()

    def add(self, key, name, village='', phone='', dob='', age='', us=False):
        key=uid(key); name=phonetic(name)
        if not key or not name: return
        mobile=re.sub(r'[^0-9]', '', phone)
        if len(mobile)==12 and mobile.startswith('91'): mobile=mobile[2:]
        born=parse_date(dob,us)
        strong=(mobile,born.isoformat()) if born and re.fullmatch('[6-9][0-9]{9}', mobile) else None
        self.evidence[key].add((name,strong))
        place=phonetic(village)
        if place and len(name.split())>=2: self.names[name,place].add(key)

    def finish(self):
        # Two independent structured identifiers plus compatible name before joining hospital IDs.
        for key, seen in self.evidence.items():
            names={n for n,_ in seen}; strong={s for _,s in seen if s}
            if len(names)>1 or len(strong)>1: self.conflicts.add(key); continue
            parts=('person',*next(iter(strong)),next(iter(names))) if strong else ('facility-id',key)
            self.persons[key]='PSN-'+token(self.secret,*parts)

    def lookup(self, raw='', name='', village=''):
        if raw:
            key=uid(raw)
            if not key or key in self.conflicts: return None
            candidate=phonetic(name)
            known=self.evidence.get(key)
            if candidate and known and all(candidate != registered for registered,_ in known): return None
            # Without a registry, accept only a recognized facility-specific namespace.
            return self.persons.get(key) or ('PSN-'+token(self.secret,'facility-id',key) if re.match(r'(JJH-|DHH[0-9]{4}-|SNJ/)',key) else None)
        candidates=self.names.get((phonetic(name),phonetic(village)),set())
        if len(candidates)==1: return self.persons.get(next(iter(candidates)))
        return None

    def shift(self, raw, patient, us=False):
        day=parse_date(raw,us)
        if not patient or not day: return ''
        seed=int(token(self.secret,'day',patient),16); offset=(1+seed%365)*(1 if seed%2 else -1)
        try: return (day+timedelta(days=offset)).isoformat()
        except OverflowError: return ''
