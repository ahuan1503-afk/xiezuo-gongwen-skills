# -*- coding: utf-8 -*-
"""scripts/ofd_check.py：用内存里拼出的最小 OFD 包验证结构体检。"""
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from tests.format.helpers import SKILL  # noqa: F401  导入 helpers 时已把 scripts 加入 sys.path

import ofd_check  # noqa: E402

NS = 'xmlns:ofd="http://www.ofdspec.org/2016"'


def make_ofd(path, box='0 0 210 297', fonts=(('方正仿宋_GBK', True),), pages=1, keep_pages=True):
    font_xml = ''.join(
        '<ofd:Font ID="%d" FontName="%s">%s</ofd:Font>' % (i, name, '<ofd:FontFile>f%d.ttf</ofd:FontFile>' % i if emb else '')
        for i, (name, emb) in enumerate(fonts, 1))
    page_xml = ''.join('<ofd:Page ID="%d" BaseLoc="Pages/Page_%d/Content.xml"/>' % (i, i) for i in range(1, pages + 1))
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('OFD.xml', '<ofd:OFD %s><ofd:DocBody><ofd:DocRoot>Doc_0/Document.xml</ofd:DocRoot></ofd:DocBody></ofd:OFD>' % NS)
        zf.writestr('Doc_0/Document.xml',
                    '<ofd:Document %s><ofd:CommonData><ofd:PageArea><ofd:PhysicalBox>%s</ofd:PhysicalBox></ofd:PageArea>'
                    '<ofd:PublicRes>PublicRes.xml</ofd:PublicRes></ofd:CommonData><ofd:Pages>%s</ofd:Pages></ofd:Document>'
                    % (NS, box, page_xml))
        zf.writestr('Doc_0/PublicRes.xml', '<ofd:Res %s BaseLoc="Res"><ofd:Fonts>%s</ofd:Fonts></ofd:Res>' % (NS, font_xml))
        if keep_pages:
            for i in range(1, pages + 1):
                zf.writestr('Doc_0/Pages/Page_%d/Content.xml' % i, '<ofd:Page %s/>' % NS)


class OfdCheckTest(unittest.TestCase):

    def run_check(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '成稿.ofd'
            make_ofd(path, **kwargs)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = ofd_check.main([str(path), '--json'])
            return code, json.loads(buf.getvalue())

    def test_clean_package_passes(self):
        code, result = self.run_check(pages=2)
        self.assertEqual(code, 0)
        self.assertEqual(result['pages'], 2)
        self.assertEqual(result['page_size_mm'], [210.0, 297.0])
        self.assertEqual(result['summary'], {'P0': 0, 'P1': 0, 'P2': 0})
        self.assertFalse(result['signed'])

    def test_not_a4_is_p1(self):
        code, result = self.run_check(box='0 0 176 250')
        self.assertEqual(code, 1)
        self.assertEqual(result['summary']['P1'], 1)
        self.assertIn('A4', result['issues'][0]['message'])

    def test_fallback_font_is_p1(self):
        code, result = self.run_check(fonts=(('Noto Sans CJK SC', True),))
        self.assertEqual(code, 1)
        self.assertEqual(result['summary']['P1'], 1)

    def test_not_embedded_is_only_p2(self):
        code, result = self.run_check(fonts=(('方正仿宋_GBK', False),))
        self.assertEqual(code, 0)
        self.assertEqual(result['summary'], {'P0': 0, 'P1': 0, 'P2': 1})

    def test_missing_page_content_is_p0(self):
        code, result = self.run_check(keep_pages=False)
        self.assertEqual(code, 1)
        self.assertEqual(result['summary']['P0'], 1)

    def test_not_a_zip_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.ofd'
            path.write_text('不是 zip', encoding='utf-8')
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(ofd_check.main([str(path)]), 2)


if __name__ == '__main__':
    unittest.main()
