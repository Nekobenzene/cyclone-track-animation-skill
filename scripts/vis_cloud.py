"""Small VIS cloud component: resumable directory download, processing and UTC loop.

typhoon.exe vis-cloud fetch|build|run PROJECT --url https://data.dapiya.cn/history/30W/VIS_clean/ --year 2026
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen
import argparse, json, math, os, re, sys, time

ROOT=Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[1])
if not getattr(sys,'frozen',False): sys.path[:0]=[str(ROOT),str(ROOT/'runtime/python')]
from PIL import Image
from scripts import vis_clean


def write_json(path,value):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a': self.links.extend(v for k,v in attrs if k=='href' and v)


def listing_files(text,base,year):
    parsed=urlparse(base)
    if parsed.scheme!='https' or not parsed.netloc or not parsed.path.endswith('/'):
        raise ValueError('Use an HTTPS directory URL ending in /')
    parser=Links();parser.feed(text);files={}
    for link in parser.links:
        url=urljoin(base,link);p=urlparse(url);name=unquote(p.path.rsplit('/',1)[-1])
        if p.netloc!=parsed.netloc or p.path.rsplit('/',1)[0]!=parsed.path.rstrip('/'):
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]+_VIS_\d{14}\.png',name,re.I): continue
        stamp=vis_clean.timestamp(name)
        if stamp.year==year: files[name]=url
    if not files: raise ValueError('No matching VIS PNG observations for requested year')
    return sorted(files.items(),key=lambda item:vis_clean.timestamp(item[0]))


def valid_png(path):
    try:
        with Image.open(path) as im: im.verify()
        return True
    except (OSError,SyntaxError): return False


def download_one(name,url,source,base,retries=3):
    target=source/name;part=source/(name+'.part')
    if target.is_file() and valid_png(target): return dict(file=name,cached=True)
    error=''
    for attempt in range(retries):
        try:
            req=Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':base})
            with urlopen(req,timeout=45) as response,part.open('wb') as dest:
                while block:=response.read(1<<20): dest.write(block)
            if not valid_png(part): raise ValueError('Invalid PNG checksum or incomplete source')
            part.replace(target)
            return dict(file=name,cached=False)
        except (OSError,ValueError) as exc:
            error=str(exc)
            if attempt+1<retries: time.sleep(min(2**attempt,4))
    return dict(file=name,error=error)


def fetch(project,base,year,workers):
    build=project/'build/vis_cloud';build.mkdir(parents=True,exist_ok=True)
    source=project/'sourcedata/frames_VIS_clean';source.mkdir(parents=True,exist_ok=True)
    req=Request(base,headers={'User-Agent':'Mozilla/5.0'})
    with urlopen(req,timeout=60) as response: html=response.read().decode('utf-8')
    (build/'listing.html').write_text(html,encoding='utf-8')
    files=listing_files(html,base,year)
    write_json(build/'snapshot.json',{'url':base,'year':year,'files':files})
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(download_one,name,url,source,base) for name,url in files]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results)%50==0 or len(results)==len(files):
                status={'stage':'download','completed':len(results),'total':len(files),
                        'failed':sum('error' in r for r in results)}
                write_json(build/'status.json',status);print(status,flush=True)
    failures=[r for r in results if 'error' in r]
    report={'source':base,'year':year,'total':len(files),'valid':len(results)-len(failures),
            'rejected':failures,'files':sorted(results,key=lambda r:r['file'])}
    write_json(build/'download_report.json',report)
    if failures:
        raise RuntimeError('Download incomplete: inspect download_report.json; rerun fetch to retry')
    return source


def build_loop(project,args):
    build=project/'build/vis_cloud';build.mkdir(parents=True,exist_ok=True)
    source=(args.source or project/'sourcedata/frames_VIS_clean').resolve()
    cfg=vis_clean.settings(json.loads(args.config.read_text(encoding='utf-8')) if args.config else None)
    settings_path=build/'processing.json';write_json(settings_path,cfg)
    out=(args.out or project/'output/vis_cloud').resolve()
    options=SimpleNamespace(track_start=args.track_start,start=args.start,end=args.end,
        step_seconds=args.step_seconds,size=args.size,fps=args.fps,png=False,out=out)
    write_json(build/'status.json',{'stage':'process_encode'})
    vis_clean.export(project,source,cfg,options)
    # Export writes an exact report per loop. Pick the newly generated UTC name.
    reports=sorted(out.glob('VIS_clean_screen_*.json'),key=lambda p:p.stat().st_mtime_ns)
    report=json.loads(reports[-1].read_text(encoding='utf-8'))
    report['cloud']['fade_out_seconds']=.5
    write_json(build/'cloud_config.json',{'cloud':report['cloud']})
    write_json(build/'recipe.json',{'command':'vis-cloud build','project':str(project),
        'source':str(source),'processing_file':str(settings_path),'start':args.start,'end':args.end,
        'step_seconds':args.step_seconds,'fps':args.fps,'size':args.size,'report':str(reports[-1])})
    write_json(build/'status.json',{'stage':'complete','video':report['file'],'frames':report['frames']})
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['fetch','build','run']);p.add_argument('project',type=Path)
    p.add_argument('--url');p.add_argument('--year',type=int)
    p.add_argument('--workers',type=int,default=12)
    p.add_argument('--source',type=Path);p.add_argument('--config',type=Path);p.add_argument('--out',type=Path)
    p.add_argument('--start');p.add_argument('--end');p.add_argument('--track-start')
    p.add_argument('--size',type=int,default=512);p.add_argument('--fps',type=int,default=30)
    p.add_argument('--step-seconds',type=float,default=150)
    args=p.parse_args(argv);project=args.project.resolve()
    if not (project/'sourcedata').is_dir(): p.error('Expected project/sourcedata')
    if not 1<=args.workers<=24 or not 1<=args.fps<=120 or not math.isfinite(args.step_seconds) or args.step_seconds<=0:
        p.error('Invalid workers/fps/observation interval')
    if not 32<=args.size<=4096 or args.size%2: p.error('Size must be even, 32..4096')
    if args.command in ('fetch','run'):
        if not args.url or not args.year: p.error('fetch/run require --url and --year')
        fetch(project,args.url,args.year,args.workers)
    if args.command in ('build','run'): build_loop(project,args)


if __name__=='__main__': main()
