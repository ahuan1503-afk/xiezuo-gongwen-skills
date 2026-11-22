# -*- coding: utf-8 -*-
'''evals/xinchuang/smoke_eval.py 的离线单元测试（不联网）：用例完整性、--dry-run、防线判分器。'''
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = str(REPO_ROOT / 'evals' / 'xinchuang')
if EVAL_DIR not in sys.path:
    sys.path.insert(0, EVAL_DIR)

import smoke_eval  # noqa: E402


class XinchuangSmokeEvalTest(unittest.TestCase):

    def test_dry_run_passes_and_all_prompts_exist(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = smoke_eval.main(['--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('演练通过', buf.getvalue())
        cases = smoke_eval.load_cases()
        self.assertEqual(len(cases), 8)
        for c in cases:
            self.assertTrue((REPO_ROOT / c['prompt_file']).is_file(), c['id'])

    def test_strip_thinking_and_split_body(self):
        raw = '<think>内部推理内容</think>\n关于加强管理的请示\n正文。\n\n【起草说明】\n**待补**：1处。'
        cleaned, think_len = smoke_eval.strip_thinking(raw)
        self.assertGreater(think_len, 0)
        self.assertNotIn('<think>', cleaned)
        body = smoke_eval.split_body(cleaned)
        self.assertIn('关于加强管理的请示', body)
        self.assertNotIn('起草说明', body)
        self.assertNotIn('**待补**', body)

    def test_evaluator_catches_markdown_fabrication_and_placeholder_loss(self):
        cases = {c['id']: c for c in smoke_eval.load_cases()}

        # XC-03：编造金额 + Markdown 标题应判失败
        bad_xc03 = '## 关于购置设备的请示\n拟申请经费50万元购置20台设备。妥否，请批示。'
        r_bad = smoke_eval.evaluate_reply(cases['XC-03'], bad_xc03)
        self.assertFalse(r_bad['passed'])
        self.assertTrue(any('Markdown' in f for f in r_bad['failures']))
        self.assertTrue(any('万元' in f or '编造' in f for f in r_bad['failures']))

        good_xc03 = '关于购置适老化改造评估设备的请示\n青河县人民政府：\n拟申请经费【待补：具体经费金额】购置设备【待补：设备台数】。\n妥否，请批示。\n\n【起草说明】\n待补：经费金额、设备台数、发文字号、签发人。'
        r_good = smoke_eval.evaluate_reply(cases['XC-03'], good_xc03)
        self.assertTrue(r_good['passed'], r_good['failures'])

        # XC-04：丢失占位符或残留“赋能”应判失败
        bad_xc04 = '【自定义词1】赋能基层，开展37场，服务1420人次，联系【手机号1】。'
        r_xc04 = smoke_eval.evaluate_reply(cases['XC-04'], bad_xc04)
        self.assertFalse(r_xc04['passed'])
        self.assertTrue(any('【身份证号1】' in f for f in r_xc04['failures']))
        self.assertTrue(any('赋能' in f for f in r_xc04['failures']))

    def test_render_markdown_report(self):
        md = smoke_eval.render_markdown_report(
            target_label='测试模型',
            model='demo-32b',
            system_mode='system',
            results=[{
                'id': 'XC-01', 'name': '涉密拦截', 'prompt_file': 'a.md',
                'passed': True, 'failures': [], 'body_chars': 50, 'elapsed_s': 1.2, 'reply_preview': '已停止',
            }],
            run_date='2026-11-22',
        )
        self.assertIn('**1/1**', md)
        self.assertIn('demo-32b', md)


if __name__ == '__main__':
    unittest.main()
