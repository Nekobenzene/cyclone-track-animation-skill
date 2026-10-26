import ast
from pathlib import Path
import re
import tempfile
import unittest
from types import SimpleNamespace
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]

class SelectionTests(unittest.TestCase):
    def test_overview_render_does_not_need_cli_globals(self):
        tree=ast.parse((ROOT/'scripts/track_preview.py').read_text(encoding='utf-8'))
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='render_overview']
        ns={'Image':Image,'make_proj':lambda *a:None,'load_pass1':lambda:None}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'overview','exec'),ns)
        maps=SimpleNamespace(crop=lambda *a:__import__('numpy').zeros((8,16,3),dtype='uint8'))
        (ROOT/'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
            out=Path(temp)/'overview.png'
            ns['render_overview']([],maps,16,8,(0,16,0,8),str(out),log=lambda *a:None)
            with Image.open(out) as image:self.assertEqual(image.size,(16,8))

    def test_num_identifiers(self):
        tree=ast.parse((ROOT/'scripts/track_preview.py').read_text(encoding='utf-8'))
        ns={'re':re}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('select_storms','out_name')],type_ignores=[]),'selection','exec'),ns)
        a={'dir':'misleading_02W','dep':'01W','jma':'202001'}
        b={'dir':'other','dep':'','jma':'202614 202616'}
        c={'dir':'nolo','dep':'15E','jma':'202628'}
        storms=[a,b,c]
        self.assertEqual(ns['select_storms'](storms,['season']),('overview',None))
        self.assertEqual(ns['select_storms'](storms,['all']),('all',None))
        self.assertEqual(ns['select_storms'](storms,['01w','202001','202616'])[1],[a,b])
        self.assertEqual(ns['select_storms'](storms,['15E'])[1],[c])
        for tokens in (['02W'],['01'],['202099'],['all','01W']):
            with self.assertRaises(ValueError):ns['select_storms'](storms,tokens)
        with self.assertRaises(ValueError):ns['select_storms'](storms+[dict(c,dep='01W')],['01W'])
        self.assertEqual(ns['out_name'](b),'202614.png')
        self.assertEqual(ns['out_name'](c),'15E.png')
