"""Sustained intensity audio must stop across weaker gaps."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
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
    def test_separate_qualifying_intervals(self):
        check([100, 125, 100, 125, 100], 113, 2)
        check([125, 100, 125], 113, 2)
        check([125, 125, 125], 113, 1)
        check([100, 100, 100], 113, 0)
        check([160, 180, 160, 180, 160], 170, 2)
        check([113, 113, 113], 113, 1)
        check([125, 113, 125], 113, 1)
