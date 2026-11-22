# -*- coding: utf-8 -*-
"""gongwen-university 专用文书机检脚本（university_check.py）单元测试。

运行：python -m unittest discover -s tests/university -t .
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "gongwen-university" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import university_check as uc  # noqa: E402


class UniversityRuleExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rs = uc.load_rules()

    def test_all_rules_hit_and_miss_examples(self):
        for rule in self.rs.rules:
            doc_type = rule.types[0] if rule.types else None
            for ex in rule.hit_examples:
                with self.subTest(rule=rule.id, kind="hit", ex=ex):
                    res = uc.check_text(ex, doc_type=doc_type, ruleset=self.rs)
                    ids = [it["rule_id"] for it in res["issues"]]
                    self.assertIn(rule.id, ids, f"{rule.id} 应命中：{ex}")
            for ex in rule.miss_examples:
                with self.subTest(rule=rule.id, kind="miss", ex=ex):
                    res = uc.check_text(ex, doc_type=doc_type, ruleset=self.rs)
                    ids = [it["rule_id"] for it in res["issues"]]
                    self.assertNotIn(rule.id, ids, f"{rule.id} 不应误报：{ex}")


class UniversityCheckLogicTests(unittest.TestCase):
    def test_procedural_contradiction_on_qianbao(self):
        text = (
            "关于实验室改造经费的请示\n"
            "分管副校长：\n"
            "本方案已于10月10日经学院党政联席会议研究同意。目前资产管理处、研究生院意见尚未征求。\n"
            "妥否，请批示。"
        )
        res = uc.check_text(text, doc_type="签报")
        ids = [it["rule_id"] for it in res["issues"]]
        self.assertIn("UNI-101", ids)

    def test_qianbao_clean_no_contradiction(self):
        text = (
            "关于实验室改造经费的请示\n"
            "分管副校长：\n"
            "本方案拟提交学院党政联席会议研究，并已征求资产管理处、研究生院意见，两部门均无异议。\n"
            "妥否，请批示。"
        )
        res = uc.check_text(text, doc_type="签报")
        self.assertEqual(res["summary"]["total"], 0)

    def test_external_escalates_uni002_to_p0(self):
        text = "本学科在相关方向达到国内领先水平。"
        res_in = uc.check_text(text, doc_type="学科评估", external=False)
        res_ext = uc.check_text(text, doc_type="学科评估", external=True)
        self.assertEqual(res_in["issues"][0]["level"], "P1")
        self.assertEqual(res_ext["issues"][0]["level"], "P0")

    def test_draft_note_ignored(self):
        text = (
            "2025学年，学院2025届本科生毕业去向落实率为91.2%。\n"
            "【起草说明】\n"
            "假设：原文写的就业率和国内领先已删去。\n"
        )
        res = uc.check_text(text, doc_type="学院总结")
        self.assertEqual(res["summary"]["total"], 0)

    def test_cli_json_and_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.txt"
            p.write_text("签约后保证录取，并提供内部指标。", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "university_check.py"), str(p), "--json", "--strict"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            self.assertGreaterEqual(data["summary"]["P0"], 1)

    def test_cli_list_rules(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "university_check.py"), "--list-rules"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("UNI-001", proc.stdout)
        self.assertIn("UNI-101", proc.stdout)


if __name__ == "__main__":
    unittest.main()
