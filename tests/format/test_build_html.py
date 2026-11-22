#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单文件 GB/T 9704 HTML 轻排版（build_html.py）及工具箱接口测试。"""
from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "gongwen-format" / "scripts"))
sys.path.insert(0, str(ROOT / "xinchuang"))

import build_html  # noqa: E402
import local_toolbox  # noqa: E402


SAMPLE_NOTICE = """关于召开全区冬季供暖协调会的通知

各街道办事处、区直有关部门：

为做好今冬供暖保障工作，定于2026年11月25日下午2时30分在区政府三楼会议室召开协调会。现将有关事项通知如下：

一、参会人员
各街道分管负责人，区城管局、区财政局主要负责人。

二、会议内容
（一）通报管网检修进度。重点核查老旧小区换热站试压情况。
（二）部署寒潮应急值班。

| 单位 | 联系人 | 报送截止 |
| --- | --- | --- |
| 城管局 | 王某 | 11月24日 |

附件：1. 参会回执表
2. 换热站排查清单

某区人民政府办公室
2026年11月22日

【起草说明】
假设：按会议通知白头排。
"""


class TestBuildHtml(unittest.TestCase):
    def test_auto_white_layout_and_cutoff(self) -> None:
        html_doc, report = build_html.build_html(SAMPLE_NOTICE.splitlines())
        self.assertEqual(report["layout"], "白头")
        self.assertIn("关于召开全区冬季供暖协调会的通知", html_doc)
        self.assertIn("各街道办事处、区直有关部门：", html_doc)
        self.assertIn("@page", html_doc)
        self.assertIn("margin: 37mm 26mm 35mm 28mm", html_doc)
        self.assertIn("打印 / 存为 PDF", html_doc)
        self.assertIn("复制纯文本", html_doc)
        self.assertIn("复制富文本", html_doc)
        self.assertIn('<table class="gw-table">', html_doc)
        self.assertIn("gw-attachment-first", html_doc)
        self.assertNotIn("【起草说明】", html_doc)
        self.assertNotIn("按会议通知白头排", html_doc)

    def test_redhead_and_meta(self) -> None:
        meta = {
            "发文机关标志": "某区人民政府办公室文件",
            "发文字号": "某政办发〔2026〕18号",
            "抄送": ["区委办公室", "区人大常委会办公室"],
            "印发机关": "某区人民政府办公室",
            "印发日期": "2026年11月22日印发",
        }
        html_doc, report = build_html.build_html(SAMPLE_NOTICE.splitlines(), meta=meta)
        self.assertEqual(report["layout"], "红头")
        self.assertIn('data-layout="红头"', html_doc)
        self.assertIn("某区人民政府办公室文件", html_doc)
        self.assertIn("某政办发〔2026〕18号", html_doc)
        self.assertIn("抄送：区委办公室，区人大常委会办公室。", html_doc)

    def test_note_layout_and_xss_escape(self) -> None:
        lines = [
            "关于停水检修的通知",
            "各位居民：",
            "明早8时停水<script>alert(1)</script>，请提前储水。",
            "某社区居委会",
            "2026年11月22日",
        ]
        html_doc, report = build_html.build_html(lines, layout="便签")
        self.assertEqual(report["layout"], "便签")
        self.assertNotIn("<script>alert(1)</script>", html_doc)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_doc)

    def test_cli_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "notice.txt"
            out = Path(tmp) / "notice.html"
            src.write_text(SAMPLE_NOTICE, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = build_html.main([str(src), "-o", str(out), "--layout", "白头", "--json"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["layout"], "白头")
            self.assertTrue(out.is_file())
            content = out.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", content)
            self.assertIn("关于召开全区冬季供暖协调会的通知", content)

    def test_toolbox_format_html(self) -> None:
        res = local_toolbox.op_format_html({"b": SAMPLE_NOTICE})
        self.assertTrue(res["ok"])
        self.assertEqual(res["mode"], "html_lite")
        decoded = base64.b64decode(res["html_b64"]).decode("utf-8")
        self.assertIn("关于召开全区冬季供暖协调会的通知", decoded)
        self.assertNotIn("【起草说明】", decoded)

    def test_empty_input_error(self) -> None:
        res = local_toolbox.op_format_html({"b": "   \n【起草说明】\n无"})
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
