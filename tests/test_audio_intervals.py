"""Sustained intensity audio must stop across weaker gaps."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/python'),str(ROOT)]
import numpy as np
from single.scripts import typhoon_anim
intervals=typhoon_anim.intensity_intervals
curve=typhoon_anim.MonotoneCubic
def check(values, threshold, expected):
    hours = np.arange(len(values), dtype=float)
    storm = SimpleNamespace(WF=curve(hours, values), ihours=hours, duration_h=float(hours[-1]))
    intervals.__globals__['S'] = storm
    runs = intervals(threshold)
    assert len(runs) == expected, (values, threshold, runs)
    for hour in np.linspace(0.00001, hours[-1]-0.00001, 10001):
        wind = float(storm.WF(hour))
        if abs(wind-threshold) < 1e-7:
            continue
        assert any(a <= hour <= b for a,b in runs) == (wind >= threshold), (hour, runs)
    print(values, threshold, runs)

class AudioIntervalTests(unittest.TestCase):
    def test_series_threshold_plateau_survives_display_easing(self):
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            Path(temp,'track.txt').write_text(
                '20261020000000 130 20 160 900 TC\n'
                '20261020060000 131 20 170 895 TC\n'
                '20261020120000 132 20 170 890 TC\n'
                '20261020180000 133 20 160 900 TC\n', encoding='utf-8')
            with patch.object(typhoon_anim,'SRC',temp), patch.object(typhoon_anim,'_D',{}):
                storm=typhoon_anim.Series()
            self.assertLess(float(storm.WF(6)),170)
            with patch.object(typhoon_anim,'S',storm):
                runs=intervals(170)
            self.assertEqual(len(runs),1)
            self.assertAlmostEqual(runs[0][0],6,places=6)
            self.assertAlmostEqual(runs[0][1],12,places=6)

    def test_separate_qualifying_intervals(self):
        check([100, 125, 100, 125, 100], 113, 2)
        check([125, 100, 125], 113, 2)
        check([125, 125, 125], 113, 1)
        check([100, 100, 100], 113, 0)
        check([160, 180, 160, 180, 160], 170, 2)
        check([113, 113, 113], 113, 1)
        check([125, 113, 125], 113, 1)
