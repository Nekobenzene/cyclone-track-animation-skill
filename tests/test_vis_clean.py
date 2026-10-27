"""Cloud border removal, signal isolation, screen integration and UTC export."""
import ast
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime/python')]
import numpy as np
from PIL import Image, ImageDraw
from scripts import vis_clean as vc


def cloud_functions():
    path=ROOT/'single/scripts/typhoon_anim.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    names={'extract_cloud','cloud_overlay','cloud_mask'}
    ns=dict(os=os,re=re,json=json,math=math,np=np,Image=Image,subprocess=subprocess,
            _CMASK=None,_NCLOUD=None,CLOUD_R=64,CLOUD_STEP_EVERY=1,_CL={})
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(path),'exec'),ns)
    return ns


class VisCleanTests(unittest.TestCase):
    def test_blue_and_black_backgrounds_leave_no_plate(self):
        for color in [(0,0,0),(12,69,126),(25,80,149)]:
            rgba=vc.process_frame(Image.new('RGB',(200,200),color),size=128)
            self.assertFalse(np.asarray(rgba)[...,3].any())

    def test_connected_white_border_removed_but_isolated_cloud_retained(self):
        im=Image.new('RGB',(200,200),'black'); d=ImageDraw.Draw(im)
        d.polygon([(0,0),(90,0),(0,90)],fill='white')
        d.ellipse((80,80,120,120),fill='white')
        mask=np.asarray(vc.source_validity(im))
        self.assertEqual(mask[10,10],0)
        self.assertEqual(mask[100,100],255)
        rgba=vc.process_frame(im,dict(vc.DEFAULTS,zoom=1),128)
        alpha=np.asarray(rgba)[...,3]
        self.assertGreater(alpha[64,64],220)
        self.assertEqual(alpha[15,15],0)
        self.assertFalse(alpha[[0,-1],:].any())
        self.assertFalse(alpha[:,[0,-1]].any())

    def test_extreme_crop_rotation_and_screen_perimeter(self):
        rgba=vc.process_frame(Image.new('RGB',(210,200),'white'),
            dict(vc.DEFAULTS,center_x=0,center_y=.1,rotation=30),128)
        self.assertFalse(np.asarray(rgba)[...,3].any())  # all-white placeholder is invalid
        im=Image.new('RGB',(200,200),'black'); ImageDraw.Draw(im).ellipse((30,30,170,170),fill='white')
        rgba=vc.process_frame(im,size=128)
        bg=Image.new('RGB',(250,250),(20,40,70))
        out=vc.composite(bg,rgba,(125,125),128)
        arr=np.asarray(out)
        self.assertTrue(np.array_equal(arr[0],np.asarray(bg)[0]))
        self.assertGreater(int(arr[125,125,0]),20)
        self.assertTrue(np.array_equal(np.asarray(vc.screen_plate(rgba))[0],np.zeros((128,3),np.uint8)))

    def test_parameter_validation(self):
        for bad in [{'zoom':0},{'gain':float('nan')},{'surprise':1},{'tint':[1,2,3]}, {'schema':2}]:
            with self.assertRaises((ValueError,TypeError)): vc.settings(bad)
        self.assertEqual(vc.utc('20261014124730'),vc.timestamp('29W_VIS_20261014124730.png'))

    def test_real_encode_gaps_placeholders_and_renderer_cache(self):
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            project=Path(folder); source=project/'sourcedata/frames_VIS_clean'; source.mkdir(parents=True)
            # First placeholder is excluded; the missing 12:52:30 slot holds 12:50.
            for stamp,level in [('20261014124730',None),('20261014125000',160),('20261014125500',240),('20261014125730',None)]:
                im=Image.new('RGB',(128,128),'white' if level is None else 'black')
                if level: ImageDraw.Draw(im).ellipse((24,24,104,104),fill=(level,level,level))
                im.save(source/('29W_VIS_'+stamp+'.png'))
            (source.parent/'track.txt').write_text('20261014120000 140 20 35 1000 TC\n',encoding='utf-8')
            args=SimpleNamespace(start=None,end=None,out=None,size=64,fps=30,step_seconds=150,png=True,track_start=None)
            vc.export(project,source,vc.settings(),args)
            report=json.loads(next((project/'output/vis_clean').glob('*.json')).read_text())
            self.assertEqual(report['frames'],3)
            self.assertEqual(report['held_slots'],1)
            self.assertEqual(report['cloud']['h0'],50/60)
            pngs=sorted(Path(report['rgba_directory']).glob('*.png'))
            self.assertEqual(pngs[0].read_bytes(),pngs[1].read_bytes())
            self.assertNotEqual(pngs[1].read_bytes(),pngs[2].read_bytes())
            self.assertEqual(len(report['excluded']),2)
            ns=cloud_functions(); cloud=project/'build/cloud'; cloud.mkdir()
            ns.update(CLOUD_FILE=report['file'],SRC=str(project/'sourcedata'),CLOUDD=str(cloud),_CL={'format':'screen'})
            with patch.dict(os.environ,PATH=str(ROOT/'runtime/bin')+os.pathsep+os.environ.get('PATH','')):
                ns['extract_cloud']()
                self.assertEqual(len(list(cloud.glob('*.jpg'))),3)
                # Matching source avoids extraction, including clips shorter than 100 frames.
                with patch.object(subprocess,'run',side_effect=AssertionError('unexpected extraction')):
                    ns['extract_cloud']()
                # A changed sample interval invalidates the cache without removing unrelated files.
                (cloud/'notes.txt').write_text('keep')
                ns['CLOUD_STEP_EVERY']=2
                ns['extract_cloud']()
                self.assertEqual(len(list(cloud.glob('*.jpg'))),2)
                self.assertEqual((cloud/'notes.txt').read_text(),'keep')
                ns['CLOUD_STEP_EVERY']=1; ns['extract_cloud']()
            full=np.asarray(ns['cloud_overlay'](0,1))
            self.assertTrue(np.array_equal(np.asarray(ns['cloud_overlay'](.9,1)),full))
            faded=np.asarray(ns['cloud_overlay'](0,.5))
            self.assertFalse(full[0,:,:3].any())
            self.assertTrue(np.all(faded[...,:3]<=full[...,:3]))
            # A small bright spot near the frame edge stays in place (no double crop).
            im=Image.new('RGB',(128,128)); ImageDraw.Draw(im).rectangle((102,60,110,68),fill='white')
            im.save(cloud/'0000.jpg',quality=100)
            ns['_NCLOUD']=None
            out=np.asarray(ns['cloud_overlay'](0,1))
            self.assertGreater(out[64,106,0],240)
            self.assertLess(out[64,64,0],3)
            ns['_CL']={}; ns['_NCLOUD']=None
            legacy=ns['cloud_overlay'](0,1)
            self.assertEqual(legacy.size,(128,128))


if __name__=='__main__': unittest.main()
