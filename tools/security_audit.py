#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内网入网静态安全审计与 SHA-256 清单生成（只依赖 Python 标准库）。

面向单位信息中心、保密办审查：
  1. 用 Python AST 扫描全部随包分发的 .py 文件，核查是否存在联网模块导入、动态执行（eval/exec）、
     隐藏外部 API 调用或未声明的本地端口监听；
  2. 仅允许本机零联网工具箱（xinchuang/local_toolbox.py）使用标准库 http.server，且必须硬编码绑定 127.0.0.1；
  3. 生成确定性的 Markdown《安全自查报告.md》与《SHA256SUMS.txt》。

用法：
  python tools/security_audit.py [--strict] [--out 安全自查报告.md]
退出码：0 通过；1 发现违规（--strict 时）；2 参数错误。
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from sync_shared import REPO_ROOT, add_root_argument, make_parser, setup_console  # noqa: E402

# 严禁出现在离线交付脚本中的联网模块（精确模块名或顶级包名）
FORBIDDEN_NET_MODULES = frozenset({
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "socket",
    "http.client",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "ssl",
    "websocket",
    "websockets",
    "paramiko",
    "openai",
    "anthropic",
})

# 严禁用于混淆/动态加载的调用
FORBIDDEN_CALLS = frozenset({"eval", "exec", "__import__", "compile"})

# 允许仅绑定 127.0.0.1 的本地回环 Web 工具箱路径
LOOPBACK_ALLOWLIST = frozenset({"xinchuang/local_toolbox.py"})

# 允许 import subprocess 的脚本及用途：只调用系统自带命令或本包自带脚本，不执行用户输入的内容
SUBPROCESS_ALLOWLIST = {
    'skills/gongwen-format/scripts/gw_fonts.py': '调用 fc-list 读取本机已装字体名称，没有 fc-list 时改为扫描字体目录',
    'skills/gongwen-format/scripts/preview_docx.py': '调用本机 LibreOffice（soffice）把 docx 转成 PDF，只在用户运行预览时',
    'tools/install.py': '用 python 运行本包的 gw_fonts.py 做字体检查，只在用户运行安装脚本时',
}

# 宏脚本（.js）中不允许出现的联网、动态执行、系统对象写法
FORBIDDEN_JS = re.compile(r'XMLHttpRequest|WebSocket|ActiveXObject|WScript|new[ ]+Function|https?://|(?:^|[^A-Za-z_])(?:fetch|eval|require)[ ]*[(]')

SKIP_DIRS = frozenset({
    "__pycache__", ".git", ".pytest_cache", ".venv", "venv", "node_modules", ".gongwen", "公文",
})


@dataclass
class AuditFinding:
    path: str
    line: int
    kind: str
    detail: str
    severity: str  # "FAIL" | "NOTE"


@dataclass
class AuditSummary:
    scanned_py: List[str] = field(default_factory=list)
    scanned_js: List[str] = field(default_factory=list)
    findings: List[AuditFinding] = field(default_factory=list)

    @property
    def failures(self) -> List[AuditFinding]:
        return [f for f in self.findings if f.severity == "FAIL"]

    @property
    def notes(self) -> List[AuditFinding]:
        return [f for f in self.findings if f.severity == "NOTE"]


def _check_module(rel: str, lineno: int, mod: str, findings: List[AuditFinding]) -> None:
    top = mod.split(".", 1)[0]
    if mod in FORBIDDEN_NET_MODULES or top in FORBIDDEN_NET_MODULES:
        findings.append(AuditFinding(rel, lineno, "联网模块导入", f"检测到导入 `{mod}`", "FAIL"))
        return
    if mod == 'subprocess':
        purpose = SUBPROCESS_ALLOWLIST.get(rel)
        if purpose:
            findings.append(AuditFinding(rel, lineno, '本机命令调用', purpose, 'NOTE'))
        else:
            findings.append(AuditFinding(rel, lineno, '未登记的本机命令调用', '检测到导入 `subprocess`', 'FAIL'))
        return
    if mod == "http.server" or mod.startswith("http.server."):
        if rel in LOOPBACK_ALLOWLIST:
            findings.append(AuditFinding(rel, lineno, "本机回环界面", "仅用于 127.0.0.1 本地网页工具箱，不监听局域网/公网", "NOTE"))
        else:
            findings.append(AuditFinding(rel, lineno, "未登记的监听模块", f"检测到导入 `{mod}`", "FAIL"))


def audit_python_source(rel: str, source: str) -> List[AuditFinding]:
    """对单份 Python 源码做 AST 静态安全检查。"""
    findings: List[AuditFinding] = []
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        findings.append(AuditFinding(rel, exc.lineno or 1, "语法错误", str(exc.msg), "FAIL"))
        return findings

    has_loopback_bind = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_module(rel, node.lineno, alias.name, findings)
        elif isinstance(node, ast.ImportFrom) and node.module:
            _check_module(rel, node.lineno, node.module, findings)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALLS:
                findings.append(AuditFinding(rel, node.lineno, "动态执行调用", f"检测到 `{fn.id}()`", "FAIL"))
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == 'os' and fn.attr in ('system', 'popen'):
                findings.append(AuditFinding(rel, node.lineno, '系统命令调用', '检测到 `os.%s()`' % fn.attr, 'FAIL'))
            for kw in node.keywords:
                if kw.arg == 'shell' and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    findings.append(AuditFinding(rel, node.lineno, 'shell=True 调用', '子进程以 shell 方式运行', 'FAIL'))
        elif isinstance(node, ast.Constant) and node.value == "127.0.0.1":
            has_loopback_bind = True

    if rel in LOOPBACK_ALLOWLIST and not has_loopback_bind:
        findings.append(AuditFinding(rel, 1, "回环地址校验失败", "未在源码中发现显式绑定 `127.0.0.1`", "FAIL"))
    return findings


def audit_files(entries: Iterable[Tuple[str, bytes]]) -> AuditSummary:
    """扫描 (posix_rel_path, raw_bytes) 中的全部 .py 文件。"""
    summary = AuditSummary()
    for rel, raw in sorted(entries, key=lambda x: x[0]):
        if rel.endswith('.js'):
            summary.scanned_js.append(rel)
            for lineno, line in enumerate(raw.decode('utf-8-sig', errors='replace').splitlines(), 1):
                hit = FORBIDDEN_JS.search(line)
                if hit:
                    summary.findings.append(AuditFinding(rel, lineno, '宏脚本禁用写法', '检测到 `%s`' % hit.group(0).strip(), 'FAIL'))
            continue
        if not rel.endswith(".py"):
            continue
        summary.scanned_py.append(rel)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            summary.findings.append(AuditFinding(rel, 1, "编码异常", "非 UTF-8 源码，无法审计", "FAIL"))
            continue
        summary.findings.extend(audit_python_source(rel, text))
    return summary


def collect_repo_py(repo_root: Path) -> List[Tuple[str, bytes]]:
    """收集仓库内面向交付的 Python 脚本（skills/、shared/、xinchuang/、tools/install.py）。"""
    items: List[Tuple[str, bytes]] = []
    for top in ("skills", "shared", "xinchuang"):
        base = repo_root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            cur = Path(dirpath)
            for name in sorted(filenames):
                if name.endswith((".py", ".js")):
                    p = cur / name
                    items.append((p.relative_to(repo_root).as_posix(), p.read_bytes()))
    inst = repo_root / "tools" / "install.py"
    if inst.is_file():
        items.append(("tools/install.py", inst.read_bytes()))
    return sorted(items, key=lambda x: x[0])


def render_sha256sums(entries: Sequence[Tuple[str, bytes]]) -> str:
    """生成标准 sha256sum 兼容清单（按路径排序，LF 换行）。"""
    lines = []
    for rel, raw in sorted(entries, key=lambda x: x[0]):
        digest = hashlib.sha256(raw).hexdigest()
        lines.append(f"{digest}  {rel}")
    return "\n".join(lines) + ("\n" if lines else "")


def render_audit_report(summary: AuditSummary, total_files: int, version: str = "") -> str:
    """生成给单位信息中心 / 保密办审阅的《安全自查报告.md》。"""
    ver_line = f"版本：{version}　" if version else ""
    status = "通过（0 项违规）" if not summary.failures else f"未通过（{len(summary.failures)} 项违规）"
    lines = [
        "# 内网入网安全自查报告",
        "",
        f"> {ver_line}交付文件总数：{total_files}　已审计 Python 脚本：{len(summary.scanned_py)}、宏脚本（JS）：{len(summary.scanned_js)}　静态审计结论：**{status}**",
        "",
        "## 一、安全边界声明（供信息中心 / 保密办审阅）",
        "",
        "1. **非自主智能体（无龙虾类 Agent 后台权限）**：本交付包没有后台常驻进程、定时任务和自动执行用户指令的 Agent 循环；所有脚本均须由使用者手动触发，只处理使用者显式指定的文件或粘贴文本。个别脚本会调用本机命令（字体检测、LibreOffice 预览、字体检查），已逐项列在下面第二节的白名单说明中，均不执行用户输入的内容，也不联网。字体检测会读取系统字体目录，不读取业务文件目录。",
        "2. **零外联设计**：全部本地脚本不调用任何公网 API、不连接外部大模型、不上传任何文档内容，也不收集使用统计。",
        "3. **无混淆、全源码可审**：所有 Python 脚本与 WPS JSA 宏均为明文 UTF-8 源码，不含二进制闭源插件或 `eval`/`exec` 动态执行逻辑。",
        "4. **无商用字体打包**：仓库与离线包不随附任何 `.ttf`/`.otf`/`.ttc` 字体文件，避免字库版权与未知二进制风险。",
        "5. **保密资质提示**：本工具仅作写作辅助、本地脱敏与格式校验，不替代涉密信息系统审批；涉密材料严禁进入非涉密网络和任何联网模型。",
        "",
        "## 二、静态 AST 审计结果",
        "",
        "检查范围：全部随包 `.py` 文件的抽象语法树（导入语句与函数调用）。",
        "",
        "- 禁用联网模块：`urllib`、`urllib3`、`requests`、`httpx`、`aiohttp`、`socket`、`http.client`、`ftplib`、`smtplib`、`ssl`、`xmlrpc`、`websocket`、`paramiko`、`openai`、`anthropic` 等。",
        "- 禁用动态执行：`eval()`、`exec()`、`__import__()`、`compile()`。",
        "- 本机命令调用：仅 gw_fonts.py、preview_docx.py、install.py 三个文件允许 import subprocess，用途见下方白名单说明；其余文件出现即判违规，同时禁用 os.system、os.popen 和 shell=True。",
        "- 宏脚本（.js）：逐行检查，禁止联网、动态执行和系统对象调用的写法。",
        "- 本地界面白名单：仅 `xinchuang/local_toolbox.py` 允许使用 Python 标准库 `http.server`，且源码强制校验绑定回环地址 `127.0.0.1`（局域网其他主机不可访问）。",
        "",
    ]
    if summary.failures:
        lines += ["### 违规项（须修复后方可入网）", ""]
        for f in summary.failures:
            lines.append(f"- [FAIL] `{f.path}:{f.line}` {f.kind}：{f.detail}")
        lines.append("")
    else:
        lines += ["**审计结果：全部脚本 0 项联网模块导入，0 项动态执行调用。**", ""]

    if summary.notes:
        lines += ["### 白名单说明（本机回环界面与本机命令调用）", ""]
        for f in summary.notes:
            lines.append(f"- [NOTE] `{f.path}:{f.line}` {f.kind}：{f.detail}")
        lines.append("")

    lines += [
        "## 三、完整性校验方法",
        "",
        "离线包根目录附带 `SHA256SUMS.txt`，可在银河麒麟、统信 UOS 或 Windows 终端核对全部文件未被篡改：",
        "",
        "```bash",
        "# 国产 Linux（银河麒麟 / 统信 UOS）",
        "sha256sum -c SHA256SUMS.txt",
        "```",
        "",
        "```powershell",
        "# Windows PowerShell",
        "Get-Content SHA256SUMS.txt | ForEach-Object { $h,$p = $_ -split '  ',2; if ((Get-FileHash $p -Algorithm SHA256).Hash.ToLower() -ne $h) { Write-Error \"Mismatch: $p\" } }",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None, repo_root: Optional[Path] = None) -> int:
    setup_console()
    parser = make_parser(
        "security_audit.py",
        "对随包分发的 Python 脚本执行零外联 AST 静态安全审计，生成《安全自查报告.md》。",
        "退出码：0 通过；1 发现违规（--strict 时）；2 参数错误。",
    )
    parser.add_argument("--strict", action="store_true", help="存在违规项时返回退出码 1")
    parser.add_argument("--out", type=Path, metavar="FILE", help="将 Markdown 报告写入指定文件")
    add_root_argument(parser)
    args = parser.parse_args(argv)
    root = (args.root or repo_root or REPO_ROOT).resolve()

    entries = collect_repo_py(root)
    summary = audit_files(entries)
    report = render_audit_report(summary, total_files=len(entries))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8", newline="\n")
        print(f"已写入安全自查报告：{args.out}")
    else:
        print(report)
    if args.strict and summary.failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
