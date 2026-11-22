#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机双向脱敏与还原网关（只依赖 Python 标准库，不联网）。

定位：
  面向允许在非涉密政务内网模型处理的常规材料，在送入大模型前于本机一键脱敏
  （身份证号、手机号、座机号、邮箱、统一社会信用代码及用户自定义人名/单位名），
  模型改稿后再在本机按映射表一键还原，映射表绝不出本机。

硬红线（强拦截）：
  若文本命中密级标识（绝密/机密/秘密★、保密期限）或“工作秘密”“内部资料”“不得外传”
  等内部标注，本工具直接拦截拒绝脱敏（退出码 3），防止将涉密材料经“脱敏”后流入非涉密网络。

用法：
  python shared/scripts/desensitize.py mask <输入.txt> -o <脱敏稿.txt> --map <映射表.json> [--terms "张三,某局"]
  python shared/scripts/desensitize.py restore <改稿.txt> --map <映射表.json> -o <还原稿.txt>

退出码：0 成功；2 输入或参数错误；3 命中涉密/内部标注，已强拦截。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import secret_check  # noqa: E402

EXIT_SECRET_BLOCKED = 3

# 自动识别的个人隐私与敏感标识规则（按优先顺序匹配，防止长号码被短规则截断）
AUTO_RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("身份证号", re.compile(r"(?<![0-9A-Za-z])[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9A-Za-z])")),
    ("统一社会信用代码", re.compile(r"(?<![0-9A-Za-z])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![0-9A-Za-z])")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("座机号", re.compile(r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)")),
    ("邮箱", re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9._%+-])")),
)


class SecretBlockedError(Exception):
    """命中密级标识或内部标注时抛出，禁止继续脱敏或送入非涉密模型。"""

    def __init__(self, hits: List[Tuple[str, str, str]]) -> None:
        self.hits = hits
        summary = "、".join(f"[{loc}]{kind}:{word}" for loc, kind, word in hits[:5])
        super().__init__(f"命中涉密或内部标注（{len(hits)} 处），已强拦截，禁止脱敏外发：{summary}")


@dataclass
class MaskResult:
    masked_text: str
    mapping: Dict[str, str] = field(default_factory=dict)  # placeholder -> original
    counts: Dict[str, int] = field(default_factory=dict)   # category -> unique count


@dataclass
class RestoreResult:
    restored_text: str
    restored_count: int
    missing_tokens: List[str] = field(default_factory=list)


def check_secret_text(text: str) -> List[Tuple[str, str, str]]:
    """复用 secret_check 规则对纯文本逐行检查保密标识。"""
    items = [(f"第{i}行", line) for i, line in enumerate(text.splitlines(), 1) if line.strip()]
    return secret_check.scan(items)


def parse_custom_terms(raw: Optional[str]) -> List[str]:
    """解析自定义敏感词（逗号、顿号、分号或换行分隔），去重并按长度降序排列。"""
    if not raw:
        return []
    seen = set()
    terms: List[str] = []
    for part in re.split(r"[,，;；、\r\n]+", raw):
        t = part.strip()
        if t and t not in seen:
            seen.add(t)
            terms.append(t)
    # 最长优先，避免“某市财政局”被“某市”提前截断
    terms.sort(key=len, reverse=True)
    return terms


def mask_text(text: str, custom_terms: Sequence[str] = ()) -> MaskResult:
    """对文本执行涉密强拦截 + 确定性双向脱敏。"""
    hits = check_secret_text(text)
    if hits:
        raise SecretBlockedError(hits)

    mapping: Dict[str, str] = {}
    reverse: Dict[str, str] = {}
    counts: Dict[str, int] = {}

    def alloc(category: str, value: str) -> str:
        if value in reverse:
            return reverse[value]
        idx = counts.get(category, 0) + 1
        counts[category] = idx
        token = f"【{category}{idx}】"
        mapping[token] = value
        reverse[value] = token
        return token

    out = text
    # 1. 自定义人名/单位名优先替换（最长优先）
    terms = sorted({t.strip() for t in custom_terms if t and t.strip()}, key=len, reverse=True)
    if terms:
        custom_rx = re.compile("|".join(re.escape(t) for t in terms))
        out = custom_rx.sub(lambda m: alloc("自定义词", m.group(0)), out)

    # 2. 内置隐私号码/标识规则
    for category, rx in AUTO_RULES:
        out = rx.sub(lambda m, cat=category: alloc(cat, m.group(0)), out)

    return MaskResult(masked_text=out, mapping=mapping, counts=counts)


def restore_text(text: str, mapping: Dict[str, str]) -> RestoreResult:
    """根据映射表把脱敏占位符逐项还原为原文，并报告丢失的占位符。"""
    if not mapping:
        return RestoreResult(restored_text=text, restored_count=0, missing_tokens=[])
    missing: List[str] = []
    restored_count = 0
    out = text
    for token, original in mapping.items():
        n = out.count(token)
        if n == 0:
            missing.append(token)
        else:
            out = out.replace(token, original)
            restored_count += n
    return RestoreResult(restored_text=out, restored_count=restored_count, missing_tokens=missing)


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")


def _write_secure_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        prog="desensitize.py",
        description="本机双向脱敏与还原网关（纯标准库，零联网；涉密标识强拦截）。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mask = sub.add_parser("mask", help="涉密检查并脱敏文本")
    p_mask.add_argument("input", type=Path, help="原稿文件（.txt / .md）")
    p_mask.add_argument("-o", "--output", type=Path, help="脱敏后输出文件（不填则打印到终端）")
    p_mask.add_argument("--map", dest="map_file", type=Path, required=True, help="本机保存的映射表 JSON 路径（切勿外传）")
    p_mask.add_argument("--terms", default="", help="额外需脱敏的人名/单位名，逗号或顿号分隔")
    p_mask.add_argument("--json", action="store_true", help="输出 JSON 摘要")

    p_rest = sub.add_parser("restore", help="按本机映射表一键还原脱敏稿")
    p_rest.add_argument("input", type=Path, help="模型改写后的脱敏文件")
    p_rest.add_argument("--map", dest="map_file", type=Path, required=True, help="脱敏时生成的本机映射表 JSON")
    p_rest.add_argument("-o", "--output", type=Path, help="还原后输出文件（不填则打印到终端）")
    p_rest.add_argument("--json", action="store_true", help="输出 JSON 摘要")

    args = parser.parse_args(argv)
    if not args.input.is_file():
        print(f"错误：找不到输入文件 {args.input}", file=sys.stderr)
        return 2

    if args.cmd == "mask":
        text = _read_text_file(args.input)
        try:
            res = mask_text(text, parse_custom_terms(args.terms))
        except SecretBlockedError as exc:
            if args.json:
                print(json.dumps({"blocked": True, "error": str(exc), "hits": exc.hits}, ensure_ascii=False, indent=2))
            else:
                print(f"[强拦截] {exc}", file=sys.stderr)
            return EXIT_SECRET_BLOCKED
        _write_secure_json(args.map_file, {"version": 1, "mapping": res.mapping})
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(res.masked_text, encoding="utf-8")
        if args.json:
            print(json.dumps({
                "blocked": False,
                "count": len(res.mapping),
                "counts": res.counts,
                "map_file": str(args.map_file),
                "output": str(args.output) if args.output else None,
            }, ensure_ascii=False, indent=2))
        else:
            if not args.output:
                print(res.masked_text)
            print(f"\n[脱敏完成] 共替换 {len(res.mapping)} 项，映射表已存本机：{args.map_file}（用完请销毁，切勿上传）",
                  file=sys.stderr)
        return 0

    if not args.map_file.is_file():
        print(f"错误：找不到映射表 {args.map_file}", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.map_file.read_text(encoding="utf-8"))
        mapping = data.get("mapping") if isinstance(data, dict) else None
        if not isinstance(mapping, dict):
            raise ValueError("mapping 字段缺失")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：读取映射表失败：{exc}", file=sys.stderr)
        return 2

    res = restore_text(_read_text_file(args.input), mapping)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(res.restored_text, encoding="utf-8")
    if args.json:
        print(json.dumps({
            "restored_count": res.restored_count,
            "missing_tokens": res.missing_tokens,
            "output": str(args.output) if args.output else None,
        }, ensure_ascii=False, indent=2))
    else:
        if not args.output:
            print(res.restored_text)
        msg = f"\n[还原完成] 共还原 {res.restored_count} 处"
        if res.missing_tokens:
            msg += f"；未在改稿中找到 {len(res.missing_tokens)} 个占位符（可能已被改写或删去）：{'、'.join(res.missing_tokens)}"
        print(msg, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
