"""Track pattern continuity with dense sampling and per-segment colour changes."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TrackStyleTests(unittest.TestCase):
    def test_dense_dashes_and_coloured_solid_tracks(self):
        code = r'''
from PIL import Image, ImageDraw
from single.scripts import typhoon_anim as a
from types import SimpleNamespace
assert set(a.TRACK_PATTERNS) == {'DB', 'MV', 'MD', 'RV'}
for phase in ('DB', 'MV', 'MD', 'SD', 'SS', 'TC', 'EX', 'RV'):
    assert a._preview_phase_at(SimpleNamespace(PHASE_BOUNDS=[], S=SimpleNamespace(phase=[phase])), 0) == phase
points = [(x, 10) for x in range(300)]
colours = [(255, 0, 0) if x < 150 else (0, 255, 0) for x in range(300)]
for phase in ('DB', 'MV', 'MD', 'RV'):
    image = Image.new('RGB', (300, 20))
    a.draw_track_segments(ImageDraw.Draw(image), points, colours, [phase]*300, 2)
    pixels = [image.getpixel((x, 10)) for x in range(2, 298)]
    assert (0, 0, 0) in pixels, phase
    assert (255, 0, 0) in pixels and (0, 255, 0) in pixels, phase
for phase in ('SD', 'SS', 'TC', 'EX'):
    image = Image.new('RGB', (300, 20))
    a.draw_track_segments(ImageDraw.Draw(image), points, colours, [phase]*300, 2)
    assert all(image.getpixel((x,10)) != (0,0,0) for x in range(300)), phase
for w in (30, 100, 200, 300, 500):
    assert a.track_theme_col(w, 'EX') != a.theme_col(w, a.level_of(w, 'TC'))
assert a.track_theme_col(505, 'EX') == a.track_theme_col(500, 'EX')
'''
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join([str(ROOT/'runtime/python'), str(ROOT)])
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
