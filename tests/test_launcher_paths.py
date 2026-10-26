import ast
import os
from pathlib import Path
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]

class LauncherPathTests(TestCase):
    def test_cross_drive_assets_fall_back_to_absolute(self):
        tree=ast.parse((ROOT/'single/scripts/launch.py').read_text(encoding='utf-8'))
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='asset_reference']
        ns={'Path':Path,'os':os}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'asset_reference','exec'),ns)
        assets=Path('/shared/assets')
        build=Path('/project/build')
        with mock.patch.object(os.path,'relpath',side_effect=ValueError('different mount')):
            self.assertEqual(ns['asset_reference'](assets,build),assets.as_posix())
        with mock.patch.object(os.path,'relpath',return_value='../../shared/assets'):
            self.assertEqual(ns['asset_reference'](assets,build),'../../shared/assets')
