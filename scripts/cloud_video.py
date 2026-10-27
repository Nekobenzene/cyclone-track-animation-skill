"""Configure and preview cloud-video overlays for direct single rendering.

typhoon.exe cloud-video configure PROJECT --video SOURCE.mp4 --start-utc UTC --end-utc UTC
typhoon.exe cloud-video preview PROJECT --video SOURCE.mp4 --at 0 10 30 --zoom 1.2
typhoon.exe cloud-video probe PROJECT --video SOURCE.mp4
No website, image sequence or processed cloud-video export is required.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[1])
if not getattr(sys,'frozen',False): sys.path[:0]=[str(ROOT),str(ROOT/'runtime/python')]
from PIL import Image,ImageChops
from scripts import vis_clean
from single.scripts.cloud_video import VideoCloud,endpoint_timing


def background_path(project,explicit=None):
    if explicit: return explicit.resolve()
    choices=[project/'build/video_modes_preview/opening_track_2s.png',project/'output/preview.png']
    path=next((p for p in choices if p.is_file()),None)
    if path is None: raise ValueError('Supply --background with an actual path-video frame')
    return path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['configure','preview','probe'])
    parser.add_argument('project',type=Path)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--background',type=Path)
    parser.add_argument('--config',type=Path,help='Crop/tone/feather JSON; default project/build/cloud_video.json')
    parser.add_argument('--out',type=Path,help='Configuration JSON file, or preview directory')
    parser.add_argument('--at',type=float,nargs='+',default=[0.],help='Preview positions in video seconds')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--start-utc',help='UTC of the actual first source frame')
    group.add_argument('--h0',type=float,help='Manual first-frame hours since earliest track point')
    parser.add_argument('--end-utc',help='UTC of the actual last source frame (inclusive)')
    parser.add_argument('--step-seconds',type=float,help='Manual real observation seconds per original frame')
    parser.add_argument('--center',type=float,nargs=2,metavar=('X','Y'))
    for key in vis_clean.RANGES:
        if key not in ('center_x','center_y'): parser.add_argument('--'+key.replace('_','-'),type=float)
    args=parser.parse_args(argv)
    project=args.project.resolve(); video=args.video.resolve()
    build=project/'build/cloud_video'; build.mkdir(parents=True,exist_ok=True)
    config=(args.config or project/'build/cloud_video.json').resolve()
    if args.config and not config.is_file(): parser.error('--config file does not exist')
    values=json.loads(config.read_text(encoding='utf-8-sig')) if config.is_file() else {}
    values.update({key:getattr(args,key) for key in vis_clean.RANGES if key not in ('center_x','center_y') and getattr(args,key) is not None})
    if args.center: values.update(center_x=args.center[0],center_y=args.center[1])
    cfg=vis_clean.settings(values)
    with VideoCloud(video,cfg) as reader:
        metadata={'video':str(video),'width':reader.width,'height':reader.height,'fps':reader.fps,
                  'frames':reader.count,'duration_seconds':reader.duration}
        if args.command=='probe':
            print(json.dumps(metadata,ensure_ascii=False,indent=2)); return
        if args.command=='preview':
            if any(not math.isfinite(t) or not 0<=t<reader.duration for t in args.at):
                parser.error('--at lies outside the video')
            with Image.open(background_path(project,args.background)) as im:
                background=im.convert('RGB').resize((1920,1080),Image.Resampling.LANCZOS)
            out=(args.out or project/'output/cloud_video_preview').resolve(); out.mkdir(parents=True,exist_ok=True)
            frames=[]
            for seconds in args.at:
                index=min(reader.count-1,int(math.floor(seconds*reader.fps+1e-6)))
                plate=reader.plate(index,420)
                box=(1430,410,1850,830); result=background.copy()
                result.paste(ImageChops.screen(background.crop(box),plate),box)
                name='composite.png' if len(args.at)==1 else f'frame_{index:06d}_composite.png'
                result.save(out/name); frames.append({'frame':index,'video_seconds':index/reader.fps,'file':name})
                print('Composite ->',out/name)
            (out/'preview.json').write_text(json.dumps(dict(metadata,frames=frames,processing=cfg),ensure_ascii=False,indent=2),encoding='utf-8')
            return
        cloud={'file':os.path.relpath(video,project/'sourcedata').replace('\\','/'),
               'format':'vis-clean-video','processing_file':os.path.relpath(config,project/'sourcedata').replace('\\','/')}
        if args.start_utc and args.end_utc and args.step_seconds is None:
            endpoint_timing(args.start_utc,args.end_utc,reader.count,vis_clean.utc(args.start_utc))
            cloud.update(start_utc=vis_clean.utc(args.start_utc).isoformat(),end_utc=vis_clean.utc(args.end_utc).isoformat())
        elif args.h0 is not None and args.step_seconds is not None and not args.end_utc:
            if not math.isfinite(args.h0) or not math.isfinite(args.step_seconds) or args.step_seconds<=0:
                parser.error('Manual mapping needs finite h0 and positive step-seconds')
            cloud.update(h0=args.h0,step_h=args.step_seconds/3600,segment1=[0,reader.count-1],segment2=[0,0],resume_h=0)
        else: parser.error('Configure with --start-utc and --end-utc, or --h0 and --step-seconds')
        config.parent.mkdir(parents=True,exist_ok=True)
        config.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        out=(args.out or project/'build/cloud_video_setup.json').resolve(); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({'cloud':cloud},indent=2,ensure_ascii=False),encoding='utf-8')
        (build/'source.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False),encoding='utf-8')
        print('Processing settings ->',config)
        print('Copy cloud block into project YAML ->',out)


if __name__=='__main__': main()
