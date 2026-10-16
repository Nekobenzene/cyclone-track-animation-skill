"""Verify authored intro copy without requiring assets or native libraries."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IntroCopyTests(unittest.TestCase):
    def test_configured_copy_is_verbatim(self):
        for relative in ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py'):
            tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
            nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ('intro_title', 'intro_name_line')]
            ns = {}
            exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, 'exec'), ns)
            for hypothetical in (False, True):
                for text in ('台风电母', '假想台风电母', '假想热带气旋电母',
                             '强台风电母', '超强台风电母',
                             'HYPOTHETICAL TYPHOON DIANMU', 'typhoon Dianmu', ''):
                    with self.subTest(renderer=relative, hypothetical=hypothetical, text=text):
                        ns['_S'] = dict(hypothetical=hypothetical, title=text, intro_line=text)
                        self.assertEqual(ns['intro_title'](), text)
                        self.assertEqual(ns['intro_name_line'](), text)
                        ns['_S']['intro_title'] = 'Custom intro'
                        self.assertEqual(ns['intro_title'](), 'Custom intro')
                        self.assertEqual(ns['_S']['title'], text)
                        ns['_S']['intro_title'] = ''
                        self.assertEqual(ns['intro_title'](), '')
                ns['_S'] = dict(hypothetical=hypothetical)
                self.assertEqual(ns['intro_title'](), 'hypoTC' if hypothetical else 'CYCLONE')
                self.assertEqual(ns['intro_name_line'](), '')


if __name__ == '__main__':
    unittest.main()
