from pathlib import Path
from types import SimpleNamespace
import runpy
import numpy as np

source = Path(__file__).with_name('typhoon_anim.py')
module = runpy.run_path(str(source))
intervals = module['intensity_intervals']
curve = module['MonotoneCubic']

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

check([100, 125, 100, 125, 100], 113, 2)
check([125, 100, 125], 113, 2)
check([125, 125, 125], 113, 1)
check([100, 100, 100], 113, 0)
check([160, 180, 160, 180, 160], 170, 2)
check([113, 113, 113], 113, 1)
check([125, 113, 125], 113, 1)
print('All interval regression checks passed.')
