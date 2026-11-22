# -*- coding: utf-8 -*-
'''tools/build_wheelhouse.py 的单元测试：pip 命令、--dry-run、目录产物、龙芯清单、collect_wheelhouse。'''
from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.tools.fixtures import run_quiet

import build_wheelhouse


def fake_pip(cmd, **kwargs):
    '''代替 pip download：往 --dest 目录里放两个假 wheel。'''
    dest = Path(cmd[cmd.index('--dest') + 1])
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'lxml-0-cp311-cp311-fake.whl').write_bytes(b'x')
    (dest / 'python_docx-0-py3-none-any.whl').write_bytes(b'abc')
    return mock.Mock(returncode=0)


def arg_after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


class PipCommandTest(unittest.TestCase):

    def test_command_flags(self):
        cmd = build_wheelhouse.pip_command('x86_64', '3.11', Path('out'))
        self.assertIn('--only-binary=:all:', cmd)
        self.assertEqual(arg_after(cmd, '--platform'), 'manylinux2014_x86_64')
        self.assertEqual(arg_after(cmd, '--python-version'), '3.11')
        self.assertEqual(arg_after(cmd, '--implementation'), 'cp')
        self.assertEqual(arg_after(cmd, '--abi'), 'cp311')
        self.assertEqual(arg_after(cmd, '--dest'), str(Path('out')))
        self.assertEqual(cmd[-3:], ['python-docx', 'openpyxl', 'lxml'])
        self.assertFalse([a for a in cmd if '==' in a])  # 版本交给 pip 解析

    def test_platform_tags(self):
        for arch, tag in [('aarch64', 'manylinux2014_aarch64'), ('win_amd64', 'win_amd64')]:
            cmd = build_wheelhouse.pip_command(arch, '3.9', Path('o'))
            self.assertEqual(arg_after(cmd, '--platform'), tag)
            self.assertEqual(arg_after(cmd, '--abi'), 'cp39')
            self.assertEqual(arg_after(cmd, '--python-version'), '3.9')


class MainTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wheelhouse-test-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), ignore_errors=True)

    def run_main(self, *argv):
        with mock.patch.object(build_wheelhouse.subprocess, 'run', side_effect=fake_pip) as run:
            code, text = run_quiet(build_wheelhouse.main, list(argv))
        return code, text, run

    def test_run_calls_pip_and_writes_files(self):
        code, _text, run = self.run_main('--arch', 'aarch64', '--python', '3.10', '--python', '3.11', '--out', str(self.tmp))
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            cmd = call.args[0]
            self.assertIsInstance(cmd, list)
            self.assertFalse(call.kwargs.get('shell'))
            self.assertIn('--platform', cmd)
            self.assertIn('--only-binary=:all:', cmd)
            self.assertIn('--python-version', cmd)
        dest = self.tmp / 'aarch64' / 'py3.10'
        sums = (dest / 'SHA256SUMS.txt').read_bytes().decode('utf-8').splitlines()
        self.assertEqual(sums, [
            '%s  lxml-0-cp311-cp311-fake.whl' % hashlib.sha256(b'x').hexdigest(),
            '%s  python_docx-0-py3-none-any.whl' % hashlib.sha256(b'abc').hexdigest(),
        ])
        install = (dest / 'INSTALL.txt').read_bytes().decode('utf-8')
        self.assertIn('python3 --version', install)
        self.assertIn('uname -m', install)
        self.assertIn('python3 -m pip install --no-index --find-links wheelhouse/aarch64/py3.10 python-docx openpyxl', install)
        self.assertIn('wps_gongwen_macro.js', install)
        self.assertTrue((self.tmp / 'aarch64' / 'py3.11' / 'INSTALL.txt').is_file())

    def test_windows_install_text(self):
        code, _text, _run = self.run_main('--arch', 'win_amd64', '--python', '3.11', '--out', str(self.tmp))
        self.assertEqual(code, 0)
        install = (self.tmp / 'win_amd64' / 'py3.11' / 'INSTALL.txt').read_bytes().decode('utf-8')
        self.assertIn('python --version', install)
        self.assertIn('--find-links wheelhouse/win_amd64/py3.11', install)
        self.assertIn('AMD64', install)

    def test_all_runs_every_pip_target_but_not_loongarch(self):
        code, _text, run = self.run_main('--arch', 'all', '--out', str(self.tmp))
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 3 * len(build_wheelhouse.PYTHONS))
        self.assertFalse((self.tmp / 'loongarch64' / 'py3.11').exists())

    def test_dry_run_does_not_call_subprocess(self):
        out = self.tmp / 'o'
        with mock.patch.object(build_wheelhouse.subprocess, 'run') as run:
            code, text = run_quiet(build_wheelhouse.main, ['--arch', 'all', '--python', '3.11', '--out', str(out), '--dry-run'])
        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertFalse(out.exists())
        self.assertIn('manylinux2014_x86_64', text)
        self.assertIn('win_amd64', text)
        self.assertIn('python3-lxml', text)

    def test_loongarch64_prints_system_packages_and_never_downloads(self):
        code, text, run = self.run_main('--arch', 'loongarch64', '--out', str(self.tmp))
        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertIn('python3-lxml', text)
        self.assertIn('python3-openpyxl', text)
        self.assertEqual(list((self.tmp / 'loongarch64').glob('*.whl')), [])
        self.assertIn('python3-lxml', (self.tmp / 'loongarch64' / 'INSTALL.txt').read_bytes().decode('utf-8'))

    def test_pip_failure_writes_no_install_files(self):
        with mock.patch.object(build_wheelhouse.subprocess, 'run', return_value=mock.Mock(returncode=1)):
            code, _text = run_quiet(build_wheelhouse.main, ['--arch', 'x86_64', '--python', '3.11', '--out', str(self.tmp)])
        self.assertEqual(code, 1)
        dest = self.tmp / 'x86_64' / 'py3.11'
        self.assertFalse((dest / 'INSTALL.txt').exists())
        self.assertFalse((dest / 'SHA256SUMS.txt').exists())


class CollectWheelhouseTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wheelhouse-collect-'))
        self.addCleanup(shutil.rmtree, str(self.tmp), ignore_errors=True)

    def test_missing_dir_returns_empty(self):
        self.assertEqual(build_wheelhouse.collect_wheelhouse(self.tmp), [])

    def test_sorted_posix_paths_and_hidden_skipped(self):
        names = [
            'x86_64/py3.11/a.whl',
            'aarch64/py3.10/b.whl',
            'aarch64/py3.10/SHA256SUMS.txt',
            'aarch64/py3.10/.DS_Store',
            '.hidden/x.whl',
        ]
        for name in names:
            path = self.tmp / 'wheelhouse' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'1')
        got = build_wheelhouse.collect_wheelhouse(self.tmp)
        self.assertEqual([z for z, _p in got], [
            'wheelhouse/aarch64/py3.10/SHA256SUMS.txt',
            'wheelhouse/aarch64/py3.10/b.whl',
            'wheelhouse/x86_64/py3.11/a.whl',
        ])
        for zip_path, disk in got:
            self.assertEqual(disk, self.tmp / zip_path)
            self.assertTrue(disk.is_file())


if __name__ == '__main__':
    unittest.main()
