from pathlib import Path
import os,subprocess,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
class UpgradeEventTests(unittest.TestCase):
 def test_entries_and_repeated_upgrades(self):
  code=r'''
import numpy as np
from types import SimpleNamespace
from single.scripts import typhoon_anim
from season.scripts import season_pass1
for m in (typhoon_anim,season_pass1):
 def run(winds,bounds,start='TC'):
    m.S=SimpleNamespace(duration_h=len(winds)-1,WF=lambda q:np.interp(q,np.arange(len(winds)),winds))
    m.PHASE_BOUNDS=bounds
    def phase(h):
        ph=start
        for hb,_,pb in bounds:
            if h>=hb:ph=pb
        return ph
    m._phase_at=phase
    return m.upgrade_hours()
 assert run([20,30,40,50],[(2,'DB','TC')],start='DB')==[2]
 assert run([20,30,40,50],[(2,'EX','SS')],start='EX')==[2]
 assert run([50,45,40,35],[(2,'RV','TC')],start='RV')==[]
 assert run([40,40,40],[(1,'DB','TC')],start='DB')==[]
 assert run([20,40,20,40],[],start='EX')==[]
 events=run([20,40,20,40],[])
 assert len(events)==2 and abs(events[0]-.7)<1e-6 and abs(events[1]-2.7)<1e-6,events
 events=run([20,40,20,40],[],start='SD')
 assert len(events)==2,events
'''
  env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(ROOT/'runtime/python'),str(ROOT)])
  p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stdout+p.stderr)
