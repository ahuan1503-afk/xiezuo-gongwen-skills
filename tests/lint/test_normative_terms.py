# -*- coding: utf-8 -*-
"""规范用词检查（TRM-001～012）、行业规范词白名单（WL-020～022）、结语隔离与本单位规范词表测试。"""
from __future__ import annotations

import unittest

from tests.lint.helpers import LINTER, gl, ids, run
from tests.lint.test_cli import TempDirMixin


class NormativeTermRulesTest(unittest.TestCase):
    def test_trm_misused_terms_caught(self):
        text = (
            "关于做好冬季安全工作的通知\n\n"
            "各科室：\n\n"
            "截止2026年10月底，我局布署开展排查，做出了重要决定。"
            "公告栏张贴了招聘启示，帮助企业度过难关，明确职责界线。"
            "针对群众反应问题，持续推进法制政府建设，依法规范行政权利运行，"
            "保障生活必须品供应。加大对老少边穷地区的帮扶力度，报市卫计委和市环保局备案。\n\n"
            "特此通知。\n\n"
            "某市某局\n2026年11月1日\n"
        )
        found = set(ids(run(text, "通知", "term")))
        for rid in (
            "TRM-001", "TRM-002", "TRM-003", "TRM-004", "TRM-005", "TRM-006",
            "TRM-007", "TRM-008", "TRM-009", "TRM-010", "TRM-011", "TRM-012",
        ):
            self.assertIn(rid, found, f"未检出 {rid}")

    def test_trm_legitimate_phrases_not_flagged(self):
        text = (
            "关于做好冬季安全工作的通知\n\n"
            "各科室：\n\n"
            "截至2026年10月底，报名于10月31日截止。我局部署开展排查，作出重要决定。"
            "发布招聘启事，总结工作启示，帮助企业渡过难关，确保群众度过春节假期。"
            "明确职责界限，勘定行政区域界线。针对群众反映问题，做好药品不良反应监测。"
            "推进法治政府建设，落实重大行政决策法制审核制度，规范行政权力运行，保障群众合法权利。"
            "保障生活必需品供应，必须严格落实值班制度。"
            "原银保监会及农业部门、文化部门有关规定继续参照执行。\n\n"
            "特此通知。\n\n"
            "某市某局\n2026年11月1日\n"
        )
        found = [i for i in run(text, "通知", "term")["issues"] if i["id"].startswith("TRM-")]
        self.assertEqual(found, [])

    def test_gonggao_and_tonggao_closing_not_interchangeable(self):
        gonggao_bad = (
            "某市人民政府公告\n\n"
            "根据有关法律法规规定，经市政府常务会议研究审定，现将2026年度全市重点建设项目核准名单及法定事项予以公布。"
            "本次共公布基础设施、生态环保、民生保障等领域重点项目28个，具体名单详见市政府门户网站政务公开专栏。"
            "请社会各界予以监督，如有异议请于公示期内向市政府办公室书面反馈。\n\n"
            "特此通告。\n\n某市人民政府\n2026年11月1日\n"
        )
        tonggao_bad = (
            "某市公安局关于部分路段实施交通管制的通告\n\n"
            "因市政雨污分流管网抢修施工需要，为保障道路交通安全畅通，定于2026年11月5日0时至11月10日24时，"
            "对中山路解放路口至人民广场路段实行临时交通管制。管制期间禁止社会机动车辆通行，公交线路临时绕行建设路，"
            "请过往车辆和行人提前规划路线并服从现场执勤交警指挥。\n\n"
            "特此公告。\n\n某市公安局\n2026年11月1日\n"
        )
        self.assertIn("ELM-003", ids(run(gonggao_bad, "公告", "format")))
        self.assertIn("ELM-003", ids(run(tonggao_bad, "通告", "format")))

        gonggao_ok = gonggao_bad.replace("特此通告", "特此公告")
        tonggao_ok = tonggao_bad.replace("特此公告", "特此通告")
        self.assertNotIn("ELM-003", ids(run(gonggao_ok, "公告", "format")))
        self.assertNotIn("ELM-003", ids(run(tonggao_ok, "通告", "format")))


class NormativeWhitelistTest(unittest.TestCase):
    def test_industry_bihuan_and_shenduronghe_not_flagged(self):
        text = (
            "一、推行用药闭环和危急值闭环管理，健全隐患排查治理闭环管理机制，"
            "严格落实全流程闭环要求。\n"
            "二、深化产教深度融合、科教深度融合与党建与业务深度融合，"
            "推动文旅深度融合与数实深度融合发展。\n"
        )
        self.assertNotIn("AI-026", ids(run(text, "汇报材料", "style")))

    def test_sanguan_sanbixu_not_counted_as_force_quota(self):
        text = (
            "各单位要认真落实“三管三必须”要求，全面压实行业监管责任。"
            "坚持三管三必须原则，持续开展提质增效专项行动，完善全链条监管和全周期管理机制。"
            "严禁瞒报谎报事故信息。\n"
        )
        self.assertNotIn("DEF-028", ids(run(text, "通知", "defensive")))
        self.assertNotIn("AI-027", ids(run(text, "通知", "style")))
        res = gl.lint_text(text, "通知", "all", linter=LINTER, fingerprint=True)
        # 只有“严禁”1处计入强制词，“三管三必须”不计入
        self.assertEqual(res["fingerprint"]["modals"]["强制"], 1)


class UnitNormativeTableTest(TempDirMixin, unittest.TestCase):
    def test_unit_normative_table_in_banned_file(self):
        md = (
            "# 禁用词\n\n"
            "| 词语或表述 | 级别 | 原因 | 替换建议 | 适用范围 |\n"
            "|---|---|---|---|---|\n"
            "| 拉满 | 禁用 | 网络语 | 显著提升 | 全部 |\n\n"
            "## 本单位规范词\n\n"
            "| 不规范写法 | 规范写法 | 原因 | 适用范围 |\n"
            "|---|---|---|---|\n"
            "| 县卫计委、卫生局 | 县卫生健康局 | 本地机构规范名 | 全部 |\n"
        )
        terms = gl.load_banned(self.write("禁用词.md", md))
        by_term = {t.term: t for t in terms}
        self.assertIn("县卫计委", by_term)
        self.assertIn("卫生局", by_term)
        self.assertTrue(by_term["县卫计委"].banned)
        self.assertEqual(by_term["县卫计委"].suggestion, "县卫生健康局")

        text = "请各乡镇于月底前报送县卫计委审核，氛围拉满。"
        # --checks term 也能比对 --banned 表
        res = gl.lint_text(text, "通知", "term", linter=LINTER, banned=terms)
        found = {(i["id"], i["excerpt"]): i for i in res["issues"] if i["id"].startswith("BAN-")}
        self.assertIn(("BAN-001", "县卫计委"), found)
        self.assertEqual(found[("BAN-001", "县卫计委")]["suggestion"], "县卫生健康局")
        self.assertIn(("BAN-001", "拉满"), found)


if __name__ == "__main__":
    unittest.main()
