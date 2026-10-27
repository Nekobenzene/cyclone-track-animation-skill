"""Regressions for complete peak cycles, end-banner totals and cloud exit."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'runtime/python')]
import numpy as np
from single.scripts import typhoon_anim as a


class SingleFactsTests(unittest.TestCase):
    def series(self, wind, pres=None, phase=None):
        n = len(wind)
        return SimpleNamespace(ihours=np.arange(n), iwind=np.array(wind),
            ipres=np.array(pres if pres is not None else [1000-w for w in wind]),
            hours=np.arange(n), phase=phase or ['TC']*n,
            lon=np.arange(n)+130, lat=np.arange(n)+10)

    def test_every_cycle_and_low_pressure_representative_of_peak_plateau(self):
        s = self.series([30,135,130,155,120,145,130,170,170,170,85,105,45],
                        [1004,930,932,905,932,918,930,893,890,894,955,945,995])
        peaks = a.derive_peaks(s)
        self.assertEqual([p['h'] for p in peaks], [1,3,5,8,11])
        self.assertEqual([p['graph'] for p in peaks],
            ['P1 135/930','P2 155/905','P3 145/918','P4 170/890','P5 105/945'])

    def test_non_tropical_peak_excluded_and_flat_storm_has_one_peak(self):
        s = self.series([200,20,50,20,100], phase=['DB','TC','TC','TC','EX'])
        self.assertEqual([p['h'] for p in a.derive_peaks(s)], [2])
        self.assertEqual(len(a.derive_peaks(self.series([40,40,40]))), 1)

    def test_uses_effective_intensity_knots_including_inserted_reanalysis(self):
        s = self.series([30,80,30])
        s.ihours=np.array([0,.5,1,2]); s.iwind=np.array([30,100,80,30])
        s.ipres=np.array([1000,970,980,1000])
        self.assertEqual(a.derive_peaks(s)[0]['h'], .5)
        self.assertEqual(a.derive_peaks(s)[0]['lon'], 130.5)

    def test_damage_totals_and_explicit_banner_overrides(self):
        events=[dict(dead=1,lost=0,loss='0.49'),dict(dead=2,lost=3,loss='0.01')]
        with patch.object(a,'DAMAGE',events), patch.object(a,'CFG',{}), \
             patch.object(a,'_D',{}), patch.object(a,'S',SimpleNamespace(ace_total=50.7)):
            self.assertEqual(a.damage_totals_label(), ('CNY 50 mn','6'))
            self.assertIn('LOSS CNY 50 mn      DEATHS 6', a.banner_line2())
            a.CFG={'banner':{'loss':'CNY 49 mn','deaths':'1'}}
            self.assertIn('LOSS CNY 49 mn      DEATHS 1', a.banner_line2())
        with patch.object(a,'DAMAGE',[]):
            self.assertEqual(a.damage_totals_label(), ('n/a','n/a'))

    def test_cloud_exit_is_after_final_observation_in_output_seconds(self):
        with patch.multiple(a,CLOUD_FILE='source.mp4',CLOUD_G0=0,CLOUD_G1=0,
                            CLOUD_HA=10,CLOUD_HEND=30,_CL={}), \
             patch.object(a,'t_of_hours',side_effect=lambda h: h*2):
            self.assertEqual(a.cloud_exit_alpha(20),1)
            self.assertAlmostEqual(a.cloud_exit_alpha(20.25),.5)
            self.assertEqual(a.cloud_exit_alpha(20.5),0)
            self.assertEqual(a.cloud_exit_alpha(99),0)
            a.CLOUD_G1=5
            self.assertEqual(a.cloud_exit_alpha(60),1)
            self.assertEqual(a.cloud_exit_alpha(60.5),0)


if __name__ == '__main__':
    unittest.main()
