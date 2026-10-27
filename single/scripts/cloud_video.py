"""On-demand video decoding and VIS_CLEAN screen plates for the single renderer.

No extracted image sequence or processed cloud video is written to disk.
"""
from collections import OrderedDict
from datetime import timezone
import math
import os
from pathlib import Path
import sys

ROOT=Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[2])
if not getattr(sys,'frozen',False):
    sys.path[:0]=[str(ROOT),str(ROOT/'runtime/python')]
import cv2
import numpy as np
from PIL import Image
from scripts import vis_clean


def endpoint_timing(start,end,count,track_start):
    """Uniform observations, with both timestamps identifying actual frame centres."""
    first,last=vis_clean.utc(start),vis_clean.utc(end)
    if count<2 or last<=first: raise ValueError('UTC endpoints need at least two frames and end after start')
    if track_start.tzinfo is None: track_start=track_start.replace(tzinfo=timezone.utc)
    return {'h0':(first-track_start).total_seconds()/3600,
            'step_h':(last-first).total_seconds()/3600/(count-1),
            'segment1':[0,count-1],'segment2':[0,0],'resume_h':0.}


class VideoCloud:
    """One decoder, bounded processed-frame cache, sequential grabs and exact seeks."""
    def __init__(self,path,processing=None,cache_bytes=24*1024*1024):
        self.path=Path(path).resolve()
        if not self.path.is_file(): raise ValueError('Cloud video missing: '+str(self.path))
        self.processing=vis_clean.settings(processing)
        self.capture=cv2.VideoCapture(str(self.path),cv2.CAP_FFMPEG)
        if not self.capture.isOpened():
            self.capture.release()
            raise ValueError('Cannot decode cloud video: '+str(self.path))
        self.fps=float(self.capture.get(cv2.CAP_PROP_FPS))
        self.count=int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width=int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height=int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not math.isfinite(self.fps) or self.fps<=0 or min(self.count,self.width,self.height)<=0:
            self.close()
            raise ValueError('Video needs valid frame count, dimensions and frame rate')
        self.next_index=0
        self.cache=OrderedDict(); self.cache_bytes=int(cache_bytes); self.cached_bytes=0
        self.processed_frames=0; self.decoded_frames=0; self.seeks=0

    @property
    def duration(self): return self.count/self.fps

    def close(self):
        if getattr(self,'capture',None) is not None:
            self.capture.release(); self.capture=None
        if hasattr(self,'cache'): self.cache.clear(); self.cached_bytes=0

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

    def read(self,index):
        """Read an ordinal source frame. Unavailable/corrupt frames are errors."""
        if self.capture is None: raise ValueError('Video decoder is closed')
        index=int(index)
        if not 0<=index<self.count: raise ValueError('Cloud frame outside video: '+str(index))
        # Small forward skips are cheap and exact. Large/reverse jumps use the
        # codec's keyframe seek, then verify the reported ordinal position.
        if index<self.next_index or index-self.next_index>96:
            ok=self.capture.set(cv2.CAP_PROP_POS_FRAMES,index)
            pos=self.capture.get(cv2.CAP_PROP_POS_FRAMES)
            if not ok or not math.isfinite(pos) or abs(pos-index)>.25:
                self.capture.release()
                self.capture=cv2.VideoCapture(str(self.path),cv2.CAP_FFMPEG)
                self.next_index=0
            else:
                self.next_index=index
            self.seeks+=1
        while self.next_index<=index:
            if not self.capture.grab(): raise ValueError(f'Cannot decode cloud frame {self.next_index}: {self.path}')
            self.next_index+=1
        ok,bgr=self.capture.retrieve()
        if not ok or bgr is None: raise ValueError(f'Cannot retrieve cloud frame {index}: {self.path}')
        self.decoded_frames+=1
        return Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))

    def plate(self,index,size=420):
        """Return an owned RGB screen plate; repeated source frames cost no decode."""
        index=int(index)
        if not 0<=index<self.count: raise ValueError('Cloud frame outside video: '+str(index))
        key=(index,size)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key].copy()
        rgba=vis_clean.process_frame(self.read(index),self.processing,size)
        plate=vis_clean.screen_plate(rgba)
        self.processed_frames+=1
        cost=size*size*3
        if cost<=self.cache_bytes:
            while self.cache and self.cached_bytes+cost>self.cache_bytes:
                _,old=self.cache.popitem(last=False)
                self.cached_bytes-=old.width*old.height*3
            self.cache[key]=plate; self.cached_bytes+=cost
        return plate.copy()

    def overlay(self,index,size,alpha=1.):
        plate=self.plate(index,size)
        if alpha>=1: return plate.convert('RGBA')
        arr=np.rint(np.asarray(plate,dtype=np.float32)*max(0.,float(alpha))).astype(np.uint8)
        return Image.fromarray(arr).convert('RGBA')
