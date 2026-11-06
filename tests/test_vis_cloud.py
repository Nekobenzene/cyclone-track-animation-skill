from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io, json, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime/python')]
from PIL import Image,ImageDraw
from scripts import vis_cloud as v


class VisCloudTests(unittest.TestCase):
    def test_listing_filters_year_parent_and_foreign_links(self):
        base='https://example.org/history/30W/VIS_clean/'
        html=''.join('<a href="'+p+'">x</a>' for p in [
            '30W_VIS_20261025125000.png','30W_VIS_20251025125000.png',
            '../30W_VIS_20261025125000.png','https://other.org/30W_VIS_20261025125000.png',
            '30W_VIS_20261025125000.png'])
        self.assertEqual(v.listing_files(html,base,2026),
                         [('30W_VIS_20261025125000.png',base+'30W_VIS_20261025125000.png')])
        with self.assertRaises(ValueError): v.listing_files(html,base,2024)

    def test_valid_download_is_atomic_and_existing_file_is_reused(self):
        (ROOT/'build').mkdir(exist_ok=True)
        buf=io.BytesIO();Image.new('RGB',(20,20),'white').save(buf,format='PNG');data=buf.getvalue()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            source=Path(temp)
            with patch.object(v,'urlopen',side_effect=lambda *a,**k:io.BytesIO(data)) as request:
                result=v.download_one('30W_VIS_20261025125000.png','https://example.org/a',source,'https://example.org/')
                self.assertFalse(result['cached'])
                self.assertTrue(v.download_one(result['file'],'https://example.org/a',source,'https://example.org/')['cached'])
                self.assertEqual(request.call_count,1)
            self.assertFalse(any(source.glob('*.part')))

    def test_build_emits_real_video_recipe_and_screen_config(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            project=Path(temp);source=project/'sourcedata/frames_VIS_clean';source.mkdir(parents=True)
            (project/'sourcedata/track.txt').write_text('20261025000000 130 20 50 990 TC\n',encoding='utf-8')
            for stamp in ['20261025120000','20261025120500']:
                im=Image.new('RGB',(64,64),(0,40,100));ImageDraw.Draw(im).ellipse((15,15,49,49),fill='white')
                im.save(source/f'30W_VIS_{stamp}.png')
            args=SimpleNamespace(source=None,config=None,out=None,start=None,end=None,track_start=None,
                                 step_seconds=150,size=64,fps=10)
            report=v.build_loop(project,args)
            self.assertEqual(report['frames'],3)
            config=json.loads((project/'build/vis_cloud/cloud_config.json').read_text())['cloud']
            self.assertEqual(config['format'],'screen');self.assertEqual(config['fade_out_seconds'],.5)
            self.assertEqual(config['h0'],12)
            self.assertTrue(Path(report['file']).is_file())


if __name__=='__main__': unittest.main()
