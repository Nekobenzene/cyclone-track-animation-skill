"""Track and full exports share an editing timeline and identical effect audio."""
import ast
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/python'))
import numpy as np


def load_functions():
    source = ROOT/'single/scripts/typhoon_anim.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'_c', 'video_mode', 'video_window', 'cmd_render', 'build_audio'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    ns = dict(os=os, json=json, wave=wave, np=np, subprocess=subprocess,
              CFG={}, INTRO=3.3, TOTAL=12.3, FPS=120, NFRAMES=1476,
              OUTPUT_W=4, OUTPUT_H=2, W=4, H=2, cv2=True)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), ns)
    return ns


class VideoModeTests(unittest.TestCase):
    def test_default_windows_and_invalid_mode(self):
        ns = load_functions()
        self.assertEqual(ns['video_window'](), (0, 12.3))
        for mode, expected in [('intro',(0,3.3)),('track',(0,12.3)),('full',(0,12.3))]:
            ns['CFG'] = {'output':{'video_mode':mode}}
            self.assertEqual(ns['video_window'](), expected)
        ns['CFG'] = {'output':{'video_mode':'typo'}}
        with self.assertRaises(ValueError): ns['video_window']()

    def test_render_uses_matching_source_frames(self):
        ns = load_functions()
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            ns.update(BUILD=temp, RAWM=str(Path(temp)/'silent.mp4'))
            for mode, start, count in [('intro',0,33),('track',0,123),('full',0,123)]:
                frames, previews = [], []
                class Encoder:
                    stdin = SimpleNamespace(write=lambda data: None, close=lambda: None)
                    def wait(self): return 0
                ns.update(CFG={'output':{'video_mode':mode,'fps':10}},
                          R=lambda: SimpleNamespace(render=lambda index: (frames.append(index) or np.zeros((2,4,3),dtype=np.uint8))),
                          cmd_preview=lambda:previews.append(True),
                          subprocess=SimpleNamespace(Popen=lambda *a,**k:Encoder(),PIPE=-1))
                ns['cmd_render']()
                self.assertEqual(len(frames), count)
                self.assertEqual(frames, [start+i*12 for i in range(count)])
                self.assertEqual(bool(previews), mode != 'intro')

    def test_audio_track_matches_full_without_editing_shift(self):
        ns = load_functions()
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            ns.update(TMP=temp, ASSETS=temp, DAMAGE=[], RI_EVENTS=[], LANDFALLS=[],
                      _ts_fx_hours=lambda:[1], t_of_hours=lambda h:3.3+h,
                      intensity_intervals=lambda threshold:[(3,4)] if threshold == 113.0 else [],
                      rd_wav=lambda *a: np.full(44100,0.5,dtype=np.float32),
                      subprocess=SimpleNamespace(run=lambda *a,**k:None))
            data = {}
            for mode in ('full','track','intro'):
                ns.update(CFG={'output':{'video_mode':mode},'audio':{'weaken':False}},
                          WAV=str(Path(temp)/(mode+'.wav')))
                ns['build_audio']()
                with wave.open(ns['WAV'],'rb') as wav:
                    data[mode] = wav.readframes(wav.getnframes())
            self.assertEqual(data['track'],data['full'])
            self.assertEqual(len(data['intro']),round(3.3*44100)*4)
            self.assertFalse(any(data['intro']))
            track = np.frombuffer(data['track'], dtype='<i2').reshape(-1,2)
            self.assertFalse(np.any(track[:round(4.3*44100)]))
            self.assertTrue(np.any(track[round(4.3*44100):round(5.3*44100)]))


if __name__ == '__main__': unittest.main()
