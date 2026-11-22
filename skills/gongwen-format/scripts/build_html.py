#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单文件 GB/T 9704 轻量 HTML 排版器（只依赖 Python 标准库，零外联，无需 python-docx）。

定位：
  面向日常通知、急件预览、发群/贴门、无 Python 第三方库或无需编辑 .docx 的轻量场景，
  把公文纯文本直接渲染成单文件 .html：
  1. 内置 GB/T 9704-2012 A4 打印样式（上 37mm、下 35mm、左 28mm、右 26mm、28pt 行距）；
  2. 顶部工具条（打印/存 PDF 时自动隐藏）支持：打印/存 PDF、一键复制纯文本、一键复制富文本、
     实时切换「白头 / 红头 / 材料 / 便签」四种版式；
  3. 严守字体诚实原则：CSS 声明标准公文字体名，不冒充正式国标印刷成品；正式送签归档请用 build_docx.py。

用法：
  python3 build_html.py 正文.txt -o 成稿.html [--layout 白头|红头|材料|便签] [--meta 版式信息.json] [--json]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import gw_layout  # noqa: E402

VALID_LAYOUTS = ("白头", "红头", "材料", "便签")
_PIPE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_PIPE_SEP_RE = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def read_body_lines(text: str) -> List[str]:
    """按行读取正文，遇到【起草说明】分界行停止，与 build_docx / gongwen_lint 口径一致。"""
    out: List[str] = []
    for line in text.splitlines():
        if gw_layout.is_draft_note_line(line):
            break
        out.append(line)
    return out


def _detect_layout(parsed: "gw_layout.ParsedDoc", meta: Dict[str, object], explicit: Optional[str]) -> str:
    if explicit:
        if explicit not in VALID_LAYOUTS:
            raise ValueError(f"不支持的 HTML 版式：{explicit}（可选：{'、'.join(VALID_LAYOUTS)}）")
        return explicit
    meta_layout = str(meta.get("版式") or meta.get("layout") or "").strip()
    if meta_layout in VALID_LAYOUTS:
        return meta_layout
    has_issuer = bool(meta.get("发文机关标志")) or any(it.role == "issuer" for it in parsed.items)
    if has_issuer:
        return "红头"
    has_recipient = any(it.role in ("recipient", "salutation") for it in parsed.items)
    if has_recipient:
        return "白头"
    return "材料"


def _render_heading(text: str, role: str, split: Optional[int]) -> str:
    end = len(text) if split is None or split < 0 else min(split, len(text))
    cls = f"gw-{role}"
    if end < len(text):
        head = _escape(text[:end])
        tail = _escape(text[end:])
        return f'<p class="gw-p gw-inline-heading"><span class="{cls}-inline">{head}</span>{tail}</p>'
    return f'<p class="gw-p {cls}">{_escape(text)}</p>'


def _render_pipe_table(rows: Sequence[str]) -> str:
    parsed_rows: List[List[str]] = []
    for raw in rows:
        if _PIPE_SEP_RE.match(raw):
            continue
        m = _PIPE_ROW_RE.match(raw)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        parsed_rows.append(cells)
    if not parsed_rows:
        return "".join(f'<p class="gw-p">{_escape(r)}</p>' for r in rows)
    html_rows: List[str] = []
    for idx, cells in enumerate(parsed_rows):
        tag = "th" if idx == 0 else "td"
        tds = "".join(f"<{tag}>{_escape(c)}</{tag}>" for c in cells)
        html_rows.append(f"<tr>{tds}</tr>")
    return '<table class="gw-table"><tbody>' + "".join(html_rows) + "</tbody></table>"


def _extract_meta_header(parsed: "gw_layout.ParsedDoc", meta: Dict[str, object]) -> Tuple[str, str, str]:
    issuer = str(meta.get("发文机关标志") or "").strip()
    if isinstance(meta.get("发文机关标志"), list):
        issuer = "\n".join(str(x).strip() for x in meta["发文机关标志"] if str(x).strip())
    docno = str(meta.get("发文字号") or "").strip()
    signer = str(meta.get("签发人") or "").strip()
    for it in parsed.items:
        if it.role == "issuer" and not issuer:
            issuer = it.text.strip()
        elif it.role == "docno" and not docno:
            docno = it.text.strip()
    return issuer, docno, signer


def _render_items(parsed: "gw_layout.ParsedDoc", meta: Dict[str, object]) -> Tuple[str, str, Dict[str, object]]:
    issuer, docno, signer = _extract_meta_header(parsed, meta)
    header_parts: List[str] = []
    if issuer:
        issuer_html = "<br>".join(_escape(ln) for ln in issuer.splitlines() if ln.strip())
    else:
        issuer_html = "（发文机关标志，点击可直接编辑）"
    header_parts.append(
        f'<div class="gw-issuer" contenteditable="true" title="红头版式下可直接点击修改">{issuer_html}</div>'
    )
    if docno or signer:
        if signer:
            header_parts.append(
                '<div class="gw-docno-row gw-docno-up">'
                f'<span class="gw-docno" contenteditable="true">{_escape(docno)}</span>'
                f'<span class="gw-signer" contenteditable="true">签发人：{_escape(signer)}</span>'
                "</div>"
            )
        else:
            header_parts.append(
                f'<div class="gw-docno-row"><span class="gw-docno" contenteditable="true">{_escape(docno)}</span></div>'
            )
    header_parts.append('<div class="gw-red-rule"></div>')
    header_html = '<header class="gw-redhead">' + "".join(header_parts) + "</header>"

    body_parts: List[str] = []
    title_text = ""
    counts: Dict[str, int] = {"title": 0, "h1": 0, "h2": 0, "h3": 0, "h4": 0, "body": 0, "table": 0}
    items = parsed.items
    i = 0
    while i < len(items):
        item = items[i]
        role = item.role
        text = item.text
        if role in ("blank", "issuer", "docno"):
            i += 1
            continue
        # 合并连续 Markdown 管道表格行
        if _PIPE_ROW_RE.match(text):
            tbl_rows: List[str] = []
            while i < len(items) and _PIPE_ROW_RE.match(items[i].text):
                tbl_rows.append(items[i].text)
                i += 1
            body_parts.append(_render_pipe_table(tbl_rows))
            counts["table"] += 1
            continue

        if role == "title":
            counts["title"] += 1
            if not title_text:
                title_text = text.strip()
            lines_broken = gw_layout.break_title(text)
            body_parts.append(
                '<h1 class="gw-title">' + "<br>".join(_escape(ln) for ln in lines_broken) + "</h1>"
            )
        elif role == "subtitle":
            body_parts.append(f'<p class="gw-subtitle">{_escape(text)}</p>')
        elif role == "title_note":
            body_parts.append(f'<p class="gw-title-note">{_escape(text)}</p>')
        elif role in ("recipient", "salutation"):
            body_parts.append(f'<p class="gw-recipient">{_escape(text)}</p>')
        elif role in ("h1", "h2", "h3", "h4"):
            counts[role] += 1
            body_parts.append(_render_heading(text, role, item.split))
        elif role == "attachment":
            cls = "gw-attachment gw-attachment-first" if item.first else "gw-attachment"
            body_parts.append(f'<p class="{cls}">{_escape(text)}</p>')
        elif role == "signature":
            body_parts.append(f'<p class="gw-signature">{_escape(text)}</p>')
        elif role == "date":
            body_parts.append(f'<p class="gw-date">{_escape(text)}</p>')
        elif role == "note":
            body_parts.append(f'<p class="gw-note">{_escape(text)}</p>')
        elif role in ("cc", "print", "banji_main"):
            cls = "gw-banji gw-banji-cc" if role == "cc" else "gw-banji"
            body_parts.append(f'<p class="{cls}">{_escape(text)}</p>')
        else:
            counts["body"] += 1
            body_parts.append(f'<p class="gw-p">{_escape(text)}</p>')
        i += 1

    # 版记补充（来自 meta 且正文未写）
    cc_meta = meta.get("抄送")
    print_org = str(meta.get("印发机关") or "").strip()
    print_date = str(meta.get("印发日期") or "").strip()
    if cc_meta or print_org or print_date:
        banji_parts: List[str] = ['<footer class="gw-banji-block">']
        if cc_meta:
            cc_str = "，".join(str(x).strip() for x in cc_meta) if isinstance(cc_meta, list) else str(cc_meta).strip()
            if cc_str:
                if not cc_str.startswith("抄送"):
                    cc_str = f"抄送：{cc_str}"
                if not cc_str.endswith("。"):
                    cc_str += "。"
                banji_parts.append(f'<p class="gw-banji gw-banji-cc">{_escape(cc_str)}</p>')
        if print_org or print_date:
            banji_parts.append(
                '<div class="gw-banji-print">'
                f"<span>{_escape(print_org)}</span>"
                f"<span>{_escape(print_date)}</span>"
                "</div>"
            )
        banji_parts.append("</footer>")
        body_parts.append("".join(banji_parts))

    return header_html, "\n".join(body_parts), {
        "title": title_text,
        "has_issuer": bool(issuer),
        "has_docno": bool(docno),
        "counts": counts,
    }


_CSS = """
@page {
  size: A4;
  margin: 37mm 26mm 35mm 28mm;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: #eceff3;
  color: #111;
  font-family: "FangSong_GB2312", "仿宋_GB2312", "FangSong", "仿宋", "STFangsong", "Songti SC", serif;
}
.gw-toolbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  background: #1b365d;
  color: #fff;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  font-size: 13.5px;
  box-shadow: 0 2px 6px rgba(0,0,0,.12);
}
.gw-toolbar .gw-brand { font-weight: 600; margin-right: 6px; }
.gw-toolbar button, .gw-toolbar select {
  padding: 5px 11px;
  border-radius: 4px;
  border: 1px solid rgba(255,255,255,.35);
  background: rgba(255,255,255,.12);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}
.gw-toolbar select option { color: #222; background: #fff; }
.gw-toolbar button:hover { background: rgba(255,255,255,.24); }
.gw-toolbar button.primary { background: #c0392b; border-color: #c0392b; font-weight: 600; }
.gw-toolbar button.primary:hover { background: #a93226; }
.gw-status { margin-left: auto; font-size: 12.5px; color: #dbe9ff; }
.gw-font-note {
  max-width: 210mm;
  margin: 12px auto 0;
  padding: 8px 14px;
  background: #fff8e6;
  border-left: 4px solid #d48806;
  color: #5c4300;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  font-size: 12.5px;
  line-height: 1.55;
}
.gw-canvas { padding: 14px 12px 36px; }
.gw-page {
  width: 210mm;
  min-height: 297mm;
  margin: 0 auto;
  padding: 37mm 26mm 35mm 28mm;
  background: #fff;
  box-shadow: 0 4px 18px rgba(0,0,0,.1);
  color: #000;
  font-size: 16pt;
  line-height: 28pt;
}
.gw-redhead { display: none; margin-bottom: 18pt; }
.gw-page[data-layout="红头"] .gw-redhead { display: block; }
.gw-issuer {
  text-align: center;
  color: #d60000;
  font-family: "FZXiaoBiaoSong-B05S", "方正小标宋简体", "STSong", "SimSun", serif;
  font-size: 32pt;
  line-height: 1.25;
  letter-spacing: 3pt;
  margin: 0 0 12pt;
}
.gw-docno-row {
  text-align: center;
  font-size: 16pt;
  line-height: 28pt;
  margin-bottom: 6pt;
}
.gw-docno-up {
  display: flex;
  justify-content: space-between;
  padding: 0 1em;
}
.gw-red-rule {
  border-bottom: 2.2pt solid #d60000;
  margin: 4pt 0 14pt;
}
.gw-title {
  margin: 0 0 28pt;
  text-align: center;
  font-family: "FZXiaoBiaoSong-B05S", "方正小标宋简体", "STSong", "SimSun", serif;
  font-size: 22pt;
  font-weight: normal;
  line-height: 30pt;
}
.gw-subtitle {
  margin: -18pt 0 24pt;
  text-align: center;
  font-family: "KaiTi_GB2312", "楷体_GB2312", "KaiTi", "楷体", serif;
  font-size: 16pt;
  line-height: 28pt;
}
.gw-title-note {
  margin: -16pt 0 24pt;
  text-align: center;
  font-size: 16pt;
  line-height: 28pt;
}
.gw-recipient {
  margin: 0;
  text-align: left;
  text-indent: 0;
}
.gw-p {
  margin: 0;
  text-indent: 2em;
  text-align: justify;
  word-break: break-all;
}
.gw-h1 {
  font-family: "SimHei", "黑体", "Heiti SC", sans-serif;
  break-after: avoid;
}
.gw-h2, .gw-h2-inline {
  font-family: "KaiTi_GB2312", "楷体_GB2312", "KaiTi", "楷体", serif;
}
.gw-h2 { break-after: avoid; }
.gw-h3, .gw-h3-inline, .gw-h4, .gw-h4-inline {
  font-family: "FangSong_GB2312", "仿宋_GB2312", "FangSong", "仿宋", serif;
  font-weight: 600;
}
.gw-attachment {
  margin: 0;
  padding-left: 5em;
  text-align: justify;
}
.gw-attachment-first {
  margin-top: 28pt;
  text-indent: -3em;
}
.gw-signature {
  margin: 28pt 0 0;
  padding-right: 4em;
  text-align: right;
  text-indent: 0;
}
.gw-date {
  margin: 0;
  padding-right: 4em;
  text-align: right;
  text-indent: 0;
}
.gw-note {
  margin: 14pt 0 0;
  text-indent: 2em;
  font-size: 15pt;
}
.gw-banji-block {
  margin-top: 36pt;
  border-top: 1.5pt solid #000;
  border-bottom: 1.5pt solid #000;
  padding: 4pt 0;
  font-size: 14pt;
  line-height: 24pt;
}
.gw-banji {
  margin: 0;
  padding: 2pt 1em;
  font-size: 14pt;
  line-height: 24pt;
  text-indent: 0;
}
.gw-banji-cc { border-bottom: 0.75pt solid #000; }
.gw-banji-print {
  display: flex;
  justify-content: space-between;
  padding: 2pt 1em;
}
.gw-table {
  width: 100%;
  border-collapse: collapse;
  margin: 10pt 0;
  font-size: 14pt;
  line-height: 22pt;
}
.gw-table th, .gw-table td {
  border: 0.75pt solid #222;
  padding: 4pt 6pt;
  text-align: left;
  vertical-align: top;
}
.gw-table th {
  background: #f5f5f5;
  font-family: "SimHei", "黑体", sans-serif;
  font-weight: normal;
  text-align: center;
}
/* 便签 / 内部简短通知版式：紧凑美观，适合贴门、OA、快捷打印 */
.gw-page[data-layout="便签"] {
  min-height: auto;
  padding: 22mm 20mm 22mm 20mm;
  font-size: 15pt;
  line-height: 26pt;
}
.gw-page[data-layout="便签"] .gw-title {
  font-size: 20pt;
  margin-bottom: 18pt;
  padding-bottom: 8pt;
  border-bottom: 1.2pt solid #222;
}
@media screen and (max-width: 820px) {
  .gw-page { width: 100%; min-height: auto; padding: 24px 18px; }
}
@media print {
  html, body { background: #fff !important; }
  .no-print { display: none !important; }
  .gw-canvas { padding: 0 !important; }
  .gw-page {
    width: auto !important;
    min-height: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    box-shadow: none !important;
  }
}
"""

_JS = """
(function(){
  var page = document.getElementById('gwPage');
  var sel = document.getElementById('layoutSel');
  var st = document.getElementById('gwStatus');
  var rawEl = document.getElementById('gwRawText');
  function tip(msg){ if(st) st.textContent = msg; }
  if(sel){
    sel.onchange = function(){
      page.setAttribute('data-layout', sel.value);
      tip('已切换为「' + sel.value + '」版式');
    };
  }
  document.getElementById('btnPrint').onclick = function(){ window.print(); };
  document.getElementById('btnCopyPlain').onclick = function(){
    var txt = rawEl ? rawEl.value : page.innerText;
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt).then(function(){ tip('已复制纯文本（可直接粘贴微信/OA）'); });
    } else {
      rawEl.style.display = 'block'; rawEl.select();
      try{ document.execCommand('copy'); tip('已复制纯文本'); }catch(e){ tip('请手动复制正文'); }
      rawEl.style.display = 'none';
    }
  };
  document.getElementById('btnCopyRich').onclick = function(){
    var range = document.createRange();
    range.selectNodeContents(document.getElementById('gwDocBody'));
    var s = window.getSelection();
    s.removeAllRanges(); s.addRange(range);
    try{
      document.execCommand('copy');
      s.removeAllRanges();
      tip('已复制富文本（可直接粘贴到 Word / WPS）');
    }catch(e){ tip('浏览器限制自动复制，请选中正文按 Ctrl+C'); }
  };
})();
"""


def build_html(
    lines: Sequence[str],
    meta: Optional[Dict[str, object]] = None,
    layout: Optional[str] = None,
) -> Tuple[str, Dict[str, object]]:
    """纯标准库把公文正文行渲染为单文件 HTML，返回 (html_str, report_dict)。"""
    cleaned = read_body_lines("\n".join(lines))
    if not any(x.strip() for x in cleaned):
        raise ValueError("正文为空，无法生成 HTML")
    meta_dict: Dict[str, object] = dict(meta or {})
    parsed = gw_layout.parse_lines(cleaned)
    chosen_layout = _detect_layout(parsed, meta_dict, layout)
    header_html, body_html, info = _render_items(parsed, meta_dict)

    doc_title = str(info["title"] or "公文通知")
    plain_text = "\n".join(cleaned).strip()
    options_html = "".join(
        f'<option value="{lv}"{" selected" if lv == chosen_layout else ""}>{lv}版式</option>'
        for lv in VALID_LAYOUTS
    )

    html_doc = (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_escape(doc_title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        '<div class="gw-toolbar no-print">'
        '<span class="gw-brand">公文轻排版（GB/T 9704 预览/打印）</span>'
        f'<select id="layoutSel" aria-label="切换版式">{options_html}</select>'
        '<button id="btnPrint" class="primary" type="button">打印 / 存为 PDF</button>'
        '<button id="btnCopyPlain" type="button">复制纯文本（微信/OA）</button>'
        '<button id="btnCopyRich" type="button">复制富文本（Word/WPS）</button>'
        '<span id="gwStatus" class="gw-status">零依赖单文件 · 打印时工具条自动隐藏</span>'
        "</div>\n"
        '<div class="gw-font-note no-print">'
        "字体说明：本页按 GB/T 9704-2012 声明方正小标宋简体、仿宋_GB2312、黑体、楷体_GB2312；"
        "如本机未安装对应字体，浏览器会用系统默认字体回退显示。日常通知、急件打印与发群可直接使用本页；"
        "正式红头送签归档请生成国标 .docx 并在已装标准字体的电脑核对。"
        "</div>\n"
        '<main class="gw-canvas">\n'
        f'<article id="gwPage" class="gw-page" data-layout="{_escape(chosen_layout)}">\n'
        f"{header_html}\n"
        f'<div id="gwDocBody">\n{body_html}\n</div>\n'
        "</article>\n"
        "</main>\n"
        f'<textarea id="gwRawText" style="display:none" aria-hidden="true">{_escape(plain_text)}</textarea>\n'
        f"<script>{_JS}</script>\n"
        "</body>\n</html>\n"
    )
    report: Dict[str, object] = {
        "mode": "html_lite",
        "layout": chosen_layout,
        "title": doc_title,
        "counts": info["counts"],
        "has_issuer": info["has_issuer"],
        "has_docno": info["has_docno"],
        "chars": len(plain_text),
    }
    return html_doc, report


def render_report(report: Dict[str, object]) -> str:
    c = report.get("counts") or {}
    lines = [
        f"已生成单文件 HTML 轻排版（版式：{report.get('layout')}，约 {report.get('chars')} 字）。",
        f"标题：{report.get('title') or '（未识别）'}",
        f"结构：一级标题 {c.get('h1', 0)}、二级 {c.get('h2', 0)}、三级 {c.get('h3', 0)}、正文段 {c.get('body', 0)}、表格 {c.get('table', 0)}。",
        "用法：双击用浏览器打开即可预览，支持一键打印/存为 PDF、复制纯文本（发微信/OA）或富文本（粘进 Word/WPS），以及页面内切换白头/红头/材料/便签版式。",
        "提示：HTML 版面向日常通知与快速打印；正式红头送签与 OA 归档请使用 build_docx.py 生成国标 .docx。",
    ]
    if report.get("output"):
        lines.insert(1, f"输出文件：{report['output']}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="生成单文件 GB/T 9704 轻量 HTML 公文页（零依赖，支持打印/存 PDF 与一键复制）。")
    ap.add_argument("input", type=Path, help="公文纯文本文件路径（.txt / .md）")
    ap.add_argument("-o", "--output", type=Path, help="输出 .html 路径（默认与输入同目录同名 .html）")
    ap.add_argument("--layout", choices=VALID_LAYOUTS, help="指定版式：白头、红头、材料、便签（默认按正文自动判断）")
    ap.add_argument("--meta", type=Path, help="可选版式信息 JSON（发文机关标志、发文字号、签发人、抄送等）")
    ap.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 格式输出报告")
    args = ap.parse_args(argv)

    if not args.input.is_file():
        print(f"输入文件不存在：{args.input}", file=sys.stderr)
        return 2
    meta: Dict[str, object] = {}
    if args.meta:
        if not args.meta.is_file():
            print(f"版式信息文件不存在：{args.meta}", file=sys.stderr)
            return 2
        try:
            meta = json.loads(args.meta.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print(f"版式信息 JSON 解析失败：{exc}", file=sys.stderr)
            return 2
    text = args.input.read_text(encoding="utf-8-sig")
    try:
        html_doc, report = build_html(text.splitlines(), meta=meta, layout=args.layout)
    except ValueError as exc:
        print(f"生成失败：{exc}", file=sys.stderr)
        return 1
    out_path = args.output or args.input.with_suffix(".html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    report["input"] = str(args.input)
    report["output"] = str(out_path)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
