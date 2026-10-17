"""Track filename routing, chronological merging and subtropical upgrades."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
class TrackTypeTests(unittest.TestCase):
    def test_renderers(self):
        code = r'''
from pathlib import Path
import tempfile
from types import SimpleNamespace
import numpy as np
from single.scripts import typhoon_anim
from season.scripts import season_pass1, season_overview
for m in (typhoon_anim, season_pass1):
    for name, phase in [('DB','DB'),('DB-LO','DB'),('DB-aL','DB'),('DB-MV','MV'),('DB-MD','MD'),('MV','MV'),('MD','MD'),('SD','SD'),('SS','SS')]:
        assert m.segment_phase(name+'.txt', 'DB') == phase
    for phase in ('SD','SS'):
        assert m.level_of(33.99,phase) == 'SD'
        assert m.level_of(34,phase) == 'SS'
        assert m.icon_pair(34,phase)[0] == 'SS'
        assert m._phase_side(phase,34) == {'SS':1.0}
    with tempfile.TemporaryDirectory() as td:
        m.SRC=td; m._D={}
        Path(td,'SS.txt').write_text('20260101120000 140 -15 40 1000\n20260101180000 140 -15 45 1000\n')
        Path(td,'DB-MV.txt').write_text('20260101000000 140 -15 20 1000\n20260101060000 140 -15 25 1000\n')
        m.S=m.Series()
        assert list(m.S.phase)==['MV','MV','SS','SS'],m.S.phase
        assert list(m.S.hours)==[0,6,12,18]
        jobs=m.icon_jobs()
        assert jobs['S_MV'][0]=='disturbance/S-DB-aWV.mp4'
        assert jobs['S_MD'][0]=='disturbance/S-TD-MD.mp4'
        for _,(rel,_) in jobs.items():
            if Path('assets/SMCY1.3/mainicon').is_dir():
                assert (Path('assets/SMCY1.3/mainicon')/rel).is_file(),rel
    with tempfile.TemporaryDirectory() as td:
        m.SRC=td; m._D={}
        Path(td,'MV.txt').write_text('20260101000000 140 -15 20 1000\n')
        Path(td,'MD.txt').write_text('20260101060000 140 -15 25 1000\n')
        m.S=m.Series()
        assert m.S.phase==['MV','MD'],m.S.phase
    m.sample=lambda h: (140,-15)
    seen=[]
    m.icon_sprite=lambda lvl,nf,**kw: seen.append((lvl,kw['hemisphere'])) or 'sprite'
    m.PHASE_BOUNDS=[]
    assert m.R.sprite_for(None,{},0,40,phase='SS',h=12)=='sprite'
    assert seen==[('SS','S')]
    from PIL import Image
    m._phase_at=lambda h: 'SD'
    m._ss_upgrade_colour=lambda directory: np.array([0.8,1.0,0.1])
    pixels=np.array([[[0,200,0],[255,255,255],[0,0,0]]],dtype=np.uint8)
    got=np.asarray(m.upgrade_sprite(Image.fromarray(pixels),0))
    np.testing.assert_array_equal(got[0,2],[160,200,20])
    np.testing.assert_array_equal(got[0,1],[255,255,255])
    np.testing.assert_array_equal(got[0,0],[0,0,0])
    m.KEY={'ts_all':[1,2,3,4,5]}
    m._phase_at=lambda h: {1:'TC',2:'SD',3:'SS',4:'EX',5:'MV'}[h]
    assert m._ts_fx_hours()==[1,2,3]
assert season_overview._phase_side('SD',34)=={'SS':1.0}
assert typhoon_anim._preview_phase_side('SS',30)=={'SD':1.0}
'''
        env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(ROOT/'runtime/python'),str(ROOT)])
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
