"""Direct video cloud decoding, cache bounds, timing and renderer integration."""
import json
import math
from datetime import datetime,timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime/python')]
import cv2
import numpy as np
from PIL import Image,ImageDraw
from scripts import vis_clean
from single.scripts.cloud_video import VideoCloud,endpoint_timing
from single.scripts import typhoon_anim as ta


class VideoCloudTests(unittest.TestCase):
    def setUp(self):
        names=['CFG','_S','_D','_CONFIG_DIR','_CL','S','KEY','DAMAGE','LANDFALLS','CLOUD_FILE','CLOUDD','SRC',
               'CLOUD_R','CLOUD_H0','CLOUD_STEP','CLOUD_F0','CLOUD_F1','CLOUD_G0','CLOUD_G1',
               'CLOUD_HA','CLOUD_HB','CLOUD_HEND','CLOUD_STEP_EVERY','_CLOUD_VIDEO']
        self.saved={key:getattr(ta,key) for key in names}

    def tearDown(self):
        if ta._CLOUD_VIDEO is not None and ta._CLOUD_VIDEO is not self.saved['_CLOUD_VIDEO']:
            ta._CLOUD_VIDEO.close()
        for key,value in self.saved.items(): setattr(ta,key,value)

    @classmethod
    def setUpClass(cls):
        (ROOT/'build').mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=ROOT/'build')
        cls.project=Path(cls.temp.name); cls.src=cls.project/'sourcedata'; cls.src.mkdir()
        cls.video=cls.src/'cloud.mp4'
        # Long GOP exercises actual seek correctness, including reverse poster/test order.
        encoder=subprocess.Popen([str(ROOT/'runtime/bin/ffmpeg.exe'),'-v','error','-y','-f','rawvideo',
            '-pix_fmt','rgb24','-s','128x96','-r','30','-i','-','-c:v','libx264','-g','120','-crf','12',
            '-pix_fmt','yuv420p',str(cls.video)],stdin=subprocess.PIPE)
        for i in range(210):
            im=Image.new('RGB',(128,96),(10,65,125) if i<105 else (0,0,0))
            d=ImageDraw.Draw(im); d.rectangle((35,30,90,70),fill=(70+i%180,)*3)
            d.rectangle((0,0,8,95),fill='white')
            encoder.stdin.write(im.tobytes())
        encoder.stdin.close(); assert encoder.wait()==0

    @classmethod
    def tearDownClass(cls):
        if ta._CLOUD_VIDEO is not None: ta._CLOUD_VIDEO.close(); ta._CLOUD_VIDEO=None
        cls.temp.cleanup()

    def test_seek_matches_sequential_decode_and_visual_pipeline(self):
        reference={}
        cap=cv2.VideoCapture(str(self.video),cv2.CAP_FFMPEG)
        wanted={0,1,4,104,105,143,201,209}
        for i in range(210):
            ok,frame=cap.read(); self.assertTrue(ok)
            if i in wanted: reference[i]=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        cap.release()
        with VideoCloud(self.video) as reader:
            for index in (0,201,4,209,104,105,143,1):
                self.assertTrue(np.array_equal(np.asarray(reader.read(index)),reference[index]),index)
                expected=vis_clean.screen_plate(vis_clean.process_frame(Image.fromarray(reference[index]),size=128))
                actual=reader.plate(index,128)
                self.assertTrue(np.array_equal(np.asarray(actual),np.asarray(expected)),index)
                self.assertFalse(np.asarray(actual)[0].any())

    def test_duplicate_frames_cache_is_bounded_and_not_mutable(self):
        with VideoCloud(self.video,cache_bytes=128*128*3*2) as reader:
            first=reader.plate(0,128); original=first.tobytes()
            first.paste('red',(0,0,128,128))
            self.assertEqual(reader.plate(0,128).tobytes(),original)
            self.assertEqual(reader.processed_frames,1)
            self.assertEqual(reader.decoded_frames,1)
            for index in (1,2,3): reader.plate(index,128)
            self.assertLessEqual(reader.cached_bytes,128*128*3*2)
            self.assertEqual(len(reader.cache),2)
            with self.assertRaises(ValueError): reader.plate(210)
            reader.close()
            with self.assertRaises(ValueError): reader.read(0)

    def setup_renderer(self):
        if ta._CLOUD_VIDEO is not None: ta._CLOUD_VIDEO.close()
        ta._CLOUD_VIDEO=None
        ta.SRC=str(self.src); ta.CLOUDD=str(self.project/'build/no_extracted_clouds')
        ta.CLOUD_FILE='cloud.mp4'; ta.CLOUD_R=64
        ta.CLOUD_H0=5.; ta.CLOUD_STEP=1/6
        ta.CLOUD_F0=2; ta.CLOUD_F1=10; ta.CLOUD_G0=15; ta.CLOUD_G1=20
        ta.CLOUD_HA=5+8/6; ta.CLOUD_HB=8.; ta.CLOUD_HEND=8+5/6
        ta.CLOUD_STEP_EVERY=1; ta._CL={'format':'vis-clean-video','processing':dict(vis_clean.DEFAULTS)}

    def test_renderer_directly_reads_video_without_extraction_or_future_frame(self):
        self.setup_renderer()
        with patch.object(ta.subprocess,'run',side_effect=AssertionError('must not extract to disk')):
            ta.extract_cloud()
        self.assertFalse(Path(ta.CLOUDD).exists())
        self.assertEqual(ta.cloud_state(4.99),(None,False))
        self.assertEqual(ta.cloud_state(5),(2.,True))
        self.assertEqual(ta.cloud_state(7),(None,False))
        self.assertEqual(ta.cloud_state(8),(15.,True))
        self.assertEqual(ta.cloud_state(9),(20,True))
        first=ta.cloud_overlay(2,1)
        self.assertEqual(first.tobytes(),ta.cloud_overlay(2.99,1).tobytes())
        self.assertEqual(ta._CLOUD_VIDEO.processed_frames,1)
        self.assertTrue(np.all(np.asarray(ta.cloud_overlay(2,.5))[...,:3]<=np.asarray(first)[...,:3]))

    def test_bad_ranges_and_missing_processing_fail_explicitly(self):
        self.setup_renderer(); ta.CLOUD_F1=210
        with self.assertRaisesRegex(ValueError,'segments'): ta._get_cloud_video()
        ta.CLOUD_F1=10; ta._CL['processing_file']='missing.json'
        ta._CL.pop('processing')
        with self.assertRaises(FileNotFoundError): ta._get_cloud_video()

    def test_utc_endpoints_use_frame_centres_and_actual_track_origin(self):
        timing=endpoint_timing('20261014120000','20261014200000',210,datetime(2026,10,14))
        self.assertEqual(timing['h0'],12)
        self.assertAlmostEqual(timing['step_h']*209,8)
        for first,last,count in [('20261014200000','20261014120000',210),('20261014120000','20261014200000',1)]:
            with self.assertRaises(ValueError): endpoint_timing(first,last,count,datetime(2026,10,14))
        (self.src/'track.txt').write_text('20261014000000 140 20 50 990 TC\n20261015000000 141 21 50 990 TC\n',encoding='utf-8')
        cfg={'paths':{'storm':str(self.project),'assets':str(ROOT/'assets/SMCY1.3'),
                      'cache':str(self.project/'build/cache')},
             'cloud':{'format':'vis-clean-video','file':'cloud.mp4',
                      'start_utc':'20261014120000','end_utc':'20261014200000'}}
        ta._apply_config(cfg); ta._bind_paths(); ta._build()
        self.assertEqual(ta.CLOUD_H0,12)
        self.assertAlmostEqual(ta.cloud_state(20)[0],209)
        self.assertEqual(ta.CLOUD_STEP_EVERY,1)
        self.assertNotIn('h0',cfg['cloud'])  # no mutation of the user's source configuration
        self.assertFalse(Path(ta.CLOUDD).exists())
        cfg['cloud']['step_h']=1
        with self.assertRaisesRegex(ValueError,'Choose UTC'): ta._build()


if __name__=='__main__': unittest.main()
