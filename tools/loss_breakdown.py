"""Aggregate the organizer practice check's retention probes, including quarantine."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import runpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    checker = runpy.run_path(str(args.kit / 'check_dev.py'))
    norm, read_text = checker['norm'], checker['read_text']
    truth = json.loads((args.kit / 'dev/truth/truth.json').read_text())
    report = json.loads((args.release / 'report.json').read_text())
    outputs = {f['input_sha256']: f['output'] for f in report['files']}
    by_kind = defaultdict(Counter)
    for source, file in truth['files'].items():
        dest = outputs[file['sha256']]
        text = norm(read_text(args.release / dest)) if dest else ''
        for unit in file['units'].values():
            for probe in unit.get('preserve', []):
                state = 'withheld' if not dest else 'kept' if norm(probe['text']) in text else 'missing'
                by_kind[source.split('/')[0], probe['kind']][state] += 1
    print(f'{"Format / clinical field":32} {"Kept":>6} {"Missing":>8} {"Withheld":>9}')
    for (group, kind), count in sorted(by_kind.items(), key=lambda pair: -(pair[1]['missing'] + pair[1]['withheld'])):
        print(f'{group + " / " + kind:32} {count["kept"]:6} {count["missing"]:8} {count["withheld"]:9}')


if __name__ == '__main__':
    main()
