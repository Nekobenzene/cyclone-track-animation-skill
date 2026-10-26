"""Track's lead-in substitutes for the intro without changing any source times."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/python'))
from PIL import Image


class TrackOpeningTests(unittest.TestCase):
    def setUp(self):
        path = ROOT/'single/scripts/typhoon_anim.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='R')
        nodes = [n for n in cls.body if isinstance(n,ast.FunctionDef)
                 and n.name in ('render','_compose_hud')]
        self.ns = dict(FPS=120,INTRO=3.3,T_MAIN=49.3,T_PULL=51.3,T_SUM=55.3,SUMMARY=0)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),self.ns)

    def test_all_hud_pixels_are_available_immediately(self):
        original = Image.new('RGBA',(5,5),(17,90,180,130))
        obj = SimpleNamespace(hud=original)
        for t in (0,1,2.8,3.3,5):
            frame = self.ns['_compose_hud'](obj,t)
            self.assertEqual(frame.tobytes(),original.tobytes())
            self.assertIsNot(frame,original)

    def test_only_leadin_visuals_differ_between_modes(self):
        obj = SimpleNamespace(frame_main=lambda t,i:('track',t,i),
                              frame_intro=lambda t:('intro',t),
                              frame_hold=lambda t:('hold',t))
        for mode in ('track','full','intro'):
            self.ns['video_mode'] = lambda:mode
            for index in (0,120,336,360,395):
                result = self.ns['render'](obj,index)
                self.assertEqual(result[0],'track' if mode=='track' else 'intro')
            self.assertEqual(self.ns['render'](obj,396),('track',3.3,396))
            self.assertEqual(self.ns['render'](obj,480),('track',4.0,480))


if __name__ == '__main__': unittest.main()
