# -*- coding: utf-8 -*-
'''信创字体适配：Linux 字体目录兜底扫描、方正 GBK 预设、严格模式不回退，以及工具箱的字体自检按钮。'''
import base64
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.format.helpers import SKILL  # noqa: F401  导入时已把 scripts 加入 sys.path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'xinchuang'))

import gw_fonts  # noqa: E402
import local_toolbox as tb  # noqa: E402


class LinuxFontScanTest(unittest.TestCase):

    def setUp(self):
        for patcher in (mock.patch.object(gw_fonts.platform, 'system', return_value='Linux'),
                        mock.patch.object(gw_fonts, '_scan_fc_list', return_value=(set(), False))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, gw_fonts, '_CACHE', None)

    def scan(self, root):
        with mock.patch.object(gw_fonts, 'font_dirs', return_value=[root]):
            return gw_fonts.installed_fonts(refresh=True)

    def test_recursive_scan_finds_font_without_fc_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / 'fangzheng'
            nested.mkdir()
            (nested / '方正仿宋_GBK.ttf').write_bytes(b'')
            names, method = self.scan(Path(tmp))
        self.assertTrue(gw_fonts.is_installed('方正仿宋_GBK', names))
        self.assertFalse(gw_fonts.is_installed('方正楷体_GBK', names))
        self.assertIn('信创字体目录', method)

    def test_empty_dirs_means_undetected(self):
        with tempfile.TemporaryDirectory() as tmp:
            names, method = self.scan(Path(tmp))
        self.assertEqual(names, set())
        self.assertIn('无法检测', method)


class PresetTest(unittest.TestCase):

    def setUp(self):
        self.params = gw_fonts.load_params()

    def test_presets_cover_exactly_the_standard_roles(self):
        roles = set(self.params['fonts']['standard'])
        for key, preset in gw_fonts.UNIT_FONT_PRESETS.items():
            self.assertEqual(set(preset), roles, key)

    def test_preset_parsed(self):
        got = gw_fonts.parse_unit_fonts('preset:fangzheng-gbk', self.params)
        self.assertEqual(got['仿宋'], '方正仿宋_GBK')
        self.assertEqual(got['小标宋'], '方正小标宋_GBK')

    def test_unknown_preset_rejected(self):
        with self.assertRaises(ValueError):
            gw_fonts.parse_unit_fonts('preset:nope', self.params)

    def test_missing_preset_font_is_reported_not_replaced(self):
        unit = gw_fonts.parse_unit_fonts('preset:fangzheng-gbk', self.params)
        params = gw_fonts.apply_unit_fonts(self.params, unit)
        fonts, check = gw_fonts.resolve_fonts(params, {gw_fonts.norm('方正仿宋_GBK')}, 'test')
        self.assertEqual(fonts['仿宋'], '方正仿宋_GBK')
        self.assertEqual(check['font_status'], 'missing')
        missing = {e['font'] for e in check['missing_fonts']}
        self.assertNotIn('方正仿宋_GBK', missing)
        self.assertIn('方正小标宋_GBK', missing)


class ToolboxFontsTest(unittest.TestCase):

    def test_undetected_is_not_ok(self):
        with mock.patch.object(gw_fonts, 'installed_fonts', return_value=(set(), '测试')):
            res = tb.op_fonts({})
        self.assertFalse(res['ok'])
        self.assertIn('无法检测', res['text'])

    def test_complete_is_ok(self):
        standard = gw_fonts.load_params()['fonts']['standard'].values()
        have = {gw_fonts.norm(f) for f in standard}
        with mock.patch.object(gw_fonts, 'installed_fonts', return_value=(have, '测试')):
            res = tb.op_fonts({})
        self.assertTrue(res['ok'])


try:
    import docx
except ImportError:
    docx = None

NL = chr(10)
SAMPLE = NL.join(['关于加强窗口管理的通知', '', '各科室：', '', '请于本周五前完成自查。', '', '某区政务服务中心', '2026年11月20日', ''])


@unittest.skipUnless(docx, '没有 python-docx')
class ToolboxFormatTest(unittest.TestCase):

    def test_returns_openable_docx_with_text(self):
        res = tb.op_format({'b': SAMPLE})
        self.assertTrue(res['ok'], res['text'])
        doc = docx.Document(io.BytesIO(base64.b64decode(res['docx'])))
        self.assertIn('请于本周五前完成自查', NL.join(p.text for p in doc.paragraphs))

    def test_empty_body_refused(self):
        self.assertFalse(tb.op_format({'b': '  '})['ok'])

    def test_body_lines_match_read_body_text(self):
        from gw_layout import read_body_text
        text = SAMPLE + NL.join(['【起草说明】', '不排版的内容', ''])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '正文.txt'
            path.write_text(text, encoding='utf-8')
            expected, _notes = read_body_text(path)
        self.assertEqual(tb.body_lines(text), expected)


if __name__ == '__main__':
    unittest.main()
