"""验证跨期跨河段归因、证据状态和解释版次治理。"""
import json
import unittest
from pathlib import Path

from climate_analysis.evidence import connect, receive
from climate_analysis.attribution import explain, evaluate_claim
from climate_analysis.explanation import (
    register_published, revise, get_explanation, history)

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / 'data' / 'scenario.json').read_text(
    encoding='utf8'))


class AttributionCase(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        for doc in SCENARIO['documents']:
            receive(self.db, doc)

    def tearDown(self):
        self.db.close()

    def _component(self, result, metric):
        return next(c for c in result['components'] if c['metric'] == metric)

    def test_first_known_at_uses_licence_when_returns_missing(self):
        # 2026-08-01：取水尚未补报，按许可量代入且降级为许可口径
        result = explain(self.db, SCENARIO['known_at'][0],
                         'reach-2', '2025水文年')
        self.assertEqual(result['status'], '可比')
        abstraction = self._component(result, 'abstraction')
        self.assertEqual(abstraction['status'], '许可口径:实际取水缺报')
        self.assertEqual(abstraction['current_amount'], 220)
        self.assertEqual(abstraction['reference_amount'], 100)
        self.assertEqual(abstraction['explained_delta'], -120)
        # 始终保留正的无法归因残差
        self.assertGreater(result['unexplained_residual'], 0)
        self.assertEqual(result['gap_to_target'], -400)
        self.assertIn('补水承诺依据成立', result['gap_note'])

    def test_second_known_at_picks_up_supplemented_returns_and_recompute(self):
        result = explain(self.db, SCENARIO['known_at'][1],
                         'reach-2', '2025水文年')
        abstraction = self._component(result, 'abstraction')
        glacier = self._component(result, 'glacier_melt')
        self.assertEqual(abstraction['status'], '补报实测:超许可取水')
        self.assertEqual(abstraction['current_amount'], 250)
        self.assertEqual(abstraction['explained_delta'], -150)
        self.assertEqual(glacier['status'], '模型估计')
        self.assertEqual(glacier['current_amount'], 310)
        self.assertEqual(glacier['explained_delta'], -90)
        # 支流为实测，降水为枯水年实测
        self.assertEqual(self._component(result, 'tributary_flow')['status'],
                         '实测支持')
        precip = self._component(result, 'precipitation_runoff')
        self.assertEqual(precip['year_type'], '枯水年')
        # 残差仍为正：证据不能闭合全部缺口
        self.assertGreater(result['unexplained_residual'], 0)

    def test_water_balance_identity(self):
        for known_at in SCENARIO['known_at']:
            for region in ('reach-1', 'reach-2'):
                r = explain(self.db, known_at, region, '2025水文年')
                rebuilt = sum(c['explained_delta']
                              for c in r['components']
                              if c['explained_delta'] is not None)
                self.assertEqual(
                    r['observed_decline'],
                    rebuilt + r['unexplained_residual'])

    def test_incomparable_period_or_unit_is_excluded(self):
        # 新增一条期间/单位不一致的融水记录：不得静默并入平衡
        doc = {
            'source': '冰川监测机构', 'document_id': 'glacier-mismatch',
            'revision': 'r1', 'received_at': '2026-08-25T00:00:00+00:00',
            'records': [{
                'kind': 'glacier_melt', 'id': 'glacier-2', 'revision': 'r3',
                'valid_from': '2025-10-01',
                'payload': {
                    'metric': 'glacier_melt', 'region': 'reach-2',
                    'unit': '亿立方米', 'period': '2025水文年',
                    'value': 3.1}}]}
        receive(self.db, doc)
        result = explain(self.db, SCENARIO['known_at'][1],
                         'reach-2', '2025水文年')
        glacier = self._component(result, 'glacier_melt')
        self.assertTrue(glacier['status'].startswith('口径不可比'))
        self.assertIsNone(glacier['explained_delta'])
        self.assertEqual(glacier['sources'], [])

    def test_missing_evidence_is_unattributable(self):
        result = explain(self.db, SCENARIO['known_at'][1],
                         'reach-3', '2025水文年')
        self.assertIn('证据缺失', result['status'])

    def test_sole_cause_claim_rejected_while_multi_cause_partial(self):
        result = explain(self.db, SCENARIO['known_at'][0],
                         'reach-2', '2025水文年')
        verdict = evaluate_claim(
            result, '下游断流全部归因于冰川融水减少。')
        self.assertEqual(verdict['verdict'], '不支持')
        verdict2 = evaluate_claim(
            result, '断流由融水、取水、支流和降水共同导致。')
        self.assertEqual(verdict2['verdict'], '部分支持')
        self.assertIn('残差', verdict2['reason'])

    def test_sources_are_fingerprinted(self):
        result = explain(self.db, SCENARIO['known_at'][1],
                         'reach-2', '2025水文年')
        all_sources = set(result['sources'])
        for component in result['components']:
            all_sources.update(component['sources'])
        self.assertTrue(all_sources)
        self.assertTrue(all(len(sha) == 64 for sha in all_sources))


class ExplanationGovernanceCase(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        for doc in SCENARIO['documents']:
            receive(self.db, doc)

    def tearDown(self):
        self.db.close()

    def _register(self, entry, supersedes=None):
        common = dict(explanation_id=entry['explanation_id'],
                      version=entry['version'], known_at=entry['known_at'],
                      period=entry['period'], region=entry['region'],
                      published_at=entry['published_at'],
                      narrative=entry['narrative'])
        if supersedes:
            return revise(self.db, supersedes=supersedes, **common)
        return register_published(self.db, **common)

    def test_published_version_is_preserved_and_evaluated(self):
        v1_entry, v2_entry = SCENARIO['explanations']
        v1 = self._register(v1_entry)
        self.assertEqual(
            v1['detail']['claim_evaluation']['verdict'], '不支持')
        # 原叙述与原依据指纹原样保留
        self.assertEqual(v1['narrative'], v1_entry['narrative'])
        self.assertEqual(len(v1['fingerprint']), 64)
        again = register_published(
            self.db, v1_entry['explanation_id'], v1_entry['version'],
            v1_entry['known_at'], v1_entry['period'], v1_entry['region'],
            v1_entry['published_at'], v1_entry['narrative'])
        self.assertEqual(again['fingerprint'], v1['fingerprint'])

    def test_revision_records_attribution_changes_and_commitment(self):
        v1_entry, v2_entry = SCENARIO['explanations']
        self._register(v1_entry)
        v2 = self._register(v2_entry, supersedes='v1')
        metrics = {c['metric']: c
                   for c in v2['detail']['attribution_changes']}
        self.assertIn('abstraction', metrics)
        self.assertEqual(metrics['abstraction']['driver'],
                         '取水记录补报或许可执行更新')
        self.assertIn('glacier_melt', metrics)
        self.assertEqual(metrics['glacier_melt']['driver'],
                         '融水估计重算或冰川质量平衡更新')
        self.assertEqual(
            v2['detail']['preserved_prior_narrative'], v1_entry['narrative'])
        commitment = v2['detail']['commitment_assessment']
        self.assertFalse(commitment['commitment_affected'])
        self.assertIn('补水承诺维持', commitment['note'])
        # 修订版评估为部分支持（残差仍在），但不再是唯一原因表述
        self.assertEqual(v2['detail']['claim_evaluation']['verdict'],
                         '部分支持')
        self.assertEqual(len(history(self.db, 'exp-downstream')), 2)

    def test_revision_refuses_sole_cause_narrative(self):
        v1_entry, _ = SCENARIO['explanations']
        self._register(v1_entry)
        with self.assertRaises(ValueError):
            revise(self.db, 'exp-downstream', 'v2-bad',
                   SCENARIO['known_at'][1], '2025水文年', 'reach-2',
                   '2026-09-10T00:00:00+00:00',
                   '重算后断流完全归因于融水减少这一唯一原因。',
                   supersedes='v1')

    def test_revision_requires_existing_prior_version(self):
        with self.assertRaises(ValueError):
            revise(self.db, 'exp-ghost', 'v2',
                   SCENARIO['known_at'][1], '2025水文年', 'reach-2',
                   '2026-09-10T00:00:00+00:00', '多因素共同导致。',
                   supersedes='v1')

    def test_published_and_revised_basis_fingerprints_distinct(self):
        v1_entry, v2_entry = SCENARIO['explanations']
        v1 = self._register(v1_entry)
        v2 = self._register(v2_entry, supersedes='v1')
        self.assertNotEqual(v1['fingerprint'], v2['fingerprint'])
        self.assertIn(v1['fingerprint'],
                      json.dumps(v2['detail'], ensure_ascii=False))
        self.assertIsNotNone(get_explanation(self.db, 'exp-downstream', 'v1'))


if __name__ == '__main__':
    unittest.main()
