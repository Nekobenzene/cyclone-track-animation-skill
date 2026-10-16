"""Import the complete renderers so missing runtime imports cannot hide in AST tests."""
from pathlib import Path
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RendererImportTests(unittest.TestCase):
    def test_source_renderers_import_without_project_data(self):
        code = ('from single.scripts import typhoon_anim; '
                'from season.scripts import season_pass1, season_overview; '
                'assert typhoon_anim.theme_col(200, "C5++") == (198,232,255); '
                'assert season_pass1.theme_col(200, "C5++") == (198,232,255); '
                'assert season_overview.theme_col(200, "C5++") == (198,232,255)')
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join([str(ROOT/'runtime/python'), str(ROOT)])
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
