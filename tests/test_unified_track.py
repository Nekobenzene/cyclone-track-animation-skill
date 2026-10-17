"""Unified full/sparse phase columns, legacy fallback and ACE phase gaps."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
class UnifiedTrackTests(unittest.TestCase):
    def test_full_sparse_and_legacy(self):
        code=r'''
from pathlib import Path
import tempfile
from single.scripts import typhoon_anim
from season.scripts import season_pass1, season_pass2
for m in (typhoon_anim,season_pass1):
 with tempfile.TemporaryDirectory() as td:
    m.SRC=td;m._D={'plateau_ease':False,'intensity_curve':'linear'}
    data=[('0100',20,'DB'),('0106',40,'TC'),('0112',70,'RV'),('0118',40,'TC'),('0200',50,'TC'),('0206',70,'RV'),('0212',30,'ST'),('0218',40,'ST')]
    rows=[f'202601{date}0000 140 -15 {w} 1000 {phase}' for date,w,phase in data]
    path=Path(td,'track.txt');path.write_text('\n'.join(rows))
    # A stale explicit YAML list and old files must not duplicate unified data.
    Path(td,'TC.txt').write_text('20260101000000 140 15 200 900\n')
    m._D['series']=[{'file':'TC.txt','phase':'TC'}]
    full=m.Series();assert abs(full.ace_total-0.57)<1e-8,full.ace_total
    assert full.phase==['DB','TC','RV','TC','TC','RV','SD','SD']
    m.S=full;m.build_phases()
    assert m._phase_at(5.99)=='DB' and m._phase_at(6)=='TC'
    assert m._phase_at(12)=='RV' and m._phase_at(18)=='TC'
    expected=m.PHASE_BOUNDS.copy()
    sparse=[];last=None
    for row,(_,_,phase) in zip(rows,data):
        sparse.append(row if phase!=last else row.rsplit(' ',1)[0]);last=phase
    path.write_text('\n'.join(sparse))
    overlay_rows=season_pass2.read_rows(str(path))
    overlay=season_pass2.Series(overlay_rows,overlay_rows[0][0])
    assert abs(overlay.ace[-1]-full.ace_total)<1e-8,overlay.ace
    m.S=m.Series();m.build_phases()
    assert m.S.phase==full.phase and m.PHASE_BOUNDS==expected
    assert abs(m.S.ace_total-full.ace_total)<1e-8
    # Parsing and real crossing generation share the subtropical upgrade path.
    m.KEY=m.build_key()
    events=m._ts_fx_hours()
    assert any(36<h<42 for h in events),events
    # No implicit TC assumption for the first unified row.
    path.write_text(rows[0].rsplit(' ',1)[0])
    try:m.Series()
    except ValueError as e:assert 'first track fix' in str(e)
    else:raise AssertionError('Missing first type accepted')
    path.write_text(rows[0]+'\n'+rows[0].replace(' DB',' EX'))
    try:m.Series()
    except ValueError as e:assert 'Conflicting' in str(e)
    else:raise AssertionError('Conflicting timestamp accepted')
    path.write_text(rows[0].replace(' DB',' TYPO'))
    try:m.Series()
    except ValueError as e:assert 'track.txt:1' in str(e)
    else:raise AssertionError('Unknown type accepted')
    path.unlink();m._D={}
    legacy=m.Series();assert legacy.phase==['TC'] and legacy.wind[0]==200
    # Interleaved legacy files: the TC file has a 24-hour gap occupied by RV.
    Path(td,'TC.txt').write_text('20260101000000 140 15 40 1000\n20260102000000 140 15 40 1000\n')
    Path(td,'RV.txt').write_text('20260101060000 140 15 70 1000\n20260101120000 140 15 70 1000\n20260101180000 140 15 70 1000\n')
    legacy=m.Series()
    assert list(legacy.hours)==[0,6,12,18,24]
    assert legacy.phase==['TC','RV','RV','RV','TC']
    assert abs(legacy.ace_total-0.32)<1e-8,legacy.ace_total
    m.S=legacy;m.build_phases()
    assert m._phase_at(0)=='TC' and m._phase_at(6)=='RV' and m._phase_at(24)=='TC'
    overlay_rows=[]
    for fn in ('TC.txt','RV.txt'):
        overlay_rows.extend(season_pass2.read_rows(str(Path(td,fn))))
    overlay_rows.sort(key=lambda row:row[0])
    overlay=season_pass2.Series(overlay_rows,overlay_rows[0][0])
    assert abs(overlay.ace[-1]-0.32)<1e-8

'''
        env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(ROOT/'runtime/python'),str(ROOT)])
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
