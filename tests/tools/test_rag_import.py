# -*- coding: utf-8 -*-
'''tools/build_prompts.py 的 RAG 知识库导入包（FastGPT、MaxKB、扣子）的单元测试。'''
from __future__ import annotations

import csv
import io
import re
import unittest

from tests.tools.fixtures import REPO_ROOT

import build_prompts

BOM = chr(0xFEFF)
BOM_BYTES = bytes([0xEF, 0xBB, 0xBF])
# 平台说明里不该出现：交接卡、转交、skill 名、脚本和参考资料路径
FORBIDDEN = re.compile(r'交接卡|转交|gongwen-|scripts/|references/')
# 总 README 切片清单里的一行：| `chunks/xx.md` | 主题 | 切片数 |
CHUNK_ROW = re.compile(r'^[|] `chunks/[^`]+` [|] [^|]+ [|] ([0-9]+) [|]$', re.M)
QA_CSV = {
    'fastgpt/qa-import.csv': build_prompts.FASTGPT_QA_HEADER,
    'maxkb/qa-import.csv': build_prompts.MAXKB_QA_HEADER,
}
PLATFORM_READMES = ('fastgpt/README.md', 'maxkb/README.md', 'coze/README.md')


class RagImportTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = build_prompts.build_rag_kb(REPO_ROOT)
        cls.chunk_total = sum(int(n) for n in CHUNK_ROW.findall(cls.out[build_prompts.INDEX_NAME]))

    def read_rows(self, name):
        text = self.out[name]
        self.assertTrue(text.startswith(BOM), name)
        self.assertEqual(text.encode('utf-8')[:3], BOM_BYTES, name)
        return list(csv.reader(io.StringIO(text[1:], newline='')))

    def test_qa_csv_matches_platform_format(self):
        self.assertGreater(self.chunk_total, 0)
        for name, header in QA_CSV.items():
            rows = self.read_rows(name)
            self.assertEqual(tuple(rows[0]), header, name)
            data = rows[1:]
            self.assertGreater(len(data), 0, name)
            self.assertEqual(len(data), self.chunk_total, name)
            for row in data:
                self.assertEqual(len(row), len(header), name)
                self.assertTrue(all(cell.strip() for cell in row), name)
                self.assertTrue(row[1].startswith('[知识来源：'), name)

    def test_fastgpt_and_maxkb_share_the_same_pairs(self):
        fast = self.read_rows('fastgpt/qa-import.csv')[1:]
        maxkb = self.read_rows('maxkb/qa-import.csv')[1:]
        self.assertEqual([(r[0], r[1]) for r in fast], [(r[0], r[1]) for r in maxkb])

    def test_every_output_uses_lf(self):
        for name, text in self.out.items():
            self.assertNotIn(chr(13), text, name)

    def test_output_is_deterministic(self):
        self.assertEqual(build_prompts.build_rag_kb(REPO_ROOT), self.out)

    def test_platform_readmes_are_clean(self):
        for name in PLATFORM_READMES:
            text = self.out[name]
            self.assertTrue(text.strip(), name)
            self.assertIsNone(FORBIDDEN.search(text), name)

    def test_readmes_give_separator_and_length(self):
        for name in ('maxkb/README.md', 'coze/README.md'):
            self.assertIn('---', self.out[name], name)
            self.assertIn(str(build_prompts.RAG_SPLIT_LEN), self.out[name], name)

    def test_root_readme_has_platform_table(self):
        readme = self.out[build_prompts.INDEX_NAME]
        for needle in ('Dify', 'FastGPT', 'MaxKB', '扣子', 'fastgpt/qa-import.csv', 'maxkb/qa-import.csv', 'dify-app-template.yml'):
            self.assertIn(needle, readme)


if __name__ == '__main__':
    unittest.main()
