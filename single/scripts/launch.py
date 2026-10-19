"""Launch the single renderer from a project containing only sourcedata/."""
from pathlib import Path
import argparse, os, sys, subprocess, importlib

def main(argv=None, renderer_module=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('command', nargs='?', default='all',
                        choices=['all','info','preview','preview-black','assets','render','audio','mux','poster','test'])
    parser.add_argument('--assets', type=Path, help='Shared SMCY1.3 asset folder')
    parser.add_argument('--background',choices=['map','black','transparent'])
    parser.add_argument('--layers',choices=['both','track','heat'])
    parser.add_argument('--size',help='Static preview size: native or WxH')
    parser.add_argument('--heat-parameters')
    args = parser.parse_args(argv)
    preview_flags=[]
    for key in ('background','layers','size','heat_parameters'):
        value=getattr(args,key)
        if value is not None:preview_flags += ['--'+key.replace('_','-'),value]
    if preview_flags and args.command not in ('preview','preview-black'):
        parser.error('Background/layers/size/heat parameters apply to static preview commands')

    shared = Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[2])
    skill = shared/'single'
    deps = shared/'runtime/python'
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(deps))
    os.environ['PYTHONPATH'] = str(deps) + os.pathsep + os.environ.get('PYTHONPATH','')
    os.environ['PATH'] = str(shared/'runtime/bin') + os.pathsep + os.environ.get('PATH','')
    for module in ['numpy','PIL','cv2','yaml']:
        try: importlib.import_module(module)
        except ImportError as exc:
            raise SystemExit(f'Skill runtime unavailable for {sys.version}: {module}: {exc}')
    for tool in ['ffmpeg','ffprobe']:
        subprocess.run([tool,'-version'], check=True, stdout=subprocess.DEVNULL)
    import yaml
    project = args.project.resolve()
    if not (project/'sourcedata').is_dir():
        raise SystemExit('Expected <project>/sourcedata/')
    configs = sorted((project/'build').glob('*.yaml')) + sorted((project/'build').glob('*.yml'))
    if len(configs)>1:
        raise SystemExit('Multiple configs: use typhoon_anim.py --config <file> explicitly')
    if configs:
        config = configs[0]
    else:
        candidates = ([args.assets.resolve()] if args.assets else [])
        candidates += [shared/'assets/SMCY1.3']
        candidates += [p/'res/SMCY1.3' for p in project.parents]
        assets = next((p for p in candidates if (p/'map/basins/EARTH.png').is_file()),None)
        if assets is None:
            raise SystemExit('Shared SMCY1.3 pack not found; pass --assets <folder>')
        build = project/'build'
        build.mkdir(exist_ok=True)
        config = build/'storm.yaml'
        cfg = {'paths': {'storm':'..', 'assets':Path(os.path.relpath(assets,build)).as_posix(),
                         'sourcedata':'sourcedata','build':'build','output':'output'},
               'storm':{'id':project.name,'title':project.name,'name_en':project.name},
               'view':{'panorama':'auto'},
               'output':{'width':1920,'height':1080,'fps':120,
                         'mp4':project.name+'_1920x1080_120fps.mp4'}, 'data':{}}
        # A source-only project needs a real peak for banner category/tint.
        sys.path.insert(0, str(skill/'scripts'))
        if renderer_module is None:
            import typhoon_anim as renderer
        else:
            renderer = renderer_module
        import numpy as np
        initial = dict(cfg, paths=dict(cfg['paths'], storm=str(project), assets=str(assets)))
        renderer._apply_config(initial)
        renderer._bind_paths()
        series = renderer.Series()
        tc = [i for i, phase in enumerate(series.phase) if phase == 'TC']
        candidates = tc or list(range(len(series.hours)))
        index = max(candidates, key=lambda i: float(series.WF(series.hours[i])))
        h = float(series.hours[index])
        wind, pres = float(series.WF(h)), float(series.PF(h))
        cfg['data']['peaks'] = [dict(h=h, lon=float(series.lon[index]),
                                    lat=float(series.lat[index]), label='PEAK 1',
                                    graph='P1 %.0f/%.0f' % (wind,pres),
                                    summary='%.0f kt / %.0f hPa' % (wind,pres))]
        with config.open('x',encoding='utf-8') as f:
            yaml.safe_dump(cfg,f,allow_unicode=True,sort_keys=False)
    if renderer_module is not None:
        renderer_module.main(['--config',str(config),args.command]+preview_flags)
    else:
        subprocess.run([sys.executable,'-u',str(skill/'scripts/typhoon_anim.py'),
                        '--config',str(config),args.command]+preview_flags,check=True)

if __name__ == '__main__':
    main()
