# -*- coding: utf-8 -*-
"""Season overview stills - the static sibling of `season_pass1.py`.

Two products, both 1920x1080 by default:

  overview.png   the whole season: one fixed basin crop (the pass 1 framing
                 rule), every storm's intensity-coloured track laid on it in
                 genesis order, so the later a storm starts the higher its
                 layer sits.
  NN W.png       one storm per file: the same styling on a crop that fits that
                 storm's own track.

There is no peak marker, no name call-out and no title banner - the map and the
tracks are the whole picture.

The map, the projection, the intensity colours and the trail weights follow
`season_pass1.py`; the trail code itself is a copy of it, so the stills cannot
drift away from the animation's look.

usage:
  python season_overview.py all
  python season_overview.py overview
  python season_overview.py storms
  python season_overview.py storms --size 3840x2160

  --season  <dir>   season folder holding sourcedata/   (default: current project directory)
  --assets  <dir>   the SMCY1.3 asset pack            (default: parent skill assets/SMCY1.3)
  --out     <dir>   where the PNGs go                 (default: <season>/output/overview)
  --crop    auto | lon0,lon1,lat0,lat1               (default auto: basin rule)
  --size    WxH     output size                       (default: 1920x1080)
  --labels          overprint each track's name (off by default)
  --ss      <n>     supersample factor for the map crop (default: 2)
"""
import os
import re
import sys
import math
import argparse
import importlib.util
from datetime import datetime

# Shared skill runtime; each renderer remains self-contained.
_SKILL_SHARED = os.environ.get('TYPHOON_SKILL_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SKILL_DEPS = os.path.join(_SKILL_SHARED, 'runtime', 'python')
if not getattr(sys, 'frozen', False) and os.path.isdir(_SKILL_DEPS):
    sys.path.insert(0, _SKILL_DEPS)
    os.environ['PYTHONPATH'] = _SKILL_DEPS + os.pathsep + os.environ.get('PYTHONPATH', '')
os.environ['PATH'] = os.path.join(_SKILL_SHARED, 'runtime', 'bin') + os.pathsep + os.environ.get('PATH', '')
_SKILL_ASSETS = os.path.join(_SKILL_SHARED, 'assets', 'SMCY1.3')

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# the pass 1 renderer, imported as a library
# ---------------------------------------------------------------------------
def load_pass1(path=None):
    if path is None and getattr(sys, 'frozen', False):
        from season.scripts import season_pass1
        return season_pass1
    path = path or os.path.join(HERE, 'season_pass1.py')
    if not os.path.isfile(path):
        raise SystemExit('season_pass1.py not found beside this script: %s' % path)
    spec = importlib.util.spec_from_file_location('season_pass1', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['season_pass1'] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# framing - the pass 1 rule
# ---------------------------------------------------------------------------
WIN_PRESET = {'world': (0.0, 360.0, -90.0, 90.0),
              'wpac': (90.0, 190.0, -10.0, 70.0)}


def parse_window(txt):
    if txt in WIN_PRESET:
        return WIN_PRESET[txt]
    v = [float(x) for x in str(txt).split(',')]
    if len(v) != 4:
        raise SystemExit('--crop wants world | wpac | lon0,lon1,lat0,lat1')
    return tuple(v)


def window_for(ps, basin, tracks, W, H):
    """the basin rule, via the renderer so both stay in one piece:

        union(basin window, track bbox grown 5 deg / 10 deg south)
        grown about its centre to the frame's aspect

    The same `basin` is passed for every still, so the whole set shares one
    sheet; only the growth to the track differs per storm.
    """
    lon0 = min(t['lon'].min() for t in tracks)
    lon1 = max(t['lon'].max() for t in tracks)
    lat0 = min(t['lat'].min() for t in tracks)
    lat1 = max(t['lat'].max() for t in tracks)
    return ps.fit_aspect(ps.basin_window(basin, lon0, lon1, lat0, lat1), W, H)


# ---------------------------------------------------------------------------
# base map - the sheet the basin rule picks, out of `map/basins/`
#
# Windows come from `season_pass1`'s basin rule, but the PIXELS always come from
# the whole-world sheet `map/basins/EARTH.png`: the window is grown to the
# picture's aspect and that growth reaches past a regional sheet's long edge, so
# cutting from the regional sheet would repeat its edge.  The basin a window was
# centred from is reported, and every still is cut from the same world sheet.
# ---------------------------------------------------------------------------
class MapSource:
    """crops windows out of the whole-world sheet, at its native resolution"""

    def __init__(self, ps, assets, basin, ss=2):
        self.ss = max(1, int(ss))
        self.basin = basin                       # the pick, kept for reporting
        self.world = ps._basins().get('EARTH') or basin
        p = self.world['file']
        if not os.path.isfile(p):
            raise SystemExit('map not found: %s' % p)
        # a known asset, not an untrusted download: the world sheet at
        # 21600x10800 is past PIL's 178.9 Mpx decompression-bomb limit
        Image.MAX_IMAGE_PIXELS = None
        self.im = Image.open(p).convert('RGB')
        self.native = self.im.size
        self._cache = {}
        print('  sheet %s  %dx%d  %.1f px/deg   (basin rule -> %s)'
              % (os.path.basename(p), self.native[0], self.native[1],
                 self.world['ppd'], basin['name']))

    def _crop_layer(self, lon0, lon1, lat0, lat1, W, H, allow_up):
        """the window, returned exactly WxH.

        The integer floor/ceil box around the window is cropped at the sheet's
        own resolution; PIL's float `box` then takes the sub-pixel edges; one
        final LANCZOS step lands on the exact frame size.  `allow_up` lets a wide
        overview supersample, while a narrow crop - which already has more source
        pixels than it needs - never upsamples.
        """
        key = (round(lon0, 4), round(lon1, 4), round(lat0, 4),
               round(lat1, 4), W, H, allow_up)
        if key in self._cache:
            return self._cache[key]
        b = self.world
        im = self.im
        nw, nh = im.size
        ppd = b['ppd']
        fx0, fx1 = (lon0 - b['lon0']) * ppd, (lon1 - b['lon0']) * ppd
        fy0, fy1 = (b['lat1'] - lat1) * ppd, (b['lat1'] - lat0) * ppd
        if fx0 < 0.0 or fx1 > nw or fy0 < 0.0 or fy1 > nh:
            print('  ! window lon %.1f..%.1f lat %.1f..%.1f leaves the world sheet'
                  % (lon0, lon1, lat0, lat1))
        fx0 = max(0.0, min(nw - 1.0, fx0)); fx1 = max(1.0, min(float(nw), fx1))
        fy0 = max(0.0, min(nh - 1.0, fy0)); fy1 = max(1.0, min(float(nh), fy1))
        ix0, ix1 = int(math.floor(fx0)), int(math.ceil(fx1))
        iy0, iy1 = int(math.floor(fy0)), int(math.ceil(fy1))
        ix0 = max(0, min(nw - 2, ix0)); ix1 = min(nw, max(ix0 + 1, ix1))
        iy0 = max(0, min(nh - 2, iy0)); iy1 = min(nh, max(iy0 + 1, iy1))
        cw, ch = ix1 - ix0, iy1 - iy0
        sub = (fx0 - ix0, fy0 - iy0, fx1 - ix0, fy1 - iy0)
        scale = 1
        if allow_up > 1:
            scale = max(1, min(int(allow_up), int(math.ceil(W / float(cw)))))
        crop = im.crop((ix0, iy0, ix1, iy1))
        if scale > 1:
            crop = crop.resize((cw * scale, ch * scale), Image.BICUBIC)
        out = crop.resize((W, H), Image.LANCZOS,
                          box=tuple(v * scale for v in sub)).convert('RGB')
        if out.size != (W, H):
            out = out.resize((W, H), Image.LANCZOS)
        self._cache[key] = out
        return out

    def crop(self, lon0, lon1, lat0, lat1, W, H, basin=None):
        """RGB array (H,W,3) of the world sheet over the window"""
        return np.asarray(self._crop_layer(lon0, lon1, lat0, lat1,
                                           int(W), int(H), self.ss), dtype=np.uint8)


def make_proj(lon0, lon1, lat0, lat1, W, H):
    def proj(lon, lat):
        return ((lon - lon0) / (lon1 - lon0) * W,
                (lat1 - lat) / (lat1 - lat0) * H)
    return proj


# ---------------------------------------------------------------------------
# Num.txt: find the naming stamp by its SHAPE, not its line number
# ---------------------------------------------------------------------------
_SHORT = re.compile(r'^(?:\d{14}|\d{12})$')
_LONG = re.compile(r'^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$')


def read_num(src):
    """(invest, depression, naming_stamp or None)

    The JMA column that used to sit third is gone, so the stamp is the only
    14-digit (or legacy 12-digit) timestamp in the file.  Locating it by shape means this keeps working
    for a 3-line file and for the older 4-line one.
    """
    p = os.path.join(src, 'Num.txt')
    if not os.path.isfile(p):
        return '', '', None
    vals = [l.strip() for l in open(p, encoding='utf-8')]
    vals = [v for v in vals if v]
    stamp = None
    for v in vals:
        if _SHORT.match(v) or _LONG.match(v):
            stamp = v
    codes = [v for v in vals if v != stamp]
    return (codes[0] if len(codes) > 0 else '',
            codes[1] if len(codes) > 1 else '',
            stamp)


# ---------------------------------------------------------------------------
# storms
# ---------------------------------------------------------------------------
SEG_ORDER = ['DB', 'TC', 'RV', 'EX']


def storm_dirs(season):
    src = os.path.join(season, 'sourcedata')
    if not os.path.isdir(src):
        raise SystemExit('no sourcedata/ under %s' % season)
    return src, sorted(d for d in os.listdir(src)
                       if os.path.isdir(os.path.join(src, d)))


def load_storm(ps, season, assets, cache, folder):
    """run the real `_build()` for one storm and keep its `S`"""
    src = os.path.join(season, 'sourcedata')
    ps._apply_config({'paths': {'storm': season,
                                'sourcedata': os.path.join('sourcedata', folder),
                                'assets': assets, 'build': 'build',
                                'cache': cache, 'tag': 'overview'},
                      'storm': {'id': folder}, 'data': {}})
    ps._bind_paths()
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ps._build()
    S = ps.S
    inv, dep, stamp = read_num(os.path.join(src, folder))
    t0 = S.t0
    if stamp:
        try:
            named = ps.parse_fix_time(stamp)
        except Exception:
            named = None
    else:
        named = None
    # if the stamp is earlier than the first fix the data is odd: ignore it
    if named is not None and named < t0:
        named = None
    en = folder.split('_', 1)[1] if '_' in folder else folder
    return dict(dir=folder, en=en.upper(), inv=inv, dep=dep, named=named,
                S=S, ctx={k: ps.__dict__.get(k) for k in PS_CTX}, log=buf.getvalue())


# module globals that `_build()` writes and the trail reader needs
PS_CTX = ('S', 'KEY', 'PHASE_BOUNDS', 'RI_EVENTS', 'RI_BLEND_FRAC', '_S', '_D',
          'CFG', 'SRC', 'ROOT', 'ASSETS', 'BUILD', 'OUTDIR', 'TMP')


def bind(st):
    """make the imported renderer talk about this storm"""
    import season_pass1 as ps
    for k, v in st['ctx'].items():
        setattr(ps, k, v)


def full_track(st):
    """the storm's own fixes, for framing"""
    S = st['S']
    return dict(lon=S.lon, lat=S.lat)


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# the track style, copied out of `season_pass1.py`
#
# This is a deliberate copy, not a call: the stills must not be able to take
# pass 1 down with them, and the one thing they need to differ on - no fix
# markers - is exactly what pass 1 must keep.  Everything below is the pass 1
# code verbatim except for the omission of its `r_dot` block at the end of
# `trail()`; the two must be kept in step by hand.
# ---------------------------------------------------------------------------
BANDS = [('TD', 0, 33), ('TS', 34, 63), ('C1', 64, 82), ('C2', 83, 95),
         ('C3', 96, 112), ('C4', 113, 136), ('C5', 137, 155),
         ('C5+', 156, 169), ('C5++', 170, 999)]
TRANS_K = 3.5
ICON_BLEND_KT = 14.0
TRANS_H = 2.5

COL = {'DB': (206, 220, 236), 'TD': (196, 220, 255), 'TS': (58, 226, 92),
       'C1': (255, 232, 40), 'C2': (255, 158, 30), 'C3': (244, 86, 32),
       'C4': (232, 34, 28), 'C5': (255, 60, 226), 'C5+': (214, 106, 255),
       'RV': (176, 192, 214), 'EX': (152, 172, 214)}
COL.update({'WV': COL['DB'], 'MD': COL['TD'], 'SD': COL['TD'], 'SS': COL['TS']})

C5PP_A = np.array([126, 44, 176], dtype=np.float32)
C5PP_B = np.array([40, 74, 178], dtype=np.float32)
C6_END = np.array([198, 232, 255], dtype=np.float32)



HIGHWIND_BODY = [(200, (198,232,255)), (220, (192,255,244)),
                 (240, (223,255,154)), (260, (255,230,186)),
                 (280, (255,208,229)), (300, (241,221,255)),
                 (350, (234,223,255)), (400, (228,237,255)),
                 (450, (233,250,255)), (500, (244,246,255))]
HIGHWIND_HALO = [(200, (198,232,255)), (220, (192,255,244)),
                 (240, (223,255,154)), (260, (255,209,110)),
                 (280, (255,150,210)), (300, (183,108,255)),
                 (350, (113,96,255)), (400, (54,223,255)),
                 (450, (100,255,199)), (500, (216,255,82))]


def palette_colour(wind, nodes):
    return tuple(int(round(np.interp(wind, [p[0] for p in nodes],
                                     [p[1][c] for p in nodes]))) for c in range(3))


def highwind_halo_colour(wind):
    return palette_colour(wind, HIGHWIND_HALO)


def theme_col(wind, lvl):
    """155 kt+ uses the super-cyclone ramp: pink-purple -> deep blue at 185 kt
    -> ACE fill endpoint (#C6E8FF) at 200 kt, linear in between"""
    if lvl == 'C5++':
        if wind > 200.0:
            return palette_colour(wind, HIGHWIND_BODY)
        if wind <= 185.0:
            t = min(1.0, max(0.0, (wind - 170.0) / 15.0))
            return tuple(int(v) for v in (C5PP_A * (1 - t) + C5PP_B * t))
        t = min(1.0, (wind - 185.0) / 15.0)
        return tuple(int(v) for v in (C5PP_B * (1 - t) + C6_END * t))
    return COL.get(lvl, (220, 220, 220))


def intensity_weights(w):
    out = {}
    for lvl, lo, hi in BANDS:
        d = max(0.0, lo - w, w - hi)
        a = math.exp(-(d / ICON_BLEND_KT) ** 2)
        if a > 0.004:
            out[lvl] = a
    tot = sum(out.values())
    if tot <= 0.0:
        return {BANDS[-1][0]: 1.0}
    return {k: v / tot for k, v in out.items()}


def _phase_side(ph, w):
    if ph in ('SD', 'SS'):
        ph = 'SD' if w < 34 else 'SS'
    return intensity_weights(w) if ph == 'TC' else {ph: 1.0}


def state_weights(ps, h, w):
    for hb, pa, pb in ps.PHASE_BOUNDS:
        if abs(h - hb) <= TRANS_H:
            t = (h - (hb - TRANS_H)) / (2.0 * TRANS_H)
            out = {}
            for k, v in _phase_side(pa, w).items():
                out[k] = out.get(k, 0.0) + v * (1.0 - t)
            for k, v in _phase_side(pb, w).items():
                out[k] = out.get(k, 0.0) + v * t
            return out
    ph = _phase_at(ps, h)
    base = _phase_side(ph, w)
    for h0, h1, _l0, _l1, _fx in ps.RI_EVENTS:
        if h0 <= h <= h1 and h1 > h0:
            e = 1.0 / max(1e-6, ps.RI_BLEND_FRAC)
            out = {k: (v ** e) for k, v in base.items()}
            tot = sum(out.values()) or 1.0
            return {k: v / tot for k, v in out.items()}
    return base


def _phase_at(ps, h):
    ph = ps.PHASE_BOUNDS[0][1] if ps.PHASE_BOUNDS else ps.S.phase[0]
    for hb, pa, pb in ps.PHASE_BOUNDS:
        if h >= hb:
            ph = pb
    return ph


def state_color(ps, h, w, sw):
    c = np.zeros(3, dtype=np.float32)
    tot = sum(sw.values()) or 1.0
    for lvl, wt in sw.items():
        c += (wt / tot) * np.array(theme_col(w, lvl), dtype=np.float32)
    return tuple(int(v) for v in np.clip(c, 0, 255))


def sample(ps, h):
    """the pass 1 sampler, bound to the storm currently installed in `ps`"""
    S = ps.S
    h = float(max(0.0, min(S.duration_h, h)))
    i = int(np.searchsorted(S.hours, h, 'right')) - 1
    i = max(0, min(len(S.hours) - 2, i)) if len(S.hours) > 1 else 0
    span = float(S.hours[i + 1] - S.hours[i]) if len(S.hours) > 1 else 1.0
    s = 0.0 if span <= 0 else (h - S.hours[i]) / span

    def cr(arr):
        p1 = arr[i]; p0 = arr[max(0, i - 1)]
        p2 = arr[min(len(arr) - 1, i + 1)]; p3 = arr[min(len(arr) - 1, i + 2)]
        return 0.5 * ((2 * p1) + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s * s
                      + (-p0 + 3 * p1 - 3 * p2 + p3) * s * s * s)

    lon = cr(S.lon); lat = cr(S.lat)
    wind = float(S.WF(h))
    pres = float(S.PF(h))
    ace = float(np.interp(h, S.hours, S.ace))
    ph = S.phase[min(len(S.phase) - 1, int(np.searchsorted(S.hours, h, 'right')) - 1)]
    return lon, lat, wind, pres, ace, ph


def _dashed(d, pts, fill, width, dash=16, gap=11):
    on, acc = True, 0.0
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]; x1, y1 = pts[i]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg <= 0.01:
            continue
        t = 0.0
        while t < seg - 0.01:
            want = dash if on else gap
            step = min(want - acc, seg - t)
            if on and step > 0.5:
                xa = x0 + (x1 - x0) * (t / seg); ya = y0 + (y1 - y0) * (t / seg)
                xb = x0 + (x1 - x0) * ((t + step) / seg); yb = y0 + (y1 - y0) * ((t + step) / seg)
                d.line([xa, ya, xb, yb], fill=fill, width=width)
            t += step; acc += step
            if acc >= want - 1e-6:
                on = not on; acc = 0.0


def trail(ps, ov, hours, proj, sc, trail_mul):
    """pass 1's `trail()` with the fix markers left out.

    The trail itself is identical: dark outer stroke, intensity-coloured inner
    stroke whose colour is sampled continuously, and the remnant-vortex phase
    dashed.  Only the per-fix black discs are gone.
    """
    S = ps.S
    d = ImageDraw.Draw(ov)
    w_out = max(1, int(round(12 * trail_mul * sc)))
    w_in = max(1, int(round(6 * trail_mul * sc)))
    a_out, a_in = 120, 255
    pts = []
    h = 0.0
    while h < hours - 1e-6:
        h = min(hours, h + 0.8)
        lo, la, w, p, a, ph = sample(ps, h)
        pts.append((h, lo, la))
    lo, la, w, p, a, ph = sample(ps, hours)
    pts.append((hours, lo, la))
    cols = []
    for (hh, _, _) in pts:
        _, _, ww, _, _, _ = sample(ps, hh)
        cols.append(state_color(ps, hh, ww, state_weights(ps, hh, ww)))
    xy = [proj(p[1], p[2]) for p in pts]
    if len(xy) > 1:
        def is_rv(i):
            return _phase_at(ps, pts[i][0]) == 'RV'
        runs = []
        cur = [0]
        for i in range(1, len(pts)):
            if is_rv(i) != is_rv(i - 1):
                runs.append((is_rv(i - 1), cur + [i]))
                cur = [i - 1]
            cur.append(i)
        runs.append((is_rv(len(pts) - 1), cur))
        for rv, idx in runs:
            if len(idx) < 2:
                continue
            rp = [xy[k] for k in idx]
            if rv:
                _dashed(d, rp, (0, 0, 0, 110), w_out)
                _dashed(d, rp, cols[idx[-1]] + (a_in,), w_in)
            else:
                d.line(rp, fill=(0, 0, 0, a_out), width=w_out, joint='curve')
                for a, b in zip(idx[:-1], idx[1:]):
                    d.line([xy[a], xy[b]], fill=cols[b] + (a_in,), width=w_in)
    # <- pass 1 draws its fix markers here; the stills deliberately do not.


def style_scale(win, W, ps):
    """the renderer's own line-weight rule:
           SC = (px per degree) / (1920 / SPAN0_LON)
    A follow camera draws 1920 px over 22.8 deg; a season still draws W px over
    the whole crop, so its line is thinner by exactly that ratio."""
    ppd = W / float(win[1] - win[0])
    return ppd / ps.STYLE_PPD


def draw_track(frame, st, proj, ps, win, lw=1.0):
    """one storm's trail, in the pass 1 style at the frame's own map scale.

    `lw` is the still-only weight trim: pass 1's season line is sized for a
    moving 1080p frame, and on a static sheet it reads a touch heavy.
    """
    bind(st)
    sc = style_scale(win, frame.width, ps)
    ov = Image.new('RGBA', frame.size, (0, 0, 0, 0))
    trail(ps, ov, float(ps.S.duration_h), proj, sc, ps.SE_TRAIL_MUL * lw)
    frame.alpha_composite(ov)


def draw_label(frame, st, proj, ps, colour=(255, 240, 210)):
    S = st['S']
    i = int(np.argmax(S.iwind))
    h = float(S.ihours[i])
    lo = float(np.interp(h, S.hours, S.lon))
    la = float(np.interp(h, S.hours, S.lat))
    x, y = proj(lo, la)
    d = ImageDraw.Draw(frame, 'RGBA')
    f = ps.font(ps.F_MONOB, 22)
    txt = st['en']
    for dx, dy, col in ((2, 2, (0, 0, 0, 170)), (0, 0, colour + (235,))):
        d.text((x + 14 + dx, y - 10 + dy), txt, font=f, fill=col)


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------
def render_overview(storms, mapsrc, W, H, win, out, labels=False, lw=1.0, log=print):
    lon0, lon1, lat0, lat1 = win
    log('overview  lon %.2f..%.2f  lat %.2f..%.2f  (%dx%d)  line x%.2f'
        % (lon0, lon1, lat0, lat1, W, H, lw))
    arr = mapsrc.crop(lon0, lon1, lat0, lat1, W, H)
    frame = Image.fromarray(arr, 'RGB').convert('RGBA')
    proj = make_proj(lon0, lon1, lat0, lat1, W, H)
    import season_pass1 as ps
    # genesis order: the later a storm starts, the higher its layer sits
    order = sorted(storms, key=lambda s: s['S'].t0)
    for k, st in enumerate(order, 1):
        draw_track(frame, st, proj, ps, (lon0, lon1, lat0, lat1), lw)
        log('  %2d/%d  %-16s genesis %s  %3d fixes  layer %d'
            % (k, len(order), st['en'], st['S'].t0.strftime('%Y-%m-%d %HZ'),
               len(st['S'].hours), k))
        if labels:
            draw_label(frame, st, proj, ps)
    frame.convert('RGB').save(out)
    log('-> %s' % out)


def render_storm(ps, st, mapsrc, W, H, out, labels=False, lw=1.0, log=print):
    """one storm's still, framed inside the season's own sheet

    The basin is decided ONCE for the whole season, not per storm, so every
    still belongs to the same map - only the window is grown from this storm's
    own track, and for a storm well inside the basin that lands on the basin's
    own rectangle, i.e. the same picture as the overview.
    """
    lon0, lon1, lat0, lat1 = window_for(ps, mapsrc.basin, [full_track(st)], W, H)
    arr = mapsrc.crop(lon0, lon1, lat0, lat1, W, H)
    frame = Image.fromarray(arr, 'RGB').convert('RGBA')
    proj = make_proj(lon0, lon1, lat0, lat1, W, H)
    draw_track(frame, st, proj, ps, (lon0, lon1, lat0, lat1), lw)
    if labels:
        draw_label(frame, st, proj, ps)
    frame.convert('RGB').save(out)
    log('  %-16s lon %.1f..%.1f lat %.1f..%.1f  ->  %s'
        % (st['en'], lon0, lon1, lat0, lat1, os.path.basename(out)))


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------
def out_name(st):
    """01W.png .. 26W.png, from the JTWC number"""
    n = st['dep'] or ''
    m = re.match(r'^(\d{2})W$', n)
    if m:
        return '%sW.png' % m.group(1)
    m = re.match(r'^(\d{2})', st['dir'][2:])
    return '%sW.png' % (m.group(1) if m else st['dir'])


def find_defaults():
    season = '.'
    assets = _SKILL_ASSETS
    return season, assets


def main(argv):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', default='all',
                    choices=['all', 'overview', 'storms', 'info'])
    ap.add_argument('--season', default=None)
    ap.add_argument('--assets', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--crop', default='auto')
    ap.add_argument('--size', default='1920x1080')
    ap.add_argument('--ss', type=int, default=2)
    ap.add_argument('--labels', action='store_true')
    ap.add_argument('--line', type=float, default=0.7,
                    help='track line weight as a fraction of the pass 1 season '
                         'weight (default 0.7: a still reads lighter than a '
                         'moving frame)')
    ap.add_argument('--only', default=None, help='comma list of NN, e.g. 22')
    a = ap.parse_args(argv)

    ds, da = find_defaults()
    season = os.path.abspath(a.season or ds)
    assets = os.path.abspath(os.path.join(season, a.assets or da))
    W, H = (int(v) for v in a.size.lower().split('x'))
    out = os.path.abspath(os.path.join(season, a.out)) if a.out else os.path.join(season, 'output', 'overview')
    os.makedirs(out, exist_ok=True)

    ps = load_pass1()
    ps.REAL_STDOUT = sys.stdout
    src, folders = storm_dirs(season)
    log = print

    log('season %s' % season)
    log('assets %s' % assets)
    # a shared cache beside the pack, exactly as pass 1 does it
    cache = os.path.join(os.path.dirname(os.path.abspath(assets)), '_cache')

    storms = []
    for f in folders:
        try:
            storms.append(load_storm(ps, season, assets, cache, f))
        except SystemExit as e:
            log('  skip %-16s %s' % (f, e))
    if not storms:
        raise SystemExit('no storm could be loaded')
    order = sorted(storms, key=lambda s: s['S'].t0)
    log('%d storms, %d fixes, %s .. %s'
        % (len(order), sum(len(s['S'].hours) for s in order),
           order[0]['S'].t0.strftime('%Y-%m-%d'),
           order[-1]['S'].t0.strftime('%Y-%m-%d')))

    if a.cmd == 'info':
        for s in order:
            log('  %-16s %-6s inv %-4s dep %-4s named %s  %s'
                % (s['dir'], s['en'], s['inv'] or '-', s['dep'] or '-',
                   s['named'].strftime('%Y-%m-%d %HZ') if s['named'] else '-',
                   s['S'].t0.strftime('%Y-%m-%d %HZ')))
        return

    # one sheet for the whole run: the basin rule applied to every storm at once
    ex = ps.track_extent([{'ctx': {'S': s['S']}} for s in order])
    basin = ps.pick_basin(ex[0], ex[1], ex[2], ex[3], fit=(W, H))
    mapsrc = MapSource(ps, assets, basin, ss=a.ss)

    if a.cmd in ('all', 'overview'):
        if a.crop == 'auto':
            win = window_for(ps, basin, [full_track(s) for s in order], W, H)
        else:
            win = ps.fit_aspect(parse_window(a.crop), W, H)
        render_overview(order, mapsrc, W, H, win, os.path.join(out, 'overview.png'),
                        labels=a.labels, lw=a.line, log=log)

    if a.cmd in ('all', 'storms'):
        only = None
        if a.only:
            only = {x.strip().zfill(2) for x in a.only.split(',')}
        for s in order:
            nm = out_name(s)
            if only and nm[:2] not in only:
                continue
            render_storm(ps, s, mapsrc, W, H, os.path.join(out, nm),
                         labels=a.labels, lw=a.line, log=log)


if __name__ == '__main__':
    main(sys.argv[1:])
