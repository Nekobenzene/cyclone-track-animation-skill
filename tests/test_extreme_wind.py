import os,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ExtremeWindTests(unittest.TestCase):
 def test_palette_and_impact_cap(self):
  code=r'''
from single.scripts import typhoon_anim as a
from season.scripts import season_pass1 as b,season_overview as c,season_pass2 as overlay
import numpy as np
from PIL import Image
for m in (a,b,c):
    assert m.theme_col(200,'C5++')==(198,232,255)
    assert m.theme_col(300,'C5++')==(241,221,255)
    assert m.theme_col(500,'C5++')==(244,246,255)
    assert m.highwind_halo_colour(500)==(216,255,82)
    assert m.theme_col(600,'C5++')==m.theme_col(500,'C5++')
    values=np.asarray([m.theme_col(w,'C5++') for w in np.arange(200,500,.1)])
    assert np.abs(np.diff(values,axis=0)).max()<=1
assert overlay.banner_peak_colour(200)==a.theme_col(200,'C5++')
assert overlay.banner_peak_colour(500)==a.theme_col(500,'C5++')
for m in (a,b):
    assert m.landfall_scale(200)==m.landfall_scale(300)==m.landfall_scale(500)==3.25
    assert m.landfall_scale(190)<m.landfall_scale(200)
assert a.landfall_impact_size(200)==a.landfall_impact_size(500)
assert a._preview_theme_col(500,'C5++')==a.theme_col(500,'C5++')
'''
  env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(ROOT/'runtime/python'),str(ROOT)])
  p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stdout+p.stderr)
