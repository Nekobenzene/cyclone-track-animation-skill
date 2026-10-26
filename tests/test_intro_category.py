"""Intro categories follow actual phases, basin and strict wind thresholds."""
import ast
from pathlib import Path
import re
from datetime import datetime
from types import SimpleNamespace
import unittest


class IntroCategoryTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'single/scripts/typhoon_anim.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('chinese_cyclone_prefix', 'intro_name_line')]
        self.ns = {'re': re, '_S': {}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.ns)

    def classify(self, phases, winds, lon=140, lat=15):
        self.ns['S'] = SimpleNamespace(phase=phases, wind=winds,
                                      lon=[lon]*len(phases), lat=[lat]*len(phases),
                                      t0=datetime(2026, 10, 10))
        return self.ns['chinese_cyclone_prefix'](self.ns['S'])

    def test_thresholds(self):
        for wind, expected in [(33,'热带低压'),(34,'热带风暴'),(63,'热带风暴'),
                               (64,'台风'),(112,'台风'),(113,'超强台风'),
                               (154,'超强台风'),(155,'顶级超强台风'),
                               (169,'顶级超强台风'),(170,'超顶级超强台风')]:
            with self.subTest(wind=wind):
                self.assertEqual(self.classify(['TC'], [wind]), expected)

    def test_basins(self):
        for lon, lat, kind in [(140,15,'台风'),(-60,20,'飓风'),(-140,15,'飓风'),
                               (80,15,'旋风'),(140,-15,'旋风')]:
            self.assertEqual(self.classify(['TC'],[120],lon,lat),'超强'+kind)

    def test_phase_priority_and_tc_only_peak(self):
        for phases, expected in [(['DB','EX','SS'],'副热带气旋'),
                                 (['DB','EX'],'温带气旋'),(['DB','RV'],'扰动')]:
            self.assertEqual(self.classify(phases,[180]*len(phases)),expected)
        self.assertEqual(self.classify(['TC','EX'],[30,180]),'热带低压')
        self.assertEqual(self.classify(['TC','SS'],[65,180]),'台风')

    def test_replace_only_category(self):
        self.classify(['TC'],[170])
        for original in ['假想热带气旋蔷琵 - 2026 - WP', '假想顶级超强台风蔷琵 - 2026 - WP']:
            self.ns['_S'] = {'intro_line': original}
            self.assertEqual(self.ns['intro_name_line'](),'超顶级超强台风 蔷琵  2026-WPAC')
        self.ns['_S'] = {'name_cn':'蔷琵'}
        self.assertEqual(self.ns['intro_name_line'](),'超顶级超强台风 蔷琵  2026-WPAC')
        self.ns['_S'] = {'intro_line':''}
        self.assertEqual(self.ns['intro_name_line'](),'')


if __name__ == '__main__':
    unittest.main()
