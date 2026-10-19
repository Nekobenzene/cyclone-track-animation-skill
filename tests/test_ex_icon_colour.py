"""EX palette continuity, neutral-pixel preservation and sprite routing."""
import ast
import os
from functools import lru_cache
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/python'))
import numpy as np
from PIL import Image, ImageChops
import cv2


def load_renderer(relative):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    names = {'COL', 'C5PP_A', 'C5PP_B', 'C6_END', 'HIGHWIND_BODY', 'HIGHWIND_HALO', 'BANDS', 'ICON_FADE_KT'}
    functions = {'palette_colour', 'highwind_halo_colour', 'level_of', 'theme_col', 'icon_pair', 'ex_icon_colour', 'ex_icon_tinted',
                 '_sample_icon_colour', '_tc_icon_palette', '_phase_at',
                 '_grey_lightning_layer', 'ex_icon_with_lightning', '_ts_fx_hours',
                 '_ace_ex_endpoint', '_tc_digit_mask', 'tc_digit_tinted',
                 'single_badge_colours', 'single_card_colour', '_banner_digit_mask',
                 'banner_digit_tinted', '_lerp_rgb', '_ramp', 'single_highwind_text'}
    nodes = [n for n in tree.body if
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))
             or (isinstance(n, ast.FunctionDef) and n.name in functions)]
    renderer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'R')
    nodes += [n for n in renderer.body if isinstance(n, ast.FunctionDef) and n.name == 'sprite_for']
    ns = {'np': np, 'Image': Image, 'ImageChops': ImageChops, 'cv2': cv2,
          'os': os, 'lru_cache': lru_cache, 'ICOND': 'test-icons', 'ASSETS': 'fixture-assets'}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), relative, 'exec'), ns)
    return ns


class ExIconColourTests(unittest.TestCase):
    def test_single_high_wind_cards_and_banner_digit(self):
        ns = load_renderer('single/scripts/typhoon_anim.py')
        self.assertEqual(ns['single_badge_colours'](200, 'C5++', (1,2,3)),
                         ((198,232,255), (30,3,9)))
        self.assertEqual(ns['single_card_colour'](200, 'C5++'), (198,232,255))
        self.assertEqual(ns['single_card_colour'](180, 'C5++'), ns['theme_col'](180, 'C5++'))
        colours = [ns['single_badge_colours'](w, 'C5++', ns['theme_col'](w,'C5++')) for w in (185,190,195,200)]
        for a,b in zip(colours,colours[1:]):
            self.assertNotEqual(a[0],b[0])
            self.assertGreater(sum(a[1]),sum(b[1]))
        for w in (185,200):
            np.testing.assert_allclose(ns['single_highwind_text'](w-1e-4,(255,255,255),(30,3,9)),
                                       ns['single_highwind_text'](w+1e-4,(255,255,255),(30,3,9)),atol=1)
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory)/'banner.png'
            source = np.full((100,1000,3), 255, np.uint8)
            source[25:75,95:110] = [170,10,170]
            source[25:75,300:315] = [170,10,170]
            Image.fromarray(source).save(reference)
            image = Image.new('RGB', (1000,100), (198,232,255))
            self.assertIs(ns['banner_digit_tinted'](image,str(reference),185), image)
            out = np.asarray(ns['banner_digit_tinted'](image,str(reference),200))
            np.testing.assert_array_equal(out[50,100], [30,3,9])
            np.testing.assert_array_equal(out[50,305], [198,232,255])

    def test_tc_digit_darkens_only_masked_numeral(self):
        for path in ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py'):
            ns = load_renderer(path)
            source = np.full((100, 100, 3), 255, dtype=np.uint8)
            source[43:55, 46:54] = [170, 10, 170]
            source[5:10, 5:10] = [170, 10, 170]
            ns['icon_sprite'] = lambda *args, **kwargs: Image.fromarray(source)
            image = Image.new('RGB', (100, 100), (180, 220, 250))
            self.assertIs(ns['tc_digit_tinted'](image, 185), image)
            previous = 1000
            for wind in (186, 190, 195, 200):
                out = np.asarray(ns['tc_digit_tinted'](image, wind))
                self.assertLess(int(out[48, 50].sum()), previous)
                previous = int(out[48, 50].sum())
                np.testing.assert_array_equal(out[5:10, 5:10], np.asarray(image)[5:10, 5:10])
                np.testing.assert_array_equal(out[60:, :], np.asarray(image)[60:, :])
            np.testing.assert_array_equal(out[48, 50], [30, 3, 9])

    def test_tc_preview_and_overview_match_renderer_endpoint(self):
        for path, prefix in (('scripts/track_preview.py', ''),):
            tree = ast.parse((ROOT/path).read_text(encoding='utf-8'))
            constants = {prefix+name for name in ('COL', 'C5PP_A', 'C5PP_B', 'C6_END')}
            nodes = [n for n in tree.body if
                     (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets))
                     or (isinstance(n, ast.FunctionDef) and n.name == prefix+'theme_col')]
            ns = {'np': np}
            exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), ns)
            np.testing.assert_array_equal(ns[prefix+'theme_col'](200, 'C5++'), [198, 232, 255])

    def test_tc_high_wind_endpoint(self):
        for path in ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py'):
            ns = load_renderer(path)
            np.testing.assert_array_equal(ns['theme_col'](185, 'C5++'), ns['C5PP_B'])
            np.testing.assert_array_equal(ns['theme_col'](200, 'C5++'), [198, 232, 255])
            np.testing.assert_array_equal(ns['theme_col'](220, 'C5++'), [192, 255, 244])
            expected = (np.asarray(ns['C5PP_B']) + [198, 232, 255])/2
            np.testing.assert_allclose(ns['theme_col'](192.5, 'C5++'), expected, atol=1)

    def test_palette_pixels_and_routing(self):
        for path in ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py'):
            with self.subTest(renderer=path):
                ns = load_renderer(path)
                ns['ex_icon_with_lightning'] = lambda im, nf, wind: im
                ns['_ace_ex_endpoint'] = lambda directory: np.array([198, 232, 255], dtype=np.float32)
                image = Image.fromarray(np.uint8([[[60, 80, 200], [255, 255, 255],
                                                   [170, 170, 170], [0, 0, 0]]]))
                original = np.asarray(image)
                np.testing.assert_array_equal(ns['_sample_icon_colour']([image]), [60, 80, 200])
                # Verify palette nodes really come from the supplied sprite pixels.
                ns['sample'] = lambda h: (140, 15)
                ns['icon_sprite'] = lambda *args, **kwargs: image
                ns['tinted'] = lambda key, im, colour: im
                sampled = ns['_tc_icon_palette']('fixture')
                np.testing.assert_array_equal(sampled['TS'], [60, 80, 200])
                self.assertFalse(np.array_equal(sampled['TS'], ns['COL']['TS']))
                palette = {k: np.array(v, dtype=np.float32) for k, v in ns['COL'].items()}
                palette.update({'C5++': ns['C5PP_A'], 'blue': ns['C5PP_B']})
                ns['_tc_icon_palette'] = lambda directory: palette
                nodes = [((lo + hi) / 2, palette[lvl]) for lvl, lo, hi in ns['BANDS'][:-1]]
                for (a, ca), (b, cb) in zip(nodes, nodes[1:]):
                    np.testing.assert_allclose(ns['ex_icon_colour']((a+b)/2), (ca+cb)/2, atol=1e-4)
                # Within-category wind changes must change colour too.
                for a, b in ((40, 45), (68, 70), (100, 105), (140, 145), (158, 160)):
                    self.assertGreater(np.abs(ns['ex_icon_colour'](a)-ns['ex_icon_colour'](b)).max(), .1)
                for wind in (5, 15, 30, float('nan')):
                    self.assertIs(ns['ex_icon_tinted'](image, wind), image)
                colours = np.array([ns['ex_icon_colour'](w) for w in np.arange(30, 201, .05)])
                self.assertLess(np.abs(np.diff(colours, axis=0)).max(), 4)
                np.testing.assert_allclose(ns['ex_icon_colour'](185), ns['C5PP_B'])
                np.testing.assert_allclose(ns['ex_icon_colour'](200), [198, 232, 255])
                np.testing.assert_allclose(ns['ex_icon_colour'](192.5),
                                           (ns['C5PP_B'] + [198, 232, 255]) / 2)
                for boundary in (31, 34, 37, 61, 64, 67, 83, 96, 113, 137, 156, 170, 185, 200):
                    np.testing.assert_allclose(ns['ex_icon_colour'](boundary - 1e-5),
                                               ns['ex_icon_colour'](boundary + 1e-5), atol=.01)
                for wind in (30.0001, 35, 65, 100, 150, 175, 190, 200):
                    tinted = np.asarray(ns['ex_icon_tinted'](image, wind))
                    np.testing.assert_array_equal(tinted[:, 1:], original[:, 1:])
                np.testing.assert_array_equal(ns['ex_icon_tinted'](image, 30.0001), original)
                self.assertFalse(np.array_equal(ns['ex_icon_tinted'](image, 100), original))
                # Rotation can radically change the distribution of halo pixels.
                # An identical pixel must keep its colour despite that change.
                bright = np.tile(np.uint8([60, 80, 200]), (16, 16, 1))
                dim = np.tile(np.uint8([12, 16, 40]), (16, 16, 1))
                bright[0, 0] = dim[0, 0] = [60, 80, 200]
                a = np.asarray(ns['ex_icon_tinted'](Image.fromarray(bright), 100))
                b = np.asarray(ns['ex_icon_tinted'](Image.fromarray(dim), 100))
                np.testing.assert_array_equal(a[0, 0], b[0, 0])
                # Recolouring must never introduce an exposure boost.
                self.assertLessEqual(int(a.max()), int(bright.max()))
                self.assertLessEqual(int(b[1, 1].max()), int(dim[1, 1].max()))
                ns['sample'] = lambda h: (140, 15)
                ns['icon_sprite'] = lambda *args, **kwargs: image
                self.assertIs(ns['sprite_for'](None, {'EX': 1}, 0, 30, phase='EX'), image)
                self.assertFalse(np.array_equal(ns['sprite_for'](None, {'EX': 1}, 0, 100, phase='EX'), original))
                self.assertIs(ns['sprite_for'](None, {'TS': 1}, 0, 50, phase='TC'), image)
                # TC/EX transitions must use the tinted EX side too.
                ns['PHASE_BOUNDS'] = [(10, 'TC', 'EX')]
                ns['TRANS_H'] = 2.5
                expected = Image.blend(image, ns['ex_icon_tinted'](image, 50), .5)
                np.testing.assert_array_equal(
                    ns['sprite_for'](None, {}, 0, 50, phase='EX', h=10), expected)
                ns['PHASE_BOUNDS'] = []
                for phase in ('EX', 'DB', 'RV', 'TC'):
                    ns['S'] = SimpleNamespace(phase=[phase, phase])
                    self.assertEqual(ns['_phase_at'](0), phase)

    def test_ex_never_uses_ts_upgrade_fallback(self):
        for path in ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py'):
            ns = load_renderer(path)
            ns['KEY'] = {'ts': 34, 'ts_all': []}
            ns['_phase_at'] = lambda h: 'TC'
            self.assertEqual(ns['_ts_fx_hours'](), [])
            ns['KEY']['ts_all'] = [1, 2, 3]
            ns['_phase_at'] = lambda h: 'EX' if h == 2 else 'TC'
            self.assertEqual(ns['_ts_fx_hours'](), [1, 3])
            source = (ROOT/path).read_text(encoding='utf-8')
            self.assertNotIn("KEY.get('ts_all') or", source)

    def test_ex_endpoint_samples_actual_ace_asset_and_has_no_added_outline(self):
        for path in ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py'):
            ns = load_renderer(path)
            with tempfile.TemporaryDirectory() as directory:
                asset = Path(directory)/'gui/ace/ace_color_1000.png'
                asset.parent.mkdir(parents=True)
                pixels = np.zeros((4, 6, 3), dtype=np.uint8)
                pixels[:, -1] = [195, 225, 253]
                Image.fromarray(pixels).save(asset)
                np.testing.assert_array_equal(ns['_ace_ex_endpoint'](directory), [195, 225, 253])
                ns['ASSETS'] = directory
                ns['_tc_icon_palette'] = lambda d: {k: np.array(v) for k, v in
                    dict(ns['COL'], **{'C5++': [100, 70, 250], 'blue': [60, 100, 250]}).items()}
                np.testing.assert_array_equal(ns['ex_icon_colour'](200), [195, 225, 253])
                source = np.zeros((20, 20, 3), dtype=np.uint8)
                source[5:15, 5:15] = [60, 80, 200]
                source = Image.fromarray(source)
                ns['icon_sprite'] = lambda *args, **kwargs: source
                ns['ex_icon_with_lightning'] = lambda im, nf, wind: im
                np.testing.assert_array_equal(ns['sprite_for'](None, {'EX': 1}, 0, 200, phase='EX'),
                                              ns['ex_icon_tinted'](source, 200))
                self.assertEqual(np.asarray(ns['ex_icon_tinted'](source, 200))[0, 0].max(), 0)
            self.assertNotIn('ex_icon_outlined', (ROOT/path).read_text(encoding='utf-8'))

    def test_lightning_separation_and_threshold(self):
        for path in ('single/scripts/typhoon_anim.py', 'season/scripts/season_pass1.py'):
            with self.subTest(renderer=path):
                ns = load_renderer(path)
                neutral = np.full((100, 100, 3), 140, np.float32)
                neutral[:, 10:15] = 60
                baseline = neutral.min(axis=2)
                self.assertEqual(np.asarray(ns['_grey_lightning_layer'](neutral, baseline)).max(), 0)
                source = neutral.copy()
                source[20:80, 20] = [20, 50, 100]
                source[45:55, 45:55] = [20, 50, 100]
                layer = ns['_grey_lightning_layer'](source, baseline)
                pixels = np.asarray(layer)
                self.assertGreater(pixels[:, 20].max(), 50)
                self.assertEqual(pixels[45:55, 45:55].max(), 0)
                calls = []
                ns.update(FXD='fx', N_ICON=600,
                          _asset_frames=SimpleNamespace(get=lambda p, size: calls.append(p) or layer))
                base = Image.new('RGB', (100, 100))
                for wind in (5, 99.99, float('nan')):
                    self.assertIs(ns['ex_icon_with_lightning'](base, 601, wind), base)
                np.testing.assert_array_equal(ns['ex_icon_with_lightning'](base, 601, 100), layer)
                self.assertTrue(calls[0].endswith('0001.png'))


if __name__ == '__main__':
    unittest.main()
