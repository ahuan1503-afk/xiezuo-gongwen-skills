# -*- coding: utf-8 -*-
"""本机工具箱（xinchuang/local_toolbox.py）行业专检接口单元测试。

运行：python -m unittest tests.tools.test_local_toolbox_industry -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
XINCHUANG_DIR = REPO_ROOT / "xinchuang"
if str(XINCHUANG_DIR) not in sys.path:
    sys.path.insert(0, str(XINCHUANG_DIR))

import local_toolbox as tb  # noqa: E402


class LocalToolboxIndustryCheckTests(unittest.TestCase):
    def test_empty_text_rejected(self):
        res = tb.op_industry_check({"b": "   ", "industry": "grassroots"})
        self.assertFalse(res["ok"])
        self.assertIn("没有待检正文", res["text"])

    def test_grassroots_coercion_and_burden(self):
        text = "森林防火通知\n各位村民：\n未签责任书的取消分红资格。\n某村民委员会\n2026年10月16日\n"
        res = tb.op_industry_check({"b": text, "industry": "grassroots"})
        self.assertFalse(res["ok"])
        self.assertIn("NTC-018", res["text"])

    def test_hospital_external_p0(self):
        res = tb.op_industry_check({
            "b": "我院中医特色疗法保证治愈，永不复发。",
            "industry": "hospital",
            "ind_external": True,
        })
        self.assertFalse(res["ok"])
        self.assertIn("HOS-001", res["text"])

    def test_soe_procedure_check(self):
        res = tb.op_industry_check({
            "b": "本项目先行开工，后续再补办党委会前置研究和董事会审议程序。",
            "industry": "soe",
            "doc_type": "议题材料",
        })
        self.assertFalse(res["ok"])
        self.assertIn("SOE-001", res["text"])

    def test_k12_parents_and_general(self):
        res_p = tb.op_industry_check({
            "b": "请各位家长今晚检查并批改孩子的数学作业。",
            "industry": "k12_parents",
        })
        self.assertFalse(res_p["ok"])
        self.assertIn("JZ-001", res_p["text"])

        res_g = tb.op_industry_check({
            "b": "课后服务统一讲授新课，要求学生强制参加。",
            "industry": "k12_general",
        })
        self.assertFalse(res_g["ok"])
        self.assertIn("K12-G03", res_g["text"])

    def test_university_and_blind_proposal(self):
        res_u = tb.op_industry_check({
            "b": "签约后保证录取并提供内部指标。",
            "industry": "university",
        })
        self.assertFalse(res_u["ok"])
        self.assertIn("UNI-004", res_u["text"])

        res_b = tb.op_industry_check({
            "b": "本研究由张三主持，在我校开展前期调研。",
            "industry": "university_blind",
            "terms": "张三、某大学",
        })
        self.assertFalse(res_b["ok"])
        self.assertIn("[P0] 匿名", res_b["text"])
        self.assertIn("〔身份词〕", res_b["text"])

    def test_page_contains_industry_ui(self):
        self.assertIn('id="indPack"', tb.PAGE)
        self.assertIn('data-op="industry_check"', tb.PAGE)


if __name__ == "__main__":
    unittest.main()
