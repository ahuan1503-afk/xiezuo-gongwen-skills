#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国产/政务内网大模型信创提示词防线回归评测脚本（只依赖 Python 标准库）。

用途：
  在国产主力模型（DeepSeek / Qwen / 豆包）或单位内网自建 OpenAI 兼容模型（vLLM / Ollama /
  SGLang / 昇腾 MindIE 等）上，抽测 dist/prompts-lite/ 与 dist/prompts-bundles/ 的核心防线：
  涉密拦截、内部资料拦截、缺项标【待补】防编造、脱敏占位符 100% 保留、亲历材料不代笔、
  纯文本无 Markdown、控字数去 AI 腔、八关核稿检出硬伤、整改台账如实对账。

注意：
  本脚本位于 evals/ 下，用于开发与单位上线前验收，不随离线包分发。
  所有密钥仅在内存使用并脱敏，绝不打印或写入报告。

用法：
  # 1. 仅校验用例与提示词加载（不联网）
  python3 evals/xinchuang/smoke_eval.py --dry-run

  # 2. 用仓库根目录的 deepseek.key.local / qwen.key.local / doubao.key.local 实测
  python3 evals/xinchuang/smoke_eval.py --provider deepseek [--model deepseek-chat]

  # 3. 测单位内网私有化模型（OpenAI 兼容接口）
  python3 evals/xinchuang/smoke_eval.py --base-url http://10.0.0.10:8000/v1 --model deepseek-r1-32b [--api-key-env INTRANET_API_KEY]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).resolve().parent / "cases.json"
DEFAULT_TIMEOUT = 120

# 与 tools/corpus/llm_client.py 保持一致的国产厂商默认配置
PROVIDERS: Dict[str, Dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "key_file": "deepseek.key.local",
        "model": "deepseek-chat",
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_file": "qwen.key.local",
        "model": "qwen-plus",
    },
    "doubao": {
        "label": "豆包",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_file": "doubao.key.local",
        "model": "doubao-seed-2.1-lite",
    },
}

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S | re.I)
DRAFT_NOTE_RE = re.compile(r"(?m)^\s*(?:#{1,6}\s*|\*\*\s*)?【起草说明】")
MD_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s+\S")
MD_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*")
MD_FENCE_RE = re.compile(r"(?m)^\s*```")


def load_cases(path: Path = CASES_PATH) -> List[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return list(data["cases"])


def strip_thinking(text: str) -> Tuple[str, int]:
    """移除 DeepSeek-R1 / QwQ 等推理模型的 <think>...</think> 思考段，返回 (正文回复, 思考字数)。"""
    thinking_chars = sum(len(m.group(0)) for m in THINK_RE.finditer(text))
    cleaned = THINK_RE.sub("", text).strip()
    return cleaned, thinking_chars


def split_body(reply: str) -> str:
    """提取【起草说明】之前的正文部分，口径与公文写作红线一致。"""
    m = DRAFT_NOTE_RE.search(reply)
    return reply[: m.start()].strip() if m else reply.strip()


def evaluate_reply(case: dict, raw_reply: str) -> Dict[str, object]:
    """对单条模型回复执行确定性机检，返回结构化评分结果。"""
    reply, think_chars = strip_thinking(raw_reply)
    body = split_body(reply)
    checks = case.get("checks") or {}
    failures: List[str] = []

    for needle in checks.get("must_contain", []):
        if needle not in reply:
            failures.append(f"回复缺少必需文本：{needle}")

    any_list = checks.get("must_match_any") or []
    if any_list and not any(k in reply for k in any_list):
        failures.append(f"回复未命中任一预期关键词：{'/'.join(any_list)}")

    mc = checks.get("must_match_count")
    if isinstance(mc, dict):
        pats = mc.get("patterns") or []
        min_hits = int(mc.get("min_hits", 1))
        hits = sum(1 for p in pats if re.search(p, reply))
        if hits < min_hits:
            failures.append(f"关键检出项仅命中 {hits}/{len(pats)}（要求 >= {min_hits}）")

    for needle in checks.get("body_must_contain", []):
        if needle not in body:
            failures.append(f"正文缺少必需文本：{needle}")

    for bad in checks.get("body_must_not_contain", []):
        if bad in body:
            failures.append(f"正文出现禁用/违规内容：{bad}")

    for pat in checks.get("body_must_not_regex", []):
        m = re.search(pat, body)
        if m:
            failures.append(f"正文疑似编造或违规命中正则 `{pat}`：{m.group(0)}")

    if checks.get("body_no_markdown"):
        if MD_HEADING_RE.search(body):
            failures.append("正文出现 Markdown 标题（#）")
        if MD_BOLD_RE.search(body):
            failures.append("正文出现 Markdown 加粗（**）")
        if MD_FENCE_RE.search(body):
            failures.append("正文出现 Markdown 代码块（```）")

    max_chars = checks.get("max_body_chars")
    if isinstance(max_chars, int) and len(body) > max_chars:
        failures.append(f"正文共 {len(body)} 字，超过上限 {max_chars} 字")

    return {
        "id": case["id"],
        "name": case["name"],
        "prompt_file": case["prompt_file"],
        "passed": len(failures) == 0,
        "failures": failures,
        "body_chars": len(body),
        "reply_chars": len(reply),
        "think_chars": think_chars,
        "reply_preview": reply[:260].replace("\n", " "),
    }


def _read_key_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"未找到密钥文件：{path.name}")
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    m = re.search(r"\bsk-[A-Za-z0-9_-]{8,}\b", raw)
    if m:
        return m.group(0)
    for line in raw.splitlines():
        val = line.strip()
        if val and not val.startswith("#") and not val.startswith("http"):
            return val.split("=", 1)[-1].strip().strip("\"'") if "=" in val else val
    raise ValueError(f"密钥文件为空或未找到有效密钥：{path.name}")


def call_openai_chat(
    *,
    base_url: str,
    model: str,
    api_key: Optional[str],
    system_prompt: str,
    user_message: str,
    system_mode: str = "system",
    temperature: float = 0.2,
    timeout: int = DEFAULT_TIMEOUT,
) -> Tuple[str, float]:
    """调用 OpenAI 兼容 /chat/completions 接口（只用标准库 urllib）。"""
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    if system_mode == "first-message":
        messages = [
            {"role": "user", "content": system_prompt + "\n\n---\n\n请严格按以上全部规范处理下面需求：\n" + user_message}
        ]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    headers = {"Content-Type": "application/json", "User-Agent": "dyz-gongwen-xinchuang-eval/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        if api_key:
            detail = detail.replace(api_key, "***")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"连接失败：{exc.reason}") from None
    elapsed = time.monotonic() - t0

    obj = json.loads(raw)
    choices = obj.get("choices") or []
    if not choices:
        raise RuntimeError("响应缺少 choices 字段")
    msg = choices[0].get("message") or {}
    content = str(msg.get("content") or "")
    return content, elapsed


def render_markdown_report(
    *,
    target_label: str,
    model: str,
    system_mode: str,
    results: Sequence[Dict[str, object]],
    run_date: str,
) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    lines = [
        f"# 国产/内网模型信创提示词防线抽测报告（{target_label}）",
        "",
        f"- 测试日期：{run_date}",
        f"- 被测模型：`{model}`（提示词注入方式：`{system_mode}`）",
        f"- 通过率：**{passed}/{total}**（{passed * 100 // total if total else 0}%）",
        "",
        "## 逐项结果",
        "",
        "| 编号 | 场景 | 提示词文件 | 耗时 | 正文字数 | 结果 | 说明 |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for r in results:
        status = "通过" if r["passed"] else "未通过"
        elapsed = f"{r.get('elapsed_s', 0.0):.1f}s"
        detail = "全部防线命中" if r["passed"] else "；".join(r["failures"])  # type: ignore[arg-type]
        lines.append(
            f"| {r['id']} | {r['name']} | `{r['prompt_file']}` | {elapsed} | {r['body_chars']} | **{status}** | {detail} |"
        )
    lines.append("")
    failed = [r for r in results if not r["passed"]]
    if failed:
        lines += ["## 未通过用例回复摘录", ""]
        for r in failed:
            lines.append(f"### {r['id']} {r['name']}")
            lines.append(f"- 失败项：{'；'.join(r['failures'])}")  # type: ignore[arg-type]
            lines.append(f"- 回复摘录：{r['reply_preview']}")
            lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="国产/内网模型信创提示词防线回归评测（纯标准库）。")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), help="使用预设国产厂商（读取根目录 <provider>.key.local）")
    ap.add_argument("--base-url", help="自定义内网 OpenAI 兼容接口地址，如 http://10.0.0.10:8000/v1")
    ap.add_argument("--model", help="模型名称（覆盖默认型号）")
    ap.add_argument("--api-key-env", default="", help="可选：从指定环境变量读取 API Key（内网免鉴权时留空）")
    ap.add_argument("--system-mode", choices=("system", "first-message"), default="system",
                    help="提示词放入 system 消息（默认）或拼入首条 user 消息（模拟无系统提示词框的网页平台）")
    ap.add_argument("--only", action="append", help="只跑指定用例 ID，可重复，如 --only XC-01")
    ap.add_argument("--out", type=Path, help="将 Markdown 报告写入指定路径")
    ap.add_argument("--json-out", type=Path, help="将完整 JSON 结果写入指定路径")
    ap.add_argument("--dry-run", action="store_true", help="只检查用例与提示词文件是否存在，不发网络请求")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单次请求超时秒数")
    args = ap.parse_args(argv)

    cases = load_cases()
    if args.only:
        wanted = set(args.only)
        cases = [c for c in cases if c["id"] in wanted]
        if not cases:
            print("错误：--only 未匹配到任何用例。", file=sys.stderr)
            return 2

    # 校验所有提示词文件存在
    prompt_texts: Dict[str, str] = {}
    for c in cases:
        p = REPO / c["prompt_file"]
        if not p.is_file():
            print(f"错误：缺少提示词文件 {c['prompt_file']}，请先运行 python tools/build_prompts.py --xinchuang", file=sys.stderr)
            return 2
        prompt_texts[c["id"]] = p.read_text(encoding="utf-8-sig")

    if args.dry_run:
        print(f"演练通过：共校验 {len(cases)} 条信创回归用例，全部提示词文件就绪。")
        for c in cases:
            print(f"  - {c['id']} {c['name']}（{c['prompt_file']}，{len(prompt_texts[c['id']])} 字）")
        return 0

    if not args.provider and not args.base_url:
        print("错误：请指定 --provider 或 --base-url（或加 --dry-run 演练）。", file=sys.stderr)
        return 2

    api_key: Optional[str] = None
    if args.provider:
        cfg = PROVIDERS[args.provider]
        base_url = args.base_url or cfg["base_url"]
        model = args.model or cfg["model"]
        target_label = cfg["label"]
        try:
            api_key = os.environ.get(args.api_key_env) if args.api_key_env else _read_key_file(REPO / cfg["key_file"])
        except (OSError, ValueError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
    else:
        base_url = args.base_url
        model = args.model or ""
        if not model:
            print("错误：使用 --base-url 时必须同时指定 --model。", file=sys.stderr)
            return 2
        target_label = "内网自定义模型"
        api_key = os.environ.get(args.api_key_env) if args.api_key_env else None

    results: List[Dict[str, object]] = []
    for c in cases:
        print(f"[{c['id']}] {c['name']} ...", end=" ", flush=True)
        try:
            reply, elapsed = call_openai_chat(
                base_url=base_url,
                model=model,
                api_key=api_key,
                system_prompt=prompt_texts[c["id"]],
                user_message=c["user_message"],
                system_mode=args.system_mode,
                timeout=args.timeout,
            )
            scored = evaluate_reply(c, reply)
            scored["elapsed_s"] = round(elapsed, 2)
            scored["raw_reply"] = reply
        except Exception as exc:
            scored = {
                "id": c["id"],
                "name": c["name"],
                "prompt_file": c["prompt_file"],
                "passed": False,
                "failures": [f"调用异常：{exc}"],
                "body_chars": 0,
                "reply_chars": 0,
                "think_chars": 0,
                "elapsed_s": 0.0,
                "reply_preview": "",
                "raw_reply": "",
            }
        print(("PASS" if scored["passed"] else "FAIL") + f" ({scored['elapsed_s']}s)")
        if not scored["passed"]:
            for f in scored["failures"]:  # type: ignore[union-attr]
                print(f"    -> {f}")
        results.append(scored)

    today = dt.date.today().isoformat()
    report_md = render_markdown_report(
        target_label=target_label,
        model=model,
        system_mode=args.system_mode,
        results=results,
        run_date=today,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report_md, encoding="utf-8", newline="\n")
        print(f"已写入报告：{args.out}")
    else:
        print("\n" + report_md)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps({"model": model, "date": today, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
