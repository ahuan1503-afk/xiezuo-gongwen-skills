#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OFD 版式文件结构体检（GB/T 33190-2016；只依赖标准库，只读，不联网）。

OFD 是 zip 包，内含 OFD.xml、Document.xml、各页 Content.xml 和资源文件。本脚本只查机器能查的结构项：
能否打开、页数、页面尺寸是否 A4、字体清单（是否嵌入、是否回退成 Linux 默认字体）、有无电子签章部件。
折行、红线、印章位置这类版面效果机检不了，仍须用 OFD 阅读器或打印核对。

用法：python ofd_check.py <文件.ofd> [--json]
退出码：0 无 P0、P1；1 有 P0 或 P1；2 文件无法读取。
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

MAX_XML = 50 * 1024 * 1024
A4_MM = (210.0, 297.0)
TOLERANCE_MM = 1.0
# 缺字体时 OFD 生成器常回退成这些 Linux 默认字体，说明标准公文字体没装或没写入
FALLBACK_FONTS = re.compile('思源|Noto|文泉驿|WenQuanYi|DejaVu|Droid|Liberation|Source Han|AR PL', re.I)
SIGN_PART = re.compile('(^|/)Signs?/')


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _find(el: ET.Element, name: str) -> List[ET.Element]:
    return [e for e in el.iter() if _local(e.tag) == name]


def _xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    if zf.getinfo(name).file_size > MAX_XML:
        raise ValueError('部件过大：' + name)
    return ET.fromstring(zf.read(name))


def _join(base: str, loc: str) -> str:
    loc = loc.strip()
    return posixpath.normpath(loc.lstrip('/') if loc.startswith('/') else posixpath.join(base, loc))


def _page_size(doc: ET.Element) -> Optional[tuple]:
    for box in _find(doc, 'PhysicalBox'):
        parts = (box.text or '').split()
        try:
            return float(parts[2]), float(parts[3])
        except (IndexError, ValueError):
            return None
    return None


def _finish(result: Dict) -> Dict:
    count = {'P0': 0, 'P1': 0, 'P2': 0}
    for issue in result['issues']:
        count[issue['level']] += 1
    result['summary'] = count
    return result


def check(path: Path) -> Dict:
    issues: List[Dict[str, str]] = []

    def add(level: str, message: str) -> None:
        issues.append({'level': level, 'message': message})

    result: Dict = {'file': path.name, 'pages': 0, 'page_size_mm': None, 'fonts': [], 'signed': False,
                    'issues': issues}
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if 'OFD.xml' not in names:
            add('P0', '缺少 OFD.xml，不是有效的 OFD 文件')
            return _finish(result)
        roots = [(e.text or '').strip() for e in _find(_xml(zf, 'OFD.xml'), 'DocRoot')]
        doc_path = _join('', roots[0]) if roots and roots[0] else ''
        if not doc_path or doc_path not in names:
            add('P0', 'OFD.xml 指向的 Document.xml 不存在：' + (doc_path or '未写 DocRoot'))
            return _finish(result)
        doc = _xml(zf, doc_path)
        base = posixpath.dirname(doc_path)
        pages = _find(doc, 'Page')
        result['pages'] = len(pages)
        if not pages:
            add('P0', 'Document.xml 中没有页面')
        gone = [p.get('BaseLoc', '') for p in pages if _join(base, p.get('BaseLoc', '')) not in names]
        if gone:
            add('P0', '缺少页面内容文件：' + '、'.join(gone[:3]) + ('等' if len(gone) > 3 else ''))
        size = _page_size(doc)
        if size is None:
            add('P2', 'Document.xml 未写页面尺寸（PhysicalBox），无法核对 A4')
        else:
            result['page_size_mm'] = list(size)
            if abs(size[0] - A4_MM[0]) > TOLERANCE_MM or abs(size[1] - A4_MM[1]) > TOLERANCE_MM:
                add('P1', '页面尺寸 %g×%g mm，不是 A4（210×297）；横排表页等有意设置的请人工确认' % size)
        fonts: Dict[str, bool] = {}
        for name in sorted(names):
            if not name.lower().endswith('.xml') or '/Pages/' in name:
                continue
            for font in _find(_xml(zf, name), 'Font'):
                fname = font.get('FontName') or font.get('FamilyName')
                if fname:
                    embedded = any(_local(c.tag) == 'FontFile' for c in font)
                    fonts[fname] = fonts.get(fname, False) or embedded
        result['fonts'] = [{'name': n, 'embedded': e} for n, e in fonts.items()]
        for fname, embedded in fonts.items():
            if FALLBACK_FONTS.search(fname):
                add('P1', '字体“%s”是 Linux 默认回退字体，标准公文字体可能没装或没写入' % fname)
            elif not embedded:
                add('P2', '字体“%s”未嵌入，在没装该字体的电脑上阅读会被替换；送归档或加盖电子印章的版本建议嵌入' % fname)
        if not fonts:
            add('P2', '未找到字体资源清单，无法核对字体')
        result['signed'] = any(SIGN_PART.search(n) for n in names)
    return _finish(result)


def render_text(r: Dict) -> str:
    s = r['summary']
    size = '%g×%g mm' % tuple(r['page_size_mm']) if r['page_size_mm'] else '未知'
    lines = ['OFD 体检：%s（%d 页，页面 %s，%s）' % (r['file'], r['pages'], size, '含签章部件' if r['signed'] else '无签章部件'),
             'P0 %d 处｜P1 %d 处｜P2 %d 处' % (s['P0'], s['P1'], s['P2'])]
    for f in r['fonts']:
        lines.append('  字体：%s（%s）' % (f['name'], '已嵌入' if f['embedded'] else '未嵌入'))
    for i in r['issues']:
        lines.append('[%s] %s' % (i['level'], i['message']))
    lines.append('机检只覆盖结构项；折行、红线、印章位置请用 OFD 阅读器或打印核对。')
    return '\n'.join(lines)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description='OFD 版式文件结构体检（页数、页面尺寸、字体嵌入、签章部件）。')
    ap.add_argument('file', type=Path, help='.ofd 文件')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出')
    args = ap.parse_args(argv)
    try:
        result = check(args.file)
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError, KeyError) as exc:
        print('[读取失败] %s：%s' % (args.file.name, exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_text(result))
    return 1 if result['summary']['P0'] or result['summary']['P1'] else 0


if __name__ == '__main__':
    sys.exit(main())
