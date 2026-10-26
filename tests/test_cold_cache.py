"""Cold-cache regressions without downloading the asset pack or native wheels.

Execute the real path/extraction functions, replacing only FFmpeg output. Full
frame/codec verification belongs to the release smoke test with installed assets.
"""
import ast
import contextlib
import io
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
RENDERERS = ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py')


def load_cache_functions(relative):
    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'_c', '_apply_config', '_bind_paths', '_ensure_cache_dirs', 'extract_fx', 'video_mode'}
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    # Load the actual renderer constructor too; stop after asset preparation.
    renderer = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == 'R')
    nodes.append(next(node for node in renderer.body
                      if isinstance(node, ast.FunctionDef) and node.name == '__init__'))
    calls = []

    def ffmpeg(args, check):
        assert check
        calls.append(args)
        output = Path(args[-1])
        # Simulate sufficient decoded frames for both reuse thresholds.
        for index in range(21):
            (output.parent / (output.name % index)).write_bytes(b'frame')

    namespace = dict(os=os, shutil=shutil, CFG={}, _S={}, _D={}, _CONFIG_DIR=None,
                     subprocess=SimpleNamespace(run=ffmpeg),
                     banner_asset=lambda: 'Summary-N-TC-TS.mp4')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace, calls


class ColdCacheTests(unittest.TestCase):
    def setup_cache(self, relative, project, custom=False):
        module, calls = load_cache_functions(relative)
        paths = {'storm': str(project), 'assets': str(project / 'assets' / 'SMCY1.3')}
        if custom:
            paths['cache'] = str(project / 'custom' / 'nested' / 'cache')
        module['_apply_config']({'paths': paths})
        return module, calls

    def test_bind_creates_default_and_custom_caches_idempotently(self):
        for relative in RENDERERS:
            for custom in (False, True):
                with self.subTest(renderer=relative, custom=custom), tempfile.TemporaryDirectory() as tmp:
                    module, _ = self.setup_cache(relative, Path(tmp), custom)
                    module['_bind_paths']()
                    for name in ('CACHE', 'ICOND', 'FXD'):
                        self.assertTrue(Path(module[name]).is_dir())
                    marker = Path(module['FXD']) / 'keep.txt'
                    marker.write_text('keep', encoding='utf-8')
                    module['_bind_paths']()
                    self.assertEqual(marker.read_text(encoding='utf-8'), 'keep')

    def test_extraction_recovers_deleted_fx_root_and_reuses_frames(self):
        for relative in RENDERERS:
            with self.subTest(renderer=relative), tempfile.TemporaryDirectory() as tmp:
                module, calls = self.setup_cache(relative, Path(tmp))
                module['_bind_paths']()
                fx = Path(module['FXD'])
                # Also exercise the extraction guard independently of binding.
                if fx.exists():
                    shutil.rmtree(fx)
                with contextlib.redirect_stdout(io.StringIO()):
                    module['extract_fx']()
                    count = len(calls)
                    self.assertGreater(count, 1)
                    module['extract_fx']()
                self.assertEqual(len(calls), count)
                self.assertTrue((fx / 'sumban_TS' / '000.png').is_file())
                self.assertTrue((fx / 'landing' / '000.png').is_file())

    def test_stale_banner_cleanup_preserves_other_effects(self):
        for relative in RENDERERS:
            with self.subTest(renderer=relative), tempfile.TemporaryDirectory() as tmp:
                module, _ = self.setup_cache(relative, Path(tmp))
                module['_bind_paths']()
                stale = Path(module['FXD']) / 'sumban_old'
                stale.mkdir()
                with contextlib.redirect_stdout(io.StringIO()):
                    module['extract_fx']()
                self.assertFalse(stale.exists())
                self.assertTrue((Path(module['FXD']) / 'landed' / '000.png').is_file())

    def test_direct_renderer_prepares_assets_before_drawing(self):
        class DrawingStarted(Exception):
            pass

        for relative in RENDERERS:
            with self.subTest(renderer=relative), tempfile.TemporaryDirectory() as tmp:
                module, calls = self.setup_cache(relative, Path(tmp))
                module['_bind_paths']()

                def ready_to_draw():
                    self.assertGreater(len(calls), 0)
                    self.assertTrue((Path(module['FXD']) / 'sumban_TS' / '000.png').is_file())
                    raise DrawingStarted

                module['cmd_assets'] = module['extract_fx']
                module['build_hud'] = ready_to_draw
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(DrawingStarted):
                    module['__init__'](SimpleNamespace())

    def test_cache_path_conflict_is_not_silently_ignored(self):
        for relative in RENDERERS:
            with self.subTest(renderer=relative), tempfile.TemporaryDirectory() as tmp:
                module, _ = self.setup_cache(relative, Path(tmp), custom=True)
                cache = Path(tmp) / 'custom' / 'nested' / 'cache'
                cache.parent.mkdir(parents=True)
                cache.write_text('not a directory', encoding='utf-8')
                with self.assertRaises(FileExistsError):
                    module['_bind_paths']()


if __name__ == '__main__':
    unittest.main()
