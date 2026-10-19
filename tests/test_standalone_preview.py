"""Standalone composition keeps paths above heat and preserves season references."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock
from datetime import datetime
import tempfile
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/python'),str(ROOT)]
import numpy as np
from PIL import Image,ImageDraw
from scripts import track_preview as preview

class StandalonePreviewTests(TestCase):
    def test_all_nine_plate_content_combinations(self):
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as tmp:
            root=Path(tmp);(root/'gui').mkdir()
            Image.new('RGBA',(10,100),'white').save(root/'gui/ace_heat.png')
            maps=SimpleNamespace(crop=lambda *args:np.full((10,10,3),10,dtype='uint8'))
            st={'S':SimpleNamespace(t0=datetime(2020,1,1))}
            def heat(frame,*args):
                layer=Image.new('RGBA',frame.size)
                ImageDraw.Draw(layer).rectangle((3,3,7,7),fill=(255,0,0,128))
                frame.alpha_composite(layer)
            def path(frame,*args):ImageDraw.Draw(frame).line((0,5,9,5),fill=(0,255,0,255),width=1)
            for background in ('map','black','transparent'):
                for layers in ('both','track','heat'):
                    with self.subTest(background=background,layers=layers):
                        settings={'field':{},'auto_max':True,'opacity':.4,'background':background,'layers':layers}
                        with mock.patch.object(preview,'pixel_ace_field',return_value=(np.ones((10,10)),{'actual_peak':.414})) as calc,mock.patch.object(preview,'overlay_pixel_heat',side_effect=heat) as overlay,mock.patch.object(preview,'draw_track',side_effect=path) as tracks:
                            preview.render_heat_overviews(None,[st],maps,10,10,(0,10,0,10),str(root),str(root),settings,products='overview')
                        self.assertEqual(calc.called,layers!='track')
                        self.assertEqual(overlay.called,layers!='track')
                        self.assertEqual(tracks.called,layers!='heat')
                        with Image.open(root/'overview.png') as image:
                            self.assertEqual(image.mode,'RGBA' if background=='transparent' else 'RGB')
                            if background=='transparent':self.assertEqual(image.getpixel((0,0))[3],0)
                            if background=='black':self.assertEqual(image.getpixel((0,0)),(0,0,0))
                            if layers!='heat':self.assertEqual(image.convert('RGB').getpixel((5,5)),(0,255,0))
                            if background=='transparent' and layers=='heat':self.assertEqual(image.getpixel((5,5))[3],128)

    def test_paths_are_opaque_above_heat(self):
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as tmp:
            root=Path(tmp);(root/'gui').mkdir()
            Image.new('RGBA',(10,100),'white').save(root/'gui/ace_heat.png')
            maps=SimpleNamespace(crop=lambda *args:np.full((10,10,3),10,dtype='uint8'))
            st={'S':SimpleNamespace(t0=datetime(2020,1,1))}
            settings={'field':{},'auto_max':True,'legend_max':0,'opacity':.4}
            def heat(frame,*args):frame.paste((255,0,0,255),(0,0,10,10))
            def path(frame,*args):ImageDraw.Draw(frame).line((0,5,9,5),fill=(0,255,0,255),width=1)
            with mock.patch.object(preview,'pixel_ace_field',return_value=(np.zeros((10,10)),{'actual_peak':.41415})),mock.patch.object(preview,'overlay_pixel_heat',side_effect=heat),mock.patch.object(preview,'draw_track',side_effect=path):
                result=preview.render_heat_overviews(None,[st],maps,10,10,(0,10,0,10),str(root),str(root),settings,products='overview')
            with Image.open(root/'overview.png') as image:
                self.assertEqual(image.getpixel((5,5)),(0,255,0))
                self.assertEqual(image.getpixel((5,4)),(255,0,0))
            self.assertEqual(result['legend_max'],.41)

    def test_independent_storm_fields_share_one_season_limit(self):
        a={'S':SimpleNamespace(t0=datetime(2020,1,1)),'dep':'01W'}
        b={'S':SimpleNamespace(t0=datetime(2020,1,2)),'dep':'02W'}
        settings={'field':{},'auto_max':True,'legend_max':0,'opacity':.4}
        def field(storms,*args,**kwargs):
            return np.zeros((10,10)),{'actual_peak':.41415 if len(storms)==2 else .025}
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as tmp:
            root=Path(tmp);(root/'gui').mkdir()
            Image.new('RGBA',(10,100),'white').save(root/'gui/ace_heat.png')
            maps=SimpleNamespace(basin={},crop=lambda *args:np.full((10,10,3),10,dtype='uint8'))
            with mock.patch.object(preview,'pixel_ace_field',side_effect=field) as calculate,mock.patch.object(preview,'overlay_pixel_heat'),mock.patch.object(preview,'draw_track'),mock.patch.object(preview,'full_track',return_value={}),mock.patch.object(preview,'window_for',return_value=(0,10,0,10)):
                result=preview.render_heat_overviews(None,[a,b],maps,10,10,(0,10,0,10),str(root),str(root),settings)
            self.assertEqual([len(call.args[0]) for call in calculate.call_args_list],[2,1,1])
            self.assertEqual({v['legend_max'] for v in result['products'].values()},{.41})
