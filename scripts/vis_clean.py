"""Crop VIS_CLEAN imagery into edge-free cloud overlays; offline tuner and UTC export.

typhoon.exe vis-clean tune PROJECT
typhoon.exe vis-clean preview PROJECT --frame NAME.png --config build/vis_clean.json
typhoon.exe vis-clean export PROJECT --config build/vis_clean.json --start UTC --end UTC
"""
from __future__ import annotations
import argparse
import base64
import bisect
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[1])
if not getattr(sys,'frozen',False): sys.path.insert(0,str(ROOT/'runtime/python'))
import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw

DEFAULTS=dict(schema=1,center_x=.5,center_y=.5,zoom=1.15,rotation=0.,
              black_level=.035,white_level=.97,gamma=1.02,gain=1.12,
              blue_removal=1.1,feather=.42,radius=1.,opacity=.94,
              border_softness=.025,tint=[.94,.97,1.])
RANGES=dict(center_x=(0,1),center_y=(0,1),zoom=(1,5),rotation=(-30,30),
            black_level=(0,.5),white_level=(.5,1),gamma=(.25,3),gain=(.1,3),
            blue_removal=(0,3),feather=(.05,.8),radius=(.4,1),opacity=(0,1),
            border_softness=(.005,.15))

def settings(values=None):
    if values is None: values={}
    if not isinstance(values,dict): raise ValueError('Settings must be a JSON object')
    unknown=set(values)-set(DEFAULTS)
    if unknown: raise ValueError('Unknown settings: '+', '.join(sorted(unknown)))
    cfg=dict(DEFAULTS,**values)
    if cfg['schema']!=1: raise ValueError('Unsupported settings schema')
    for key,(low,high) in RANGES.items():
        value=float(cfg[key])
        if not math.isfinite(value) or not low<=value<=high: raise ValueError('Invalid '+key)
        cfg[key]=value
    if cfg['white_level']<=cfg['black_level']: raise ValueError('White level must exceed black level')
    if not isinstance(cfg['tint'],(list,tuple)) or len(cfg['tint'])!=3 or any(not math.isfinite(float(v)) or not 0<=float(v)<=1 for v in cfg['tint']):
        raise ValueError('tint must contain three values between zero and one')
    cfg['tint']=[float(v) for v in cfg['tint']]
    return cfg

def timestamp(name):
    match=re.search(r'(\d{14})(?=\.[^.]+$)',Path(name).name)
    if not match: raise ValueError('Filename needs a 14-digit UTC timestamp: '+str(name))
    return datetime.strptime(match.group(1),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)

def utc(value):
    if re.fullmatch(r'\d{14}',value): return datetime.strptime(value,'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

def source_validity(image):
    """Remove only near-white components connected to the product's outer border."""
    image=image.convert('RGBA')
    w,h=image.size
    scale=min(1.,768/max(w,h))
    small=image.resize((max(1,round(w*scale)),max(1,round(h*scale))),Image.Resampling.BILINEAR)
    rgb=np.asarray(small)[...,:3]
    white=((rgb.min(axis=2)>=248)&(np.ptp(rgb,axis=2)<=4)).astype(np.uint8)
    _,labels=cv2.connectedComponents(white,connectivity=8)
    border=np.unique(np.concatenate([labels[0],labels[-1],labels[:,0],labels[:,-1]]))
    border=border[border!=0]
    valid=~np.isin(labels,border)
    valid=valid.astype(np.uint8)*np.asarray(small)[...,3]
    return Image.fromarray(valid).resize((w,h),Image.Resampling.BILINEAR)

def process_frame(image,cfg=None,size=512):
    cfg=settings(cfg)
    if not isinstance(size,int) or not 32<=size<=4096: raise ValueError('size must be 32..4096')
    image=image.convert('RGBA')
    w,h=image.size
    span=min(w,h)/cfg['zoom']
    angle=math.radians(cfg['rotation'])
    cs,sn=math.cos(angle)*span/size,math.sin(angle)*span/size
    transform=(cs,-sn,cfg['center_x']*w-(cs-sn)*size/2,
               sn,cs,cfg['center_y']*h-(sn+cs)*size/2)
    crop=image.convert('RGB').transform((size,size),Image.Transform.AFFINE,transform,
                                         Image.Resampling.BICUBIC,fillcolor=(0,0,0))
    valid=source_validity(image).transform((size,size),Image.Transform.AFFINE,transform,
                                         Image.Resampling.BILINEAR,fillcolor=0)
    rgb=np.asarray(crop,dtype=np.float32)/255
    # Min-channel neutral luminance rejects blue ocean while retaining cloud texture.
    neutral=rgb.min(axis=2)-cfg['blue_removal']*np.maximum(rgb[...,2]-rgb[...,0],0)
    signal=np.clip((neutral-cfg['black_level'])/(cfg['white_level']-cfg['black_level']),0,1)
    signal=np.clip(signal**cfg['gamma']*cfg['gain'],0,1)
    yy,xx=np.mgrid[:size,:size].astype(np.float32)
    distance=np.hypot((xx+.5-size/2)/(size/2),(yy+.5-size/2)/(size/2))
    feather=np.clip((cfg['radius']-distance)/cfg['feather'],0,1)
    feather=feather*feather*(3-2*feather)
    valid=np.asarray(valid)>250
    padded=np.pad(valid.astype(np.uint8),1)
    edge=cv2.distanceTransform(padded,cv2.DIST_C,3)[1:-1,1:-1]
    edge=np.clip(edge/(size*cfg['border_softness']),0,1)
    edge=edge*edge*(3-2*edge)
    alpha=np.clip(signal*feather*edge*cfg['opacity'],0,1)
    alpha[[0,-1],:]=0; alpha[:,[0,-1]]=0
    rgba=np.empty((size,size,4),dtype=np.uint8)
    rgba[...,:3]=np.rint(np.array(cfg['tint'])*255).astype(np.uint8)
    rgba[...,3]=np.rint(alpha*255).astype(np.uint8)
    return Image.fromarray(rgba,'RGBA')

def screen_plate(rgba):
    arr=np.asarray(rgba,dtype=np.float32)
    return Image.fromarray(np.rint(arr[...,:3]*arr[...,3:4]/255).astype(np.uint8),'RGB')

def composite(background,rgba,center=(1640,620),diameter=420):
    background=background.convert('RGB').copy()
    plate=screen_plate(rgba).resize((diameter,diameter),Image.Resampling.LANCZOS)
    x,y=round(center[0]-diameter/2),round(center[1]-diameter/2)
    left,top,right,bottom=max(x,0),max(y,0),min(x+diameter,background.width),min(y+diameter,background.height)
    if right<=left or bottom<=top: return background
    plate=plate.crop((left-x,top-y,right-x,bottom-y))
    box=(left,top,right,bottom)
    background.paste(ImageChops.screen(background.crop(box),plate),box)
    return background

def image_url(image,max_size=1024):
    import io
    image=image.copy(); image.thumbnail((max_size,max_size),Image.Resampling.LANCZOS)
    out=io.BytesIO(); image.save(out,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()

def inventory(source):
    frames=[]
    for path in source.glob('*.png'):
        try: frames.append((timestamp(path.name),path))
        except ValueError: continue
    frames.sort()
    if not frames: raise ValueError('No timestamped PNG files in '+str(source))
    if len({t for t,_ in frames})!=len(frames): raise ValueError('Duplicate UTC source timestamps')
    return frames

def tune(project,source,cfg,out,background):
    files=inventory(source)
    samples=[]
    for i in sorted(set(round(j*(len(files)-1)/7) for j in range(8))):
        time,path=files[i]
        try:
            with Image.open(path) as im:
                if max(hi-lo for lo,hi in im.convert('RGB').getextrema())<3: continue
                samples.append({'name':path.name,'utc':time.isoformat(),'url':image_url(im)})
        except (OSError,SyntaxError): continue
    if not samples: raise ValueError('All sampled source files are placeholders or incomplete')
    with Image.open(background) as im: base=image_url(im,1920)
    payload={'settings':cfg,'samples':samples,'background':base,
             'project':str(project),'source':str(source),'frame_count':len(files)}
    template=(ROOT/'single/templates/vis_clean_tuner.html').read_text(encoding='utf-8')
    text=template.replace('/*__PAYLOAD__*/',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c'))
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(text,encoding='utf-8')
    print('Tuner ->',out)

def export(project,source,cfg,args):
    track_start=utc(args.track_start) if args.track_start else detect_track_start(project)
    all_files=inventory(source)
    start=utc(args.start) if args.start else all_files[0][0]
    end=utc(args.end) if args.end else all_files[-1][0]
    if start<all_files[0][0] or end>all_files[-1][0] or end<start:
        raise ValueError('Requested UTC range is outside the available source snapshot')
    frames=[]; excluded=[]
    # Find a valid predecessor without an arbitrary maximum gap. Read only the
    # requested range and preceding candidates, not the whole downloaded archive.
    candidates=[entry for entry in all_files if start<=entry[0]<=end]
    earlier=[entry for entry in all_files if entry[0]<start]
    def usable(path):
        try:
            with Image.open(path) as im:
                if max(hi-lo for lo,hi in im.convert('RGB').getextrema())<3:
                    return False
            return True
        except (OSError,SyntaxError): return False
    for entry in reversed(earlier):
        if usable(entry[1]):
            frames.append(entry); break
        excluded.append(entry[1].name)
    for t,path in candidates:
        if usable(path): frames.append((t,path))
        else: excluded.append(path.name)
    if not args.start and frames: start=frames[0][0]
    if not frames or frames[0][0]>start: raise ValueError('No valid source observation at or before start')
    end=min(end,frames[-1][0])
    count=math.floor((end-start).total_seconds()/args.step_seconds)+1
    if count<=0: raise ValueError('No valid observation range')
    out=Path(args.out).resolve() if args.out else project/'output/vis_clean'
    out.mkdir(parents=True,exist_ok=True)
    build=project/'build/vis_clean_tool'; build.mkdir(parents=True,exist_ok=True)
    stamp=start.strftime('%Y%m%dT%H%M%SZ')
    name='VIS_clean_screen_'+stamp
    png=out/(name+'_rgba')
    if args.png:
        png.mkdir(exist_ok=True)
        if any(png.iterdir()): raise ValueError('RGBA output directory already exists; choose a new --out directory')
    final=out/(name+'.mp4'); temporary=build/(name+'.partial.mp4')
    ffmpeg=str(ROOT/'runtime/bin/ffmpeg.exe')
    ffprobe=str(ROOT/'runtime/bin/ffprobe.exe')
    p=subprocess.Popen([ffmpeg,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{args.size}x{args.size}',
                        '-r',str(args.fps),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','14',
                        '-pix_fmt','yuv420p','-movflags','+faststart',str(temporary)],stdin=subprocess.PIPE)
    times=[t for t,_ in frames]
    cached=None; held=0; last=None
    try:
        for i in range(count):
            t=start+timedelta(seconds=i*args.step_seconds)
            j=bisect.bisect_right(times,t)-1
            held+=t!=times[j]
            if j!=last:
                with Image.open(frames[j][1]) as im: rgba=process_frame(im,cfg,args.size)
                cached=screen_plate(rgba).tobytes(); last=j
            if args.png:
                rgba.save(png/(f'{i:06d}_'+t.strftime('%Y%m%d%H%M%S%f')+'.png'))
            p.stdin.write(cached)
            if i%100==0: print('Processed',i,'/',count,flush=True)
        p.stdin.close()
        if p.wait()!=0: raise RuntimeError('FFmpeg failed')
    except BaseException:
        if p.poll() is None: p.terminate(); p.wait()
        raise
    probe=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-show_format','-of','json',str(temporary)]))
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    if int(video['nb_frames'])!=count: raise RuntimeError('Encoded frame count does not match UTC grid')
    temporary.replace(final)
    cloud={'file':os.path.relpath(final,project/'sourcedata').replace('\\','/'),'format':'screen',
           'extract_every':1,'h0':(start-track_start).total_seconds()/3600 if track_start else None,
           'step_h':args.step_seconds/3600,'segment1':[0,count-1],'segment2':[0,0],'resume_h':0.}
    result={'schema':1,'source':str(source),'source_files_snapshot':len(all_files),'start_utc':start.isoformat(),
            'last_grid_utc':(start+timedelta(seconds=(count-1)*args.step_seconds)).isoformat(),
            'fps':args.fps,'step_seconds':args.step_seconds,'frames':count,'held_slots':held,'excluded':excluded,
            'gap_policy':'hold previous actual observation; no synthesized interpolation',
            'observations':[{'utc':t.isoformat(),'file':p.name} for t,p in frames],
            'settings':cfg,'cloud':cloud,'file':str(final),'rgba_directory':str(png) if args.png else None,
            'attribution':'Cloud imagery: dapiya.cn VIS_clean'}
    (out/(name+'.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Screen video ->',final)
    print('Renderer cloud config ->',out/(name+'.json'))

def detect_track_start(project):
    source=project/'sourcedata'
    paths=[source/'track.txt'] if (source/'track.txt').is_file() else [source/(n+'.txt') for n in
        ('DB','WV','MD','TC','RV','EX','SD','SS','DB-LO','DB-aL','DB-WV','DB-MD')]
    times=[]
    for path in paths:
        if not path.is_file(): continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.split('#',1)[0].strip()
            if line: times.append(utc(line.split()[0]))
    return min(times) if times else None

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['tune','preview','export'])
    parser.add_argument('project',type=Path)
    parser.add_argument('--source',type=Path,help='Default: <project>/sourcedata/frames_VIS_clean')
    parser.add_argument('--config',type=Path,help='JSON downloaded from the offline tuner')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--background',type=Path,help='Actual path-video frame for composite preview')
    parser.add_argument('--frame',help='Filename or full path; preview only')
    parser.add_argument('--size',type=int,default=512)
    parser.add_argument('--start'); parser.add_argument('--end')
    parser.add_argument('--track-start',help='Override earliest path UTC for h0 (custom track filenames)')
    parser.add_argument('--step-seconds',type=float,default=150)
    parser.add_argument('--fps',type=int,default=30)
    parser.add_argument('--png',action='store_true',help='Also export straight-alpha RGBA PNG sequence')
    args=parser.parse_args(argv)
    project=args.project.resolve()
    build=project/'build/vis_clean_tool'; build.mkdir(parents=True,exist_ok=True)
    source=(args.source if args.source else project/'sourcedata/frames_VIS_clean').resolve()
    cfg=settings(json.loads(args.config.read_text(encoding='utf-8')) if args.config else None)
    if not 32<=args.size<=4096 or args.size%2: parser.error('--size must be even, 32..4096')
    if not math.isfinite(args.step_seconds) or args.step_seconds<=0 or not 1<=args.fps<=120: parser.error('Invalid time grid/fps')
    if args.command in ('tune','preview') and not args.background:
        candidates=[project/'build/video_modes_preview/opening_track_2s.png',project/'output/preview.png',project/'output/preview/preview.png']
        args.background=next((p for p in candidates if p.is_file()),None)
        if not args.background: parser.error('Supply --background with a path-video frame')
    if args.command=='tune':
        tune(project,source,cfg,args.out or project/'output/vis_clean_tuner.html',args.background)
    elif args.command=='preview':
        file=Path(args.frame) if args.frame else inventory(source)[0][1]
        if not file.is_absolute(): file=source/file
        out=args.out or project/'output/vis_clean_preview'; out.mkdir(parents=True,exist_ok=True)
        with Image.open(file) as im: rgba=process_frame(im,cfg,args.size)
        rgba.save(out/'cloud_rgba.png'); screen_plate(rgba).save(out/'cloud_screen.png')
        with Image.open(args.background) as base: composite(base,rgba).save(out/'composite.png')
        (out/'settings.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        print('Preview ->',out)
    else: export(project,source,cfg,args)

if __name__=='__main__': main()
