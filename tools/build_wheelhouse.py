# -*- coding: utf-8 -*-
'''维护者在能上网的机器上运行：为国产信创平台预下载 python-docx、openpyxl 及其依赖（含带 C 扩展的 lxml）的 wheel。

产物：wheelhouse/<架构>/py<版本>/*.whl，外加每个目录的 SHA256SUMS.txt 和中文 INSTALL.txt。
本文件不进离线包，不受零外联审计限制；只用标准库，pip 用列表参数调用，不经过 shell。
'''
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

NL = chr(10)
PACKAGES = ['python-docx', 'openpyxl', 'lxml']  # 版本不写死，传递依赖由 pip 自己解析
PYTHONS = ['3.9', '3.10', '3.11', '3.12']
ARCHS = ['x86_64', 'aarch64', 'loongarch64', 'win_amd64']
WHEELHOUSE = 'wheelhouse'
# 架构 -> pip --platform 标签；manylinux2014 即 manylinux_2_17，要求目标机 glibc >= 2.17
PLATFORMS: Dict[str, str] = {
    'x86_64': 'manylinux2014_x86_64',
    'aarch64': 'manylinux2014_aarch64',
    'win_amd64': 'win_amd64',
}
LOONGARCH = 'loongarch64'
# shortcut: loongarch64 不下载 wheel，改给系统包清单；PyPI 开始收 loongarch64 wheel 后，把它并进 PLATFORMS 即可。
# 2026-11-22 核实：PyPI 上 lxml 6.1.3 的 175 个 wheel 没有一个带 loongarch64 标签（只有 x86_64、aarch64、ppc64le、riscv64 等）；
# manylinux_2_38_loongarch64 已进 manylinux 项目，但据 discuss.python.org 讨论串，PyPI 尚未接受这类 wheel。
# 第三方索引 mirrors.loong64.com 列有 lxml，但它不是 PyPI、要联网、wheel 标签未核实，本工具不用。

INSTALL_TEMPLATE = '''离线安装说明：{arch}，Python {py}
本目录：wheelhouse/{arch}/py{py}

一、先确认版本和架构
    {pycmd} --version      应显示 Python {py}.x
    {archcmd}      应显示 {expect}
版本或架构对不上就不要用本目录，换成对应的 wheelhouse/<架构>/py<版本> 目录。

二、离线安装（全程不联网）
    {pycmd} -m pip install --no-index --find-links wheelhouse/{arch}/py{py} python-docx openpyxl
装完自检：
    {pycmd} -c "import docx, openpyxl, lxml"
没有报错即成功。

三、没有 pip 怎么办
    1. {pycmd} -m pip --version 报错时，先试 {pycmd} -m ensurepip --user（标准库自带，不联网）。
    2. 仍不行：{nopip}
    3. 实在装不了：wheel 本质是 zip，可以直接解压当库用：
       {pycmd} -c "import glob, zipfile; [zipfile.ZipFile(f).extractall('gw_site') for f in glob.glob('wheelhouse/{arch}/py{py}/*.whl')]"
       {setenv}
       然后在同一个终端里运行排版脚本。

四、lxml 装不上（安装报错，或 import lxml 失败）
lxml 带 C 扩展，对系统的 glibc 版本有要求，装不上时不要硬装，改用下面任一种：
    1. WPS 宏：skills/gongwen-format/assets/wps_gongwen_macro.js
    2. 工具箱自带的轻量排版（不依赖 lxml）

五、校验文件（可选）
    {verify}
'''

LOONGARCH_TEXT = '''龙芯（loongarch64）安装说明
PyPI 官方源目前没有 lxml 的 loongarch64 wheel，所以 wheelhouse 里没有龙芯的 whl 文件。
请从龙芯 Loongnix、统信 UOS 等系统自带的软件源安装系统包（包名以所用系统的软件源为准，先用 apt search lxml 或 dnf search lxml 确认）。

一、先确认架构
    uname -m               应显示 loongarch64
    python3 --version

二、从系统软件源安装（连单位内网软件源，或用挂载的离线软件源）
    Debian 系（Loongnix、统信 UOS）：sudo apt install python3-lxml python3-openpyxl python3-docx
    RPM 系（龙蜥 Anolis、openEuler 等）：sudo dnf install python3-lxml python3-openpyxl python3-docx
装完自检：
    python3 -c "import docx, openpyxl, lxml"
软件源里没有 python3-docx 时，请联系管理员补充，或改用下面的办法。

三、装不上时
    1. WPS 宏：skills/gongwen-format/assets/wps_gongwen_macro.js
    2. 工具箱自带的轻量排版（不依赖 lxml）
'''


def write_text(path: Path, text: str) -> None:
    '''统一以 UTF-8、LF 换行写入（Windows 上 write_text 会改成 CRLF）。'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def target_dir(out: Path, arch: str, py: str) -> Path:
    return out / arch / ('py' + py)


def pip_command(arch: str, py: str, dest: Path) -> List[str]:
    '''某平台 + Python 版本的 pip download 命令；--only-binary 保证只拿 wheel，不在本机编译。'''
    return [
        sys.executable, '-m', 'pip', 'download',
        '--only-binary=:all:',
        '--platform', PLATFORMS[arch],
        '--python-version', py,
        '--implementation', 'cp',
        '--abi', 'cp' + py.replace('.', ''),
        '--dest', str(dest),
    ] + PACKAGES


def write_checksums(dest: Path) -> None:
    '''SHA256SUMS.txt：sha256sum -c 可直接校验的标准格式，按文件名排序。'''
    lines = ['%s  %s' % (hashlib.sha256(w.read_bytes()).hexdigest(), w.name) for w in sorted(dest.glob('*.whl'))]
    write_text(dest / 'SHA256SUMS.txt', NL.join(lines) + NL)


def render_install(arch: str, py: str) -> str:
    win = arch == 'win_amd64'
    return INSTALL_TEMPLATE.format(
        arch=arch,
        py=py,
        pycmd='python' if win else 'python3',
        archcmd='echo %PROCESSOR_ARCHITECTURE%' if win else 'uname -m',
        expect='AMD64' if win else arch,
        nopip='换用自带 pip 的 Python 安装包。' if win else '从单位内网软件源安装系统包 python3-pip。',
        setenv='set PYTHONPATH=%CD%/gw_site' if win else 'export PYTHONPATH=$PWD/gw_site',
        verify=('certutil -hashfile <某个 whl 文件名> SHA256    与 SHA256SUMS.txt 里同名那一行对照' if win
                else 'cd wheelhouse/%s/py%s; sha256sum -c SHA256SUMS.txt' % (arch, py)),
    )


def build_target(arch: str, py: str, out: Path, dry_run: bool) -> bool:
    '''下载一个（架构, Python 版本）目标；成功才写校验和与说明。'''
    dest = target_dir(out, arch, py)
    cmd = pip_command(arch, py, dest)
    print('[%s py%s] %s' % (arch, py, subprocess.list2cmdline(cmd)))
    if dry_run:
        return True
    dest.mkdir(parents=True, exist_ok=True)
    code = subprocess.run(cmd, check=False).returncode
    if code != 0 or not list(dest.glob('*.whl')):
        print('失败：[%s py%s] pip 退出码 %d，未生成校验和与说明' % (arch, py, code), file=sys.stderr)
        return False
    write_checksums(dest)
    write_text(dest / 'INSTALL.txt', render_install(arch, py))
    return True


def collect_wheelhouse(repo_root) -> List[Tuple[str, Path]]:
    '''列出 repo_root/wheelhouse 下全部文件，供离线包构建收录：(zip 内 posix 路径, 磁盘路径)，按路径排序，跳过隐藏文件。'''
    base = Path(repo_root) / WHEELHOUSE
    if not base.is_dir():
        return []
    found = []
    for path in base.rglob('*'):
        parts = path.relative_to(base).parts
        if path.is_file() and not any(p.startswith('.') for p in parts):
            found.append((WHEELHOUSE + '/' + '/'.join(parts), path))
    return sorted(found, key=lambda item: item[0])


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='为国产信创平台预下载 python-docx / openpyxl / lxml 的 wheel（在能上网的机器上运行）')
    ap.add_argument('--arch', required=True, choices=ARCHS + ['all'])
    ap.add_argument('--python', action='append', choices=PYTHONS, help='Python 版本，可重复；缺省为全部')
    ap.add_argument('--out', default=WHEELHOUSE, help='输出目录，默认 wheelhouse')
    ap.add_argument('--dry-run', action='store_true', help='只打印命令，不下载、不写文件')
    args = ap.parse_args(argv)
    out = Path(args.out)
    archs = ARCHS if args.arch == 'all' else [args.arch]
    pythons = [p for p in PYTHONS if p in (args.python or PYTHONS)]
    failed = 0
    for arch in archs:
        if arch == LOONGARCH:
            print(LOONGARCH_TEXT)
            if not args.dry_run:
                write_text(out / arch / 'INSTALL.txt', LOONGARCH_TEXT)
            continue
        for py in pythons:
            if not build_target(arch, py, out, args.dry_run):
                failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
