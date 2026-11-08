"""Explicit, offline migration of processed cases; never edits historical runs.

Run with --apply to replace the processed directory, retaining a full backup.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import uuid


def clean_case(case):
    profile = case['profile']
    bad = {n['evidence_id'] for n in profile['evidence_nodes']
           if not any(c.isalnum() for c in n['source_text'])}
    removed = [n for n in profile['evidence_nodes'] if n['evidence_id'] in bad]
    profile['evidence_nodes'] = [n for n in profile['evidence_nodes'] if n['evidence_id'] not in bad]
    bad_items = {d['item_id'] for d in profile['disclosure_items']
                 if not any(c.isalnum() for c in d['content'])}
    profile['disclosure_items'] = [d for d in profile['disclosure_items'] if d['item_id'] not in bad_items]
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'source_ids', 'source_fact_ids', 'evidence_ids', 'depends_on'} and isinstance(child, list):
                    value[key] = [i for i in child if i not in bad | bad_items]
                else:
                    visit(child)
        elif isinstance(value, list):
            value[:] = [v for v in value if not (isinstance(v, dict) and 'text' in v
                        and 'source_ids' in v and not any(c.isalnum() for c in v['text']))]
            for child in value:
                visit(child)
    visit(profile)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / 'data/processed/psycheval'
    audit = {}
    for line in (source / 'all.jsonl').open(encoding='utf-8'):
        case = json.loads(line)
        removed = clean_case(case)
        if removed:
            audit[case['case_id']] = removed
    print(json.dumps({'affected_cases': len(audit), 'removed_nodes': sum(map(len, audit.values()))}))
    if not args.apply or not audit:
        return
    target = root / 'runs/runtime' / ('punctuation-migration-' + uuid.uuid4().hex[:12])
    target.mkdir(parents=True)
    stage = source.parent / ('.punctuation-staging-' + uuid.uuid4().hex[:12])
    shutil.copytree(source, stage)
    hashes = {}
    for path in stage.rglob('*.jsonl'):
        original = source / path.relative_to(stage)
        hashes[str(path.relative_to(stage))] = hashlib.sha256(original.read_bytes()).hexdigest()
        with original.open(encoding='utf-8') as src, path.open('w', encoding='utf-8', newline='\n') as dst:
            for line in src:
                if line.strip():
                    case = json.loads(line)
                    if 'profile' in case and 'evidence_nodes' in case['profile']:
                        clean_case(case)
                    dst.write(json.dumps(case, ensure_ascii=False) + '\n')
    report = {'policy': 'remove-punctuation-only-v1', 'source_sha256': hashes, 'removed': audit}
    (target / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (stage / 'punctuation_cleanup.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    backup = target / 'processed-backup'
    source.rename(backup)
    try:
        stage.rename(source)
    except BaseException:
        backup.rename(source)
        raise
    print(str(target))


if __name__ == '__main__':
    main()
