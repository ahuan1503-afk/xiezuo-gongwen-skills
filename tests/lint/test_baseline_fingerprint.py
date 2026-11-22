#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gongwen_lint.py --fingerprint 文风指纹体检（FGP-001～005）单元测试。"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.lint.helpers import gl, ids


class FingerprintTest(unittest.TestCase):
    def test_fgp001_short_choppy_sentences(self) -> None:
        # 大量 10 字碎短句（>= 400 字）
        text = "关于加强社区治理的调研报告\n" + ("我们走访了社区。大家反映问题多。办事流程太慢。群众很有意见。" * 20)
        res = gl.lint_text(text, "调研报告", "style", fingerprint=True)
        self.assertIn("FGP-001", ids(res))
        self.assertIn("fingerprint", res)
        self.assertLess(res["fingerprint"]["avg_sent_len"], 30.0)

    def test_fgp002_force_quota_and_false_positive_protection(self) -> None:
        # 引号内概念和“不得不”不得计入强制词
        safe_text = (
            "关于优化窗口服务的通知\n各科室：\n"
            + ("我们建立了“必须改”“不得缓”分类清单，遇到紧急情况不得不先行受理，各窗口要按时办结相关事项，确保群众办事顺畅高效。" * 8)
        )
        res_safe = gl.lint_text(safe_text, "通知", "defensive", fingerprint=True)
        self.assertNotIn("FGP-002", ids(res_safe))
        self.assertEqual(res_safe["fingerprint"]["modals"]["强制"], 0)

        # 超配额的强制词必须命中 FGP-002
        heavy_text = (
            "关于优化窗口服务的通知\n各科室：\n"
            + ("各窗口必须按时开门，应当规范着装，不得推诿扯皮，严禁收取额外费用，必须当日登记，不得延迟回复，严禁敷衍塞责。" * 5)
        )
        res_heavy = gl.lint_text(heavy_text, "通知", "defensive", fingerprint=True)
        self.assertIn("FGP-002", ids(res_heavy))
        self.assertGreater(res_heavy["fingerprint"]["modals"]["强制"], 5)

    def test_fgp003_section_weight_imbalance(self) -> None:
        # 调研报告把 75% 篇幅压在单一板块上
        heavy_sec = "通过实地走访企业和行业协会了解到多项关键流程与标准衔接情况，结合现场测算数据梳理出改造堵点与推进路径。" * 22
        short_sec = "调研组走访了部分重点企业和行业协会，梳理了基础运行情况并形成阶段性记录。" * 3
        text = (
            "关于制造业数字化改造情况的调研报告\n"
            f"一、基本情况\n{short_sec}\n"
            f"二、主要问题\n{heavy_sec}\n"
            f"三、对策建议\n{short_sec}\n"
        )
        res = gl.lint_text(text, "调研报告", "structure", fingerprint=True)
        self.assertIn("FGP-003", ids(res))
        self.assertTrue(len(res["fingerprint"]["sections"]) >= 3)

    def test_fgp004_hard_genre_mismatch(self) -> None:
        # 千字信息硬塞 3 个一级标题 -> P1
        short_info = (
            "某街道推进网格便民服务提质增效\n"
            "一、建强阵地\n街道盘活社区用房建立暖心驿站，配齐饮水机、微波炉和应急药箱等基础便民设施。\n"
            "二、优化流程\n社区建立首问负责机制，把高频便民事项整合到综合窗口办理，压缩群众跑动次数。\n"
            "三、强化联动\n组织物业、商圈和社区网格员定期会商，及时回应并化解停车充电等身边小事。\n"
        )
        res_info = gl.lint_text(short_info, "信息", "structure", fingerprint=True)
        fgp4 = [i for i in res_info["issues"] if i["id"] == "FGP-004"]
        self.assertEqual(len(fgp4), 1)
        self.assertEqual(fgp4[0]["level"], "P1")

        # 讲话稿塞入 3 个三级标题 -> P1
        speech = (
            "在全区防汛工作推进会上的讲话\n同志们：\n"
            "一、压实防汛责任\n（一）抓实隐患排查\n"
            "1. 排查低洼院落。\n2. 排查下穿立交。\n3. 排查在建深基坑。\n"
        )
        res_speech = gl.lint_text(speech, "讲话稿", "structure", fingerprint=True)
        self.assertIn("FGP-004", ids(res_speech))

    def test_fgp005_ascii_quotes_and_cli(self) -> None:
        text = '关于开展春季检查的通知\n各科室：\n请围绕"重点点位"和"关键环节"做好排查，确保隐患及时清零。\n'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.txt"
            p.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = gl.main([str(p), "--doc-type", "通知", "--fingerprint", "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertIn("FGP-005", [i["id"] for i in data["issues"]])
            self.assertEqual(data["fingerprint"]["ascii_quotes"], 4)


if __name__ == "__main__":
    unittest.main()
