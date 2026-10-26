"""Fixed-row season metadata regression tests, without media dependencies."""
import ast
import os
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class NumRowsTests(unittest.TestCase):
    def test_fixed_rows(self):
        source = ROOT / 'season/scripts/season_pass2.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('read_num_rows', 'read_stamp', 'read_jtwc')]
        ns = dict(os=os, re=re, parse_fix_time=lambda value: value)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), ns)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Num.txt'
            for text, number, stamp in [
                ('94W\n\n\n202620\n', None, None),
                ('94W\n01W\n20260101000000 # name\n202601\n', 1, '20260101000000'),
                ('94W\n\n\n202601\n20260101000000\n', None, None),
                ('94W\n13W\n20260804180000 # Kujira\n202614 202616\n20260809060000 # Peilou\n', 13, '20260804180000'),
                ('94W\n', None, None),
                ('\n15E\n\n202628\n', 15, None),
            ]:
                path.write_text(text, encoding='utf-8-sig')
                self.assertEqual(ns['read_jtwc'](path), number)
                self.assertEqual(ns['read_stamp'](path), stamp)
            path.write_text('94W\n-\n\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                ns['read_jtwc'](path)

if __name__ == '__main__':
    unittest.main()
