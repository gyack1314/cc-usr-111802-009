"""按可比期间与河段分解断流缺口，标注每项归因的证据状态。

口径对齐规则：只有 metric、region、unit、period 四项完全一致的记录才参与
同河段平衡；期间或单位不一致的记录保留为“口径不可比”，不得静默并入。
每个组件都带来源 sha256；缺失或不可比对应“无法归因”，残差同样显式列出。
"""
from .evidence import records

# 按指标约定的组件元数据。sign 表示该来源水量相对断面流量的符号。
COMPONENTS = {
    'glacier_melt': {'label': '冰川融水', 'sign': +1},
    'tributary_flow': {'label': '支流实测来水', 'sign': +1},
    'precipitation_runoff': {'label': '降水年份差异来水', 'sign': +1},
    'abstraction': {'label': '取水', 'sign': -1},
}
# 可被纳入平衡的记录类型（observation/reference/rule 仍走原单期流程）。
ATTRIBUTION_KINDS = tuple(COMPONENTS)
SOLE_CAUSE_MARKERS = ('唯一原因', '全部归因', '完全归因', ' solely ')


def _pick(rows, metric, region, unit, period):
    """返回同口径下取得时间最新的记录；期间或单位不符返回不可比标记。"""
    same_region = [r for r in rows if r['payload'].get('metric') == metric
                   and r['payload'].get('region') == region]
    if not same_region:
        return None, '证据缺失'
    comparable = [r for r in same_region
                  if r['payload'].get('period') == period
                  and r['payload'].get('unit') == unit]
    if not comparable:
        held = sorted({(str(r['payload'].get('period')), str(r['payload'].get('unit')))
                       for r in same_region})
        return None, '口径不可比:现有记录期间/单位=%s' % held
    return comparable[-1], None


def _component_status(kind, payload, problem):
    if problem:
        return problem
    if kind == 'tributary_flow':
        return '实测支持'
    if kind == 'glacier_melt':
        method = str(payload.get('method', ''))
        return '模型估计' if '模型' in method or '估计' in method else '实测支持'
    if kind == 'precipitation_runoff':
        return '实测支持'
    if kind == 'abstraction':
        actual = payload.get('actual')
        if actual is None:
            return '许可口径:实际取水缺报'
        if payload.get('compliance') == '超许可':
            return '补报实测:超许可取水'
        return '实测支持'
    return '待核实'


def _build_component(kind, current, ref, region, unit, period):
    meta = COMPONENTS[kind]
    cur_row, cur_problem = _pick(current, kind, region, unit, period)
    ref_row, ref_problem = _pick(ref, kind, region, unit, 'REF')
    if cur_problem or ref_problem:
        problem = cur_problem or ref_problem
        return {'metric': kind, 'label': meta['label'], 'status': problem,
                'delta': None, 'explained_delta': None, 'sources': [],
                'note': '该组件不纳入平衡，对应水量无法归因'}
    cp, rp = cur_row['payload'], ref_row['payload']

    def amount(row_payload):
        if kind == 'abstraction':
            value = row_payload.get('actual')
            if value is None:
                value = row_payload.get('permitted')
            return value
        return row_payload['value']

    cur_amount, ref_amount = amount(cp), amount(rp)
    raw_delta = cur_amount - ref_amount
    explained = meta['sign'] * raw_delta
    info = {
        'metric': kind, 'label': meta['label'],
        'status': _component_status(kind, cp, None),
        'current_amount': cur_amount, 'reference_amount': ref_amount,
        'delta': raw_delta, 'explained_delta': explained,
        'sources': [cur_row['source']['sha256'], ref_row['source']['sha256']],
    }
    if kind == 'abstraction':
        info['permitted'] = cp.get('permitted')
        info['permitted_reference'] = rp.get('permitted')
        if cp.get('actual') is None:
            info['note'] = '仅有许可量，实际取水缺报，按许可量代入且证据状态降级'
        elif cp.get('compliance') == '超许可':
            info['note'] = '取水记录为补报，实际取水超过许可'
    if kind == 'precipitation_runoff':
        info['year_type'] = cp.get('year_type')
        info['year_type_reference'] = rp.get('year_type')
    if kind == 'glacier_melt':
        info['method'] = cp.get('method')
        info['mass_balance_metres_we'] = cp.get('mass_balance_metres_we')
    return info


def explain(db, known_at, region, period, unit='万立方米'):
    """形成单河段单期间的缺口分解与不可归因残差。"""
    obs = records(db, 'observation', known_at)
    refs = records(db, 'reference', known_at)
    cur_flow, flow_problem = _pick(obs, 'flow', region, unit, period)
    ref_flow, ref_problem = _pick(refs, 'flow', region, unit, 'REF')
    if flow_problem or ref_problem:
        return {'region': region, 'period': period, 'unit': unit,
                'status': flow_problem or ref_problem, 'components': []}

    current_rows = []
    reference_rows = []
    for kind in ATTRIBUTION_KINDS:
        current_rows.extend(records(db, kind, known_at))
        reference_rows.extend(records(db, kind, known_at))

    components = [_build_component(kind, current_rows, reference_rows,
                                   region, unit, period)
                  for kind in ATTRIBUTION_KINDS]
    usable = [c for c in components if c['explained_delta'] is not None]
    observed_flow = cur_flow['payload']['value']
    reference_flow = ref_flow['payload']['value']
    observed_decline = observed_flow - reference_flow
    explained = sum(c['explained_delta'] for c in usable)
    residual = observed_decline - explained

    rules = [r for r in records(db, 'rule', known_at)
             if r['payload'].get('region') == region
             and r['payload'].get('metric') == 'flow'
             and r['payload'].get('unit') == unit]
    target = None
    target_sources = []
    if rules:
        rule_payload = rules[-1]['payload']
        target = rule_payload.get('target')
        target_sources = [rules[-1]['source']['sha256']]
    gap_to_target = (observed_flow - target) if target is not None else None

    return {
        'region': region, 'period': period, 'unit': unit, 'status': '可比',
        'observed_flow': observed_flow, 'reference_flow': reference_flow,
        'observed_decline': observed_decline,
        'explained_decline': explained,
        'unexplained_residual': residual,
        'residual_note': '正残差为尚未归因的减少量；负残差表示已列证据超过实测变化',
        'ecological_target': target,
        'gap_to_target': gap_to_target,
        'gap_note': ('实测低于生态流量目标，补水承诺依据成立'
                     if gap_to_target is not None and gap_to_target < 0
                     else '实测不低于生态流量目标'),
        'components': components,
        'sources': [cur_flow['source']['sha256'], ref_flow['source']['sha256']]
                   + target_sources,
    }


def evaluate_claim(attribution, narrative):
    """核对一句归因陈述能否被当前证据支持。

    唯一原因类陈述只有在“单一数值组件、无缺失/不可比、残差为零”时才成立；
    多因素陈述在存在无法归因残差或证据缺口时降级为部分支持。
    """
    if attribution['status'] != '可比':
        return {'verdict': '无法判断', 'reason': attribution['status']}
    components = attribution['components']
    numeric = [c for c in components if c['explained_delta'] is not None]
    unsupported = [c['label'] for c in components if c['explained_delta'] is None]
    residual = attribution['unexplained_residual']
    sole_cause = any(marker in narrative for marker in SOLE_CAUSE_MARKERS)
    if sole_cause:
        if len(numeric) == 1 and not unsupported and residual == 0:
            return {'verdict': '支持', 'reason': '仅一个有证据组件且残差为零'}
        reasons = []
        if len(numeric) != 1:
            reasons.append('存在%d个有数值的并列归因组件' % len(numeric))
        if unsupported:
            reasons.append('证据缺口:%s' % '、'.join(unsupported))
        if residual != 0:
            reasons.append('无法归因残差=%s' % residual)
        return {'verdict': '不支持', 'reason': '；'.join(reasons)}
    if unsupported or residual != 0:
        reasons = []
        if unsupported:
            reasons.append('证据缺口:%s' % '、'.join(unsupported))
        if residual != 0:
            reasons.append('无法归因残差=%s' % residual)
        return {'verdict': '部分支持', 'reason': '；'.join(reasons)}
    return {'verdict': '支持', 'reason': '全部缺口由有证据组件闭合'}
