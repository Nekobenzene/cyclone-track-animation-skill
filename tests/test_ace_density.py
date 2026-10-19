"""ACE grid conservation, phase selection, angular boundaries and RGBA ramp."""
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/python'), str(ROOT)]
import numpy as np
from PIL import Image
from scripts import track_preview as overview


def storm(hours, wind, phases, lon, lat, start_hour=0):
    return {'S': SimpleNamespace(t0=datetime(2020, 1, 1, start_hour),
             hours=np.array(hours), ihours=np.array(hours), iwind=np.array(wind),
             phase=phases, lon=np.array(lon), lat=np.array(lat), ace_end_h=hours[-1])}


class AceDensityTests(unittest.TestCase):
    def test_shared_limit_rounds_half_up_to_hundredth(self):
        self.assertEqual(overview.rounded_heat_max(.41414839), .41)
        self.assertEqual(overview.rounded_heat_max(.415), .42)
        self.assertEqual(overview.rounded_heat_max(0), .01)

    def test_pixel_field_conserves_ace_and_storms_stay_independent(self):
        a=storm([0,6],[100,100],['TC','TC'],[130,136],[15,15])
        b=storm([0,6],[50,50],['TC','TC'],[130,136],[15,15])
        win=(100,180,-10,50)
        fa,ra=overview.pixel_ace_field([a],win,width=160)
        fb,rb=overview.pixel_ace_field([b],win,width=160)
        whole,r=overview.pixel_ace_field([a,b],win,width=160)
        self.assertAlmostEqual(ra['field_ace'],2.)
        self.assertAlmostEqual(rb['field_ace'],.5)
        np.testing.assert_allclose(whole,fa+fb,atol=1e-12)
        self.assertLess(rb['actual_peak'],r['actual_peak'])

    def test_tc_only_threshold_and_addition(self):
        st=storm([0,6,12],[20,40,80],['TC','EX','TC'],[140.1]*3,[15.2]*3)
        _, report=overview.pixel_ace_field([st,st],(100,180,-10,50),width=160)
        self.assertAlmostEqual(report['field_ace'],1.28)

    def test_negative_latitude_and_longitude_seam(self):
        st=storm([0,6],[40,60],['TC','TC'],[359.5,360.5],[-.5,.5])
        field, report=overview.pixel_ace_field([st],(350,370,-10,10),width=160)
        self.assertAlmostEqual(report['field_ace'],.52)
        self.assertTrue(np.isfinite(field).all())
        self.assertGreater(field.max(),0)
