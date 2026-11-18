"""断流解释的版次登记与修订对照。

已向公众公布的解释以原叙述、原依据指纹原样保存，不被后续补报覆盖；
修订版必须基于新已知时点的归因结果重新核对，并逐条说明：
哪条归因因取水补报或融水重算而改变、补水承诺是否受影响。
任何把单一变化当作唯一原因的叙述在登记处直接拒绝。
"""
import hashlib
import json

from .attribution import explain, evaluate_claim, SOLE_CAUSE_MARKERS


def _fingerprint(payload):
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()


def _component_index(attribution):
    return {c['metric']: c for c in attribution.get('components', [])}


def _basis(attribution):
    """抽取该解释实际依赖的全部来源指纹。"""
    return sorted({sha for c in attribution.get('components', [])
                   for sha in c.get('sources', [])}
                  | set(attribution.get('sources', [])))


def register_published(db, explanation_id, version, known_at, period, region,
                       published_at, narrative):
    """登记一份已经公布的解释；历史版本内容不得改写。"""
    attribution = explain(db, known_at, region, period)
    evaluation = evaluate_claim(attribution, narrative)
    detail = {'attribution': attribution, 'claim_evaluation': evaluation}
    basis = _basis(attribution)
    fingerprint = _fingerprint(
        {'id': explanation_id, 'version': version, 'known_at': known_at,
         'period': period, 'region': region, 'narrative': narrative,
         'detail': detail, 'basis': basis})
    with db:
        db.execute(
            'INSERT OR IGNORE INTO explanations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (explanation_id, version, known_at, period, region, published_at,
             None, narrative,
             json.dumps(detail, ensure_ascii=False, sort_keys=True),
             json.dumps(basis, ensure_ascii=False), fingerprint))
    return get_explanation(db, explanation_id, version)


def revise(db, explanation_id, version, known_at, period, region,
           published_at, narrative, supersedes):
    """基于补报/重算后的证据生成修订版；拒绝唯一原因表述。"""
    if any(marker in narrative for marker in SOLE_CAUSE_MARKERS):
        raise ValueError('修订解释不得把任何单一变化表述为唯一原因')
    prior = get_explanation(db, explanation_id, supersedes)
    if prior is None:
        raise ValueError('被替代的解释版本不存在，修订链断裂')
    attribution = explain(db, known_at, region, period)
    old_index = _component_index(prior['detail']['attribution'])
    new_index = _component_index(attribution)
    changes = []
    for metric in sorted(set(old_index) | set(new_index)):
        old_c, new_c = old_index.get(metric), new_index.get(metric)
        if old_c is None:
            changes.append({'metric': metric, 'change': '新增归因项',
                            'new_status': new_c['status'],
                            'new_explained_delta': new_c['explained_delta']})
            continue
        if new_c is None:
            changes.append({'metric': metric, 'change': '归因项消失',
                            'old_status': old_c['status']})
            continue
        if (old_c.get('explained_delta') != new_c.get('explained_delta')
                or old_c.get('status') != new_c.get('status')):
            entry = {'metric': metric, 'label': new_c['label'],
                     'change': '归因变化',
                     'old_status': old_c.get('status'),
                     'new_status': new_c.get('status'),
                     'old_explained_delta': old_c.get('explained_delta'),
                     'new_explained_delta': new_c.get('explained_delta')}
            if metric == 'abstraction':
                entry['driver'] = '取水记录补报或许可执行更新'
            elif metric == 'glacier_melt':
                entry['driver'] = '融水估计重算或冰川质量平衡更新'
            else:
                entry['driver'] = '实测资料更新'
            changes.append(entry)

    old_gap = prior['detail']['attribution'].get('gap_to_target')
    new_gap = attribution.get('gap_to_target')
    commitment = {
        'action': '补水',
        'prior_gap_to_target': old_gap,
        'revised_gap_to_target': new_gap,
        'commitment_affected': not (
            (old_gap is None or old_gap < 0) and (new_gap is None or new_gap < 0)
        ),
        'note': ('缺口仍存在，补水承诺维持，规模按修订后缺口复核'
                 if new_gap is not None and new_gap < 0
                 else '缺口状态变化，补水承诺需按规则重新评估'),
    }
    detail = {
        'attribution': attribution,
        'claim_evaluation': evaluate_claim(attribution, narrative),
        'attribution_changes': changes,
        'commitment_assessment': commitment,
        'preserved_prior_fingerprint': prior['fingerprint'],
        'preserved_prior_narrative': prior['narrative'],
    }
    basis = _basis(attribution)
    fingerprint = _fingerprint(
        {'id': explanation_id, 'version': version, 'known_at': known_at,
         'period': period, 'region': region, 'narrative': narrative,
         'detail': detail, 'basis': basis, 'supersedes': supersedes})
    with db:
        db.execute(
            'INSERT OR IGNORE INTO explanations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (explanation_id, version, known_at, period, region,
             published_at, supersedes, narrative,
             json.dumps(detail, ensure_ascii=False, sort_keys=True),
             json.dumps(basis, ensure_ascii=False), fingerprint))
    return get_explanation(db, explanation_id, version)


def get_explanation(db, explanation_id, version):
    row = db.execute(
        'SELECT explanation_id,version,known_at,period,region,published_at,'
        'supersedes,narrative,detail_json,basis_json,fingerprint '
        'FROM explanations WHERE explanation_id=? AND version=?',
        (explanation_id, version)).fetchone()
    if row is None:
        return None
    return {
        'explanation_id': row[0], 'version': row[1], 'known_at': row[2],
        'period': row[3], 'region': row[4], 'published_at': row[5],
        'supersedes': row[6], 'narrative': row[7],
        'detail': json.loads(row[8]), 'basis': json.loads(row[9]),
        'fingerprint': row[10],
    }


def history(db, explanation_id):
    rows = db.execute(
        'SELECT version FROM explanations WHERE explanation_id=? '
        'ORDER BY published_at, version', (explanation_id,)).fetchall()
    return [get_explanation(db, explanation_id, row[0]) for row in rows]
