#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gongwen_lint.py --fingerprint 文风指纹体检（FGP-001～004）单元测试。"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.lint.helpers import LINTER, gl, ids


def fp(text: str, doc_type: str, checks: str = "all", **kw):
    return gl.lint_text(text, doc_type, checks, linter=LINTER, fingerprint=True, **kw)


class FingerprintTest(unittest.TestCase):
    def test_fgp001_short_choppy_sentences(self) -> None:
        # 大量 10 字左右的碎短句（>= 400 字）
        text = "关于加强社区治理的调研报告\n" + ("我们走访了辖区多个社区。大家反映办事问题较多。办事流程环节太慢。群众意见比较集中。" * 20)
        res = fp(text, "调研报告", "style")
        self.assertIn("FGP-001", ids(res))
        self.assertLess(res["fingerprint"]["avg_sent_len"], 30.0)

    def test_fgp001_sentence_split_matches_baseline(self) -> None:
        # 主送、落款、日期、标题不计入句子，口径与 tools/build_baseline.py 一致
        text = ("关于开展冬季消防检查的通知\n各科室：\n"
                "请各科室于11月30日前完成本部门消防设施自查并将整改台账报安全保卫科备案。\n"
                "某局\n2026年11月1日\n")
        res = fp(text, "通知")
        # 只有正文一句（37 字）计入，主送、落款、日期不拉低均值
        self.assertEqual(res["fingerprint"]["avg_sent_len"], 37.0)
        self.assertEqual(gl.sentence_lengths(["第一句话在这里。后面又来了一段较长的无标点残句"]), [7, 15])
        self.assertEqual(gl.sentence_lengths(["第一句话在这里。残句"]), [7])

    def test_fgp001_long_sentences_use_baseline_band(self) -> None:
        # 批复的语料 P90 均句长约 110 字：80 字长句不应报告；没有基线的文种按固定上限 75 报告
        sent = "同意你单位关于调整城区部分道路交通组织方案的请示所提出的总体安排和分阶段实施步骤，请按程序做好公示和社会稳定风险评估等工作。"
        sent = sent * 1
        text = "某市人民政府关于同意调整城区部分道路交通组织方案的批复\n某市交通运输局：\n" + (sent * 8) + "\n"
        avg = fp(text, "批复")["fingerprint"]["avg_sent_len"]
        self.assertGreater(avg, 60)
        long_sent = sent[:-1] + "，并结合沿线学校医院商圈的通行需求同步优化公交线路和停车设施布局。"
        long_text = "某市人民政府关于同意调整城区部分道路交通组织方案的批复\n某市交通运输局：\n" + (long_sent * 8) + "\n"
        res = fp(long_text, "批复", "style")
        self.assertGreater(res["fingerprint"]["avg_sent_len"], 75)
        self.assertNotIn("FGP-001", ids(res))
        self.assertGreaterEqual(res["fingerprint"]["sent_len_band"][1], 100)
        res_other = fp(long_text.replace("批复", "信息"), "信息", "style")
        self.assertIn("FGP-001", ids(res_other))

    def test_fgp002_shares_def028_word_list_and_density(self) -> None:
        # 引号内概念、“不得不”“舍不得”不计入强制词
        safe_text = (
            "关于优化窗口服务的通知\n各科室：\n"
            + ("我们建立了“必须改”“不得缓”分类清单，遇到紧急情况不得不先行受理，群众舍不得走远路，"
               "各窗口要按时办结相关事项，确保群众办事顺畅高效。" * 8)
        )
        res_safe = fp(safe_text, "通知", "style")
        self.assertNotIn("FGP-002", ids(res_safe))
        self.assertEqual(res_safe["fingerprint"]["modals"]["强制"], 0)

        heavy_text = (
            "关于优化窗口服务的通知\n各科室：\n"
            + ("各窗口必须按时开门，应当规范着装，不得推诿扯皮，严禁收取额外费用，必须当日登记，不得延迟回复，严禁敷衍塞责。" * 5)
        )
        # 只查 style 时由 FGP-002 报告；全量检查时 DEF-028 报告，FGP-002 不重复
        res_style = fp(heavy_text, "通知", "style")
        self.assertIn("FGP-002", ids(res_style))
        res_all = fp(heavy_text, "通知")
        self.assertIn("DEF-028", ids(res_all))
        self.assertNotIn("FGP-002", ids(res_all))
        # “应当”是规范性义务用语，不计入强制词：每句 必须2 + 不得2 + 严禁2
        self.assertEqual(res_all["fingerprint"]["modals"]["强制"], 30)
        fgp2 = [i for i in res_style["issues"] if i["id"] == "FGP-002"][0]
        self.assertGreater(fgp2["line"], 0)

    def test_force_density_by_doc_type(self) -> None:
        # 每千字约 4.5 处：通知（阈值 3）报告，函（阈值 6，引述法定义务多）不报告
        core = "依照条例规定，申请人严禁伪造材料，不得隐瞒有关情况。"
        filler = "按时完成日常检查记录。"
        body = (filler * 36 + core) * 4
        for doc_type, expect in (("通知", True), ("函", False)):
            with self.subTest(doc_type=doc_type):
                res = gl.lint_text(f"关于有关事项的{doc_type}\n某单位：\n{body}\n", doc_type, "defensive", linter=LINTER)
                self.assertEqual("DEF-028" in ids(res), expect)
        # 叙事类文种从严：每千字约 2.5 处，信息报告、通知不报告
        body2 = (filler * 70 + core) * 3
        self.assertIn("DEF-028", ids(gl.lint_text("某街道推进便民服务\n" + body2, "信息", "defensive", linter=LINTER)))
        self.assertNotIn("DEF-028", ids(gl.lint_text("关于有关事项的通知\n各科室：\n" + body2, "通知", "defensive", linter=LINTER)))

    def test_modal_counts_ignore_lookalikes(self) -> None:
        res = fp("关于做好有关工作的通知\n各科室：\n群众舍不得离开老房子，怪不得工作难做，巴不得早点搬，迫不得已才同意。\n", "通知")
        self.assertEqual(res["fingerprint"]["modals"]["强制"], 0)
        res = fp("关于做好有关工作的通知\n各科室：\n重要的是主要领导需要掌握要点，摘要和要求见附件。\n", "通知")
        self.assertEqual(res["fingerprint"]["modals"]["要求"], 0)
        res = fp("关于做好有关工作的通知\n各科室：\n各单位要压实责任，切实抓好落实，确保按期完成。\n", "通知")
        self.assertEqual(res["fingerprint"]["modals"]["要求"], 4)

    def test_fgp003_section_weight_imbalance(self) -> None:
        heavy_sec = "通过实地走访企业和行业协会了解到多项关键流程与标准衔接情况，结合现场测算数据梳理出改造堵点与推进路径。" * 22
        short_sec = "调研组走访了部分重点企业和行业协会，梳理了基础运行情况并形成阶段性记录。" * 3
        text = (
            "关于制造业数字化改造情况的调研报告\n"
            f"一、基本情况\n{short_sec}\n"
            f"二、主要问题\n{heavy_sec}\n"
            f"三、对策建议\n{short_sec}\n"
        )
        res = fp(text, "调研报告", "structure")
        hit = [i for i in res["issues"] if i["id"] == "FGP-003"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["line"], 4)
        self.assertTrue(len(res["fingerprint"]["sections"]) >= 3)

    def test_fgp004_genre_mismatch_is_p2(self) -> None:
        short_info = (
            "某街道推进网格便民服务提质增效\n"
            "一、建强阵地\n街道盘活社区用房建立暖心驿站，配齐饮水机、微波炉和应急药箱等基础便民设施。\n"
            "二、优化流程\n社区建立首问负责机制，把高频便民事项整合到综合窗口办理，压缩群众跑动次数。\n"
            "三、强化联动\n组织物业、商圈和社区网格员定期会商，及时回应并化解停车充电等身边小事。\n"
        )
        fgp4 = [i for i in fp(short_info, "信息", "structure")["issues"] if i["id"] == "FGP-004"]
        self.assertEqual(len(fgp4), 1)
        self.assertEqual(fgp4[0]["level"], "P2")
        self.assertEqual(fgp4[0]["line"], 6)

        speech = (
            "在全区防汛工作推进会上的讲话\n同志们：\n"
            "一、压实防汛责任\n（一）抓实隐患排查\n"
            "1. 排查低洼院落。\n2. 排查下穿立交。\n3. 排查在建深基坑。\n"
        )
        for doc_type in ("讲话稿", "党课讲稿", "研讨发言"):
            with self.subTest(doc_type=doc_type):
                self.assertIn("FGP-004", ids(fp(speech, doc_type, "structure")))

    def test_fingerprint_respects_checks(self) -> None:
        heavy = ("关于优化窗口服务的通知\n各科室：\n"
                 + "各窗口必须按时开门，应当规范着装，不得推诿扯皮，严禁收取额外费用。" * 6)
        res = fp(heavy, "通知", "term")
        self.assertEqual([i for i in res["issues"] if i["id"].startswith("FGP")], [])
        self.assertIn("fingerprint", res)

    def test_ascii_quotes_reported_by_pun021_only(self) -> None:
        text = '关于开展春季检查的通知\n各科室：\n请围绕"重点点位"和"关键环节"做好排查，确保隐患及时清零。\n'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.txt"
            p.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = gl.main([str(p), "--doc-type", "通知", "--fingerprint", "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            found = [i["id"] for i in data["issues"]]
            self.assertIn("PUN-021", found)
            self.assertNotIn("FGP-005", found)
            self.assertEqual(data["fingerprint"]["ascii_quotes"], 4)


if __name__ == "__main__":
    unittest.main()
