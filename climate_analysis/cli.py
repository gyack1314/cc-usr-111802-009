"""从本地合成资料形成已知时间的指标报告，或登记断流解释版次。"""
import argparse
import json
from pathlib import Path

from .evidence import connect, receive
from .report import generate, difference
from .attribution import explain, ATTRIBUTION_KINDS
from .explanation import register_published, revise, history


def _load(db, path):
    data = json.loads(Path(path).read_text(encoding='utf8'))
    for doc in data['documents']:
        receive(db, doc)
    return data


def _inspect(db, data):
    a, b = [generate(db, t) for t in data['known_at']]
    return {'before': a, 'after': b, 'change': difference(a, b)}


def _run_explanations(db, data):
    """按版次顺序登记：无 supersedes 的为已公布原版，其余为修订版。"""
    entries = sorted(data.get('explanations', []),
                     key=lambda e: e['published_at'])
    saved = []
    for entry in entries:
        common = dict(explanation_id=entry['explanation_id'],
                      version=entry['version'], known_at=entry['known_at'],
                      period=entry['period'], region=entry['region'],
                      published_at=entry['published_at'],
                      narrative=entry['narrative'])
        if entry.get('supersedes'):
            saved.append(revise(db, supersedes=entry['supersedes'], **common))
        else:
            saved.append(register_published(db, **common))
    return saved


def _explain(db, data):
    versions = _run_explanations(db, data)
    latest_at = data['known_at'][-1]
    regions = set()
    for kind in ATTRIBUTION_KINDS + ('observation',):
        for (payload_json,) in db.execute(
                'SELECT payload_json FROM observations WHERE kind=?', (kind,)):
            regions.add(json.loads(payload_json)['region'])
    reach_attributions = [
        explain(db, latest_at, region, '2025水文年')
        for region in sorted(regions)]
    grouped = {}
    for entry in versions:
        grouped.setdefault(entry['explanation_id'], [])
        grouped[entry['explanation_id']].append(
            history(db, entry['explanation_id']))
    explanation_chains = {
        key: chain[0] for key, chain in grouped.items()}
    return {
        'known_at': data['known_at'],
        'reach_attributions': reach_attributions,
        'explanation_versions': versions,
        'explanation_chains': explanation_chains,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['inspect', 'explain'])
    p.add_argument('input')
    args = p.parse_args()
    db = connect(':memory:')
    try:
        data = _load(db, args.input)
        result = (_inspect(db, data) if args.command == 'inspect'
                  else _explain(db, data))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    main()
