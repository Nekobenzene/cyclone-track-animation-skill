# -*- coding: utf-8 -*-
"""Standalone native-resolution static track previews for single storms and seasons.

python scripts/track_preview.py single <project> [--black | --plain]
python scripts/track_preview.py season <project> [--select season|all|01W 202012 ...]
python scripts/track_preview.py html <season-project>

Defaults: native EARTH density, continuous ACE heat (sigma 3 degrees, radius 15,
30-minute samples), 40% heat opacity, then opaque pure-colour paths without outlines.
All storms in a season share its peak rounded half up to 0.01; fields are independent.
Data and theme definitions are reused from the unchanged video source modules.
"""
import os
import re
import sys
import math
import argparse
import importlib.util
import csv
import json
import base64
import io
from datetime import datetime

# Shared skill runtime; each renderer remains self-contained.
_SKILL_SHARED = os.environ.get('TYPHOON_SKILL_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_DEPS = os.path.join(_SKILL_SHARED, 'runtime', 'python')
if not getattr(sys, 'frozen', False) and os.path.isdir(_SKILL_DEPS):
    sys.path.insert(0, _SKILL_DEPS)
    os.environ['PYTHONPATH'] = _SKILL_DEPS + os.pathsep + os.environ.get('PYTHONPATH', '')
os.environ['PATH'] = os.path.join(_SKILL_SHARED, 'runtime', 'bin') + os.pathsep + os.environ.get('PATH', '')
_SKILL_ASSETS = os.path.join(_SKILL_SHARED, 'assets', 'SMCY1.3')

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,_SKILL_SHARED)


# ---------------------------------------------------------------------------
# the pass 1 renderer, imported as a library
# ---------------------------------------------------------------------------
def load_pass1(path=None):
    if path is None and getattr(sys, 'frozen', False):
        from season.scripts import season_pass1
        return season_pass1
    path = path or os.path.join(_SKILL_SHARED,'season','scripts','season_pass1.py')
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


def num_rows(src):
    path = os.path.join(src, 'Num.txt')
    if not os.path.isfile(path):
        return ['', '', '', '']
    with open(path, encoding='utf-8-sig') as fh:
        rows = [line.strip() for line in fh]
    return (rows + ['', '', '', ''])[:4]


def read_num(src):
    """Read invest, JTWC number and naming time from fixed rows 1-3."""
    rows = num_rows(src)
    return rows[0], rows[1], rows[2].split('#', 1)[0].strip() or None


def select_storms(storms, tokens):
    """Match only Num.txt row 2 (JTWC) or row 4 (JMA), never folder names."""
    if not tokens or tokens == ['all']:
        return 'all', None
    if tokens == ['season']:
        return 'overview', None
    if any(token.lower() in ('all', 'season') for token in tokens):
        raise ValueError('season/all must be used alone')
    selected = []
    for token in tokens:
        code = token.upper()
        if not (re.fullmatch(r'\d{2}[A-Z]', code) or re.fullmatch(r'\d{6}', code)):
            raise ValueError('Expected JTWC number (01W / 15E) or six-digit JMA number: ' + token)
        hits = [st for st in storms if code == st['dep'].upper() or code in st.get('jma', '').split()]
        if len(hits) != 1:
            raise ValueError('%s: %s' % (token, 'no Num.txt match' if not hits else 'ambiguous Num.txt matches: ' + ', '.join(st['dir'] for st in hits)))
        if not any(st['dir'] == hits[0]['dir'] for st in selected):
            selected.append(hits[0])
    return 'selected', selected


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
                jma=num_rows(os.path.join(src, folder))[3], S=S, renderer=ps, ctx={k: ps.__dict__.get(k) for k in PS_CTX}, log=buf.getvalue())


# module globals that `_build()` writes and the trail reader needs
PS_CTX = ('S', 'KEY', 'PHASE_BOUNDS', 'RI_EVENTS', 'RI_BLEND_FRAC', '_S', '_D',
          'CFG', 'SRC', 'ROOT', 'ASSETS', 'BUILD', 'OUTDIR', 'TMP')


def bind(st):
    """Bind parser state for one storm without starting a video renderer."""
    ps = st.get('renderer') or load_pass1()
    for k, v in st['ctx'].items():
        setattr(ps, k, v)
    return ps


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


def track_style():
    from single.scripts import typhoon_anim
    return typhoon_anim


def state_color(ps, h, w, sw):
    c = np.zeros(3, dtype=np.float32)
    tot = sum(sw.values()) or 1.0
    for lvl, wt in sw.items():
        c += (wt / tot) * np.array(track_style().track_theme_col(w, lvl), dtype=np.float32)
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

    The still uses only the continuously intensity-coloured stroke, with no
    dark outline or per-fix discs. The remnant-vortex phase remains dashed.
    """
    S = ps.S
    d = ImageDraw.Draw(ov)
    w_in = max(1, int(round(6 * trail_mul * sc)))
    a_in = 255
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
        phases=[_phase_at(ps,point[0]) for point in pts]
        track_style().draw_track_segments(d,xy,cols,phases,w_in)
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
    source = bind(st)
    sc = style_scale(win, frame.width, ps)
    ov = Image.new('RGBA', frame.size, (0, 0, 0, 0))
    # Use the current season renderer's stroke constants at this output width.
    multiplier = ps.TRAIL_K * ps.ICON_PX * (frame.width / ps.REF_W) / 12.0
    trail(source, ov, float(source.S.duration_h), proj, sc, multiplier * lw / sc)
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
    ps = load_pass1()
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
# Optional ACE density preview: one exact 1 x 1 degree cell per synoptic fix.
# ---------------------------------------------------------------------------
def ace_density_colour(value, ramp):
    # The authored labels occupy equal vertical intervals, not a linear 0..8 axis.
    position = float(np.interp(value, [0, 1, 2.5, 5, 8], [0, .25, .5, .75, 1]))
    x = int(round(ramp.width * .20))
    top = int(round(ramp.height * .011))
    bottom = ramp.height - top - 1
    y = int(round(bottom - position * (bottom - top)))
    return ramp.getpixel((x, y))


def ace_segments(storms):
    tracks, segments = [], []
    for st in storms:
        series = st['S']
        tracks.append(dict(hours=series.hours.tolist(), lon=series.lon.tolist(), lat=series.lat.tolist()))
        hours = np.arange(float((-series.t0.hour)%6),series.hours[-1]+1e-6,6)
        hours = hours[hours <= series.ace_end_h+1e-6]
        for h in hours:
            row = int(np.clip(np.searchsorted(series.hours,h,side='right')-1,0,len(series.phase)-1))
            wind = float(np.interp(h,series.ihours,series.iwind))
            if series.phase[row] != 'TC' or wind < 34: continue
            first = last = row
            while first > 0 and series.phase[first-1] == 'TC': first -= 1
            while last+1 < len(series.phase) and series.phase[last+1] == 'TC': last += 1
            lo = max(0.,float(h)-3,float(series.hours[first]))
            hi = min(float(series.hours[-1]),series.ace_end_h,float(h)+3)
            if last+1 < len(series.phase): hi = min(hi,float(series.hours[last+1]))
            segments.append([len(tracks)-1,lo,hi,wind*wind/1e4,float(h)])
    return tracks, segments


def rounded_heat_max(value):
    from decimal import Decimal, ROUND_HALF_UP
    return max(.01, float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)))


def pixel_ace_field(storms, win, width=960, sigma=3., radius=15., sample_minutes=30.):
    """Continuous ACE deposition and scalar Gaussian blur, in ACE / square degree."""
    west, east, south, north = win
    height = max(1, round(width*(north-south)/(east-west)))
    dx, dy = (east-west)/width, (north-south)/height
    base = np.zeros((height,width), dtype=np.float64)
    tracks, segments = ace_segments(storms)
    visible = 0.
    for ti, lo, hi, ace, h in segments:
        tr = tracks[ti]
        n = max(1, math.ceil((hi-lo)*60/sample_minutes)) if hi > lo else 1
        times = lo+(np.arange(n)+.5)*(hi-lo)/n if hi > lo else [h]
        lons = np.interp(times,tr['hours'],tr['lon'])
        lats = np.interp(times,tr['hours'],tr['lat'])
        for lon, lat in zip(lons,lats):
            lon += math.floor(((west+east)/2-lon)/360+.5)*360
            x,y = (lon-west)/dx-.5,(north-lat)/dy-.5
            if not (-.5 <= x <= width-.5 and -.5 <= y <= height-.5): continue
            ix,iy = math.floor(x),math.floor(y)
            fx,fy = x-ix,y-iy
            points = [(iy+j,ix+i,(fx if i else 1-fx)*(fy if j else 1-fy))
                      for j in (0,1) for i in (0,1) if 0 <= ix+i < width and 0 <= iy+j < height]
            norm = sum(w for _,_,w in points)
            for yy,xx,w in points: base[yy,xx] += ace/n*w/norm
            visible += ace/n
    def blur(a,axis,spacing):
        if sigma <= 0: return a
        r = math.ceil(radius/spacing)
        offsets = np.arange(-r,r+1)
        kernel = np.exp(-offsets**2/(2*(sigma/spacing)**2))
        kernel[np.abs(offsets)>radius/spacing+.5] = 0
        kernel /= kernel.sum()
        # Explicit padding keeps output dimensions even when the kernel exceeds the field.
        return np.apply_along_axis(lambda row: np.convolve(np.pad(row,(r,r)),kernel,'valid'),axis,a)
    field = blur(blur(base,1,dx),0,dy)
    mass = float(field.sum())
    field *= visible/mass/(dx*dy) if mass else 0.
    return field, dict(actual_peak=float(field.max()), visible_source_ace=visible,
                       field_ace=float(field.sum()*dx*dy), total_ace=sum(v[3] for v in segments))


def overlay_pixel_heat(frame, field, ramp, maximum, opacity):
    # Interpolate scalar values before mapping colours, so no cell boundaries appear.
    scalar_image = Image.fromarray(field.astype('float32')).resize(frame.size,Image.Resampling.BILINEAR)
    lut = np.array([ace_density_colour(i*8/2047,ramp) for i in range(2048)],dtype=np.float32)
    # Bound intermediate memory at native map resolution; composite horizontal strips.
    for y in range(0,frame.height,128):
        bottom=min(frame.height,y+128)
        scalar=np.asarray(scalar_image.crop((0,y,frame.width,bottom)))
        index=np.clip(scalar/maximum,0,1)*2047
        lo=index.astype('int32'); hi=np.minimum(lo+1,2047)
        rgba=lut[lo]+(lut[hi]-lut[lo])*(index-lo)[...,None]
        rgba[...,3] *= opacity
        rgba[scalar <= 1e-10,3]=0
        layer=Image.fromarray(np.uint8(np.clip(np.rint(rgba),0,255)),'RGBA')
        frame.alpha_composite(layer,(0,y))
    scalar_image.close()
    # Authored colour column only: no baked labels, tick marks, panel or title.
    bar_h = round(frame.height*.37); bar_w = max(8,round(frame.width*.0125))
    x = round(ramp.width*.2); top = round(ramp.height*.011)
    bar = ramp.crop((x,top,x+1,ramp.height-top)).resize((bar_w,bar_h),Image.Resampling.BILINEAR)
    margin = round(frame.height*.04)
    frame.alpha_composite(bar,(frame.width-margin-bar_w,frame.height-margin-bar_h))


class MetadataMapSource:
    """Map geometry without decoding EARTH pixels for solid/transparent plates."""
    def __init__(self,ps,assets,basin):
        self.basin=basin
        self.world=ps._basins().get('EARTH') or basin
        self.im=self
    def close(self): pass


def preview_frame(mapsrc,win,W,H,background):
    if background=='map':
        return Image.fromarray(mapsrc.crop(*win,W,H)).convert('RGBA')
    return Image.new('RGBA',(W,H),(0,0,0,255 if background=='black' else 0))


def save_preview(frame,path,background):
    (frame if background=='transparent' else frame.convert('RGB')).save(path)


def render_heat_overviews(ps, storms, mapsrc, W, H, win, out, assets, settings,
                          products='all', only=None, labels=False, lw=.7, selected=None):
    background=settings.get('background','map')
    layers=settings.get('layers','both')
    show_heat=layers in ('both','heat')
    field=None;maximum=None;ramp=None
    report={}
    if show_heat:
        field,report=pixel_ace_field(storms,win,**settings['field'])
        maximum=rounded_heat_max(report['actual_peak'] if settings['auto_max'] else settings['legend_max'])
        with Image.open(os.path.join(assets,'gui','ace_heat.png')) as source:ramp=source.convert('RGBA')
    records = {}
    def finish(path, local_field, info, selected, local_win):
        frame=preview_frame(mapsrc,local_win,W,H,background)
        if show_heat:overlay_pixel_heat(frame,local_field,ramp,maximum,settings['opacity'])
        proj=make_proj(*local_win,W,H)
        if layers in ('both','track'):
            for st in sorted(selected,key=lambda storm:storm['S'].t0):
                draw_track(frame,st,proj,ps,local_win,lw)
                if labels: draw_label(frame,st,proj,ps)
        save_preview(frame,path,background)
        records[os.path.basename(path)] = dict(info,legend_max=maximum,background=background,layers=layers)
        print('Heat below paths -> '+path)
    if products in ('all','overview'):
        path=os.path.join(out,'overview.png')
        finish(path,field,report,storms,win)
    if products == 'selected':
        local_win=window_for(ps,mapsrc.basin,[full_track(st) for st in selected],W,H)
        local_field,info=(pixel_ace_field(selected,local_win,**settings['field']) if show_heat else (None,{}))
        codes=[st['dep'] or st.get('jma','').split()[0] for st in selected]
        path=os.path.join(out,'selected_'+'_'.join(codes)+'.png')
        finish(path,local_field,dict(info,selected=[st['dir'] for st in selected]),selected,local_win)
    del field
    if products in ('all','storms'):
        for st in storms:
            name=out_name(st)
            if only and name[:2] not in only: continue
            local_win=window_for(ps,mapsrc.basin,[full_track(st)],W,H)
            local_field,info=(pixel_ace_field([st],local_win,**settings['field']) if show_heat else (None,{}))
            path=os.path.join(out,name)
            finish(path,local_field,info,[st],local_win)
    report.update(background=background,layers=layers,legend_max=maximum,settings=settings,products=records,window=list(win),size=[W,H])
    with open(os.path.join(out,'ace_density.json'),'w',encoding='utf-8') as f: json.dump(report,f,indent=2)
    print('Preview background=%s layers=%s; shared maximum=%s; %d images' % (background,layers,maximum,len(records)))
    return report


def render_ace_html(ps, storms, mapsrc, win, out, assets, season_name,background='map',layers='both'):
    """Export one offline HTML: continuous tracks + embedded map and colour LUT."""
    tracks, segments = ace_segments(storms)
    total = sum(x[3] for x in segments)
    expected = sum(st['S'].ace_total for st in storms)
    if not math.isclose(total,expected,abs_tol=1e-7): raise ValueError('HTML ACE conservation failed')
    with Image.open(os.path.join(assets,'gui','ace_heat.png')) as im:
        ramp=im.convert('RGBA')
    lut=[list(ace_density_colour(v*8/2047,ramp)) for v in range(2048)]
    map_width=math.ceil((win[1]-win[0])*mapsrc.world['ppd']-1e-8)
    map_height=math.ceil((win[3]-win[2])*mapsrc.world['ppd']-1e-8)
    image=Image.fromarray(mapsrc.crop(*win,map_width,map_height)).convert('RGBA')
    proj=make_proj(*win,map_width,map_height)
    track_image=Image.new('RGBA',image.size)
    for st in sorted(storms,key=lambda s:s['S'].t0): draw_track(track_image,st,proj,ps,win,.7)
    track_buf=io.BytesIO();track_image.save(track_buf,format='PNG')
    image=image.convert('RGB')
    buf=io.BytesIO();image.save(buf,format='JPEG',quality=94,subsampling=0)
    payload=dict(background=background,layers=layers,season=season_name,window=list(win),total_ace=total,storm_count=len(storms),
                 tracks=tracks,segments=segments,lut=lut,native_size=[map_width,map_height],
                 track_overlay='data:image/png;base64,'+base64.b64encode(track_buf.getvalue()).decode('ascii'),
                 font='data:font/ttf;base64,'+base64.b64encode(open(ps.F_MONOB,'rb').read()).decode('ascii'),
                 map='data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode('ascii'))
    template=os.path.join(_SKILL_SHARED,'season','templates','ace_density_preview.html')
    text=open(template,encoding='utf-8').read().replace('__ACE_DATA__',json.dumps(payload,ensure_ascii=True))
    os.makedirs(out,exist_ok=True)
    target=os.path.join(out,'ace_density_preview.html')
    with open(target,'w',encoding='utf-8') as f:f.write(text)
    print('Offline pixel-level ACE preview -> '+target)
    return target


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------
def out_name(st):
    """Prefer official Num.txt numbers; fall back to unique source folder."""
    if re.fullmatch(r'\d{2}[A-Z]', st.get('dep', '')):
        return st['dep'] + '.png'
    jma = st.get('jma', '').split()
    return (jma[0] if jma else st['dir']) + '.png'


def find_defaults():
    season = '.'
    assets = _SKILL_ASSETS
    return season, assets


def render_season(argv):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', default='all',
                    choices=['all', 'overview', 'storms', 'info', 'ace-density', 'ace-html'])
    ap.add_argument('--season', default=None)
    ap.add_argument('--assets', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--crop', default='auto')
    ap.add_argument('--size', default=None, help='WxH or native; native map pixel density by default')
    ap.add_argument('--ss', type=int, default=2)
    ap.add_argument('--labels', action='store_true')
    ap.add_argument('--line', type=float, default=0.7,
                    help='track line weight as a fraction of the pass 1 season '
                         'weight (default 0.7: a still reads lighter than a '
                         'moving frame)')
    ap.add_argument('--background',choices=['map','black','transparent'],default=None)
    ap.add_argument('--layers',choices=['both','track','heat'],default=None)
    ap.add_argument('--heat', action='store_true', help='overlay independent ACE heat fields on overview products')
    ap.add_argument('--heat-parameters', help='JSON settings saved by the HTML tuner')
    ap.add_argument('--heat-field-width', type=int, default=960)
    ap.add_argument('--heat-sigma', type=float, default=3.0)
    ap.add_argument('--heat-radius', type=float, default=15.0)
    ap.add_argument('--heat-step', type=float, default=30.0, help='path samples in minutes')
    ap.add_argument('--heat-max', type=float, default=0.0, help='legend maximum; 0 uses actual peak')
    ap.add_argument('--heat-opacity', type=float, default=.4,
                    help='ACE heat opacity from 0 to 1 (default .4)')
    ap.add_argument('--select', nargs='+', help='season | all | JTWC/JMA numbers separated by spaces')
    ap.add_argument('--only', default=None, help='comma list of NN, e.g. 22')
    a = ap.parse_args(argv)
    if not (0 <= a.heat_sigma <= 10 and 0 < a.heat_radius <= 30 and 0 < a.heat_step <= 360 and a.heat_max >= 0):
        ap.error('Invalid heat sigma/radius/step/maximum')
    if not 0 <= a.heat_opacity <= 1:
        ap.error('--heat-opacity must be from 0 to 1')

    ds, da = find_defaults()
    season = os.path.abspath(a.season or ds)
    assets = os.path.abspath(os.path.join(season, a.assets or da))
    W, H = ((1920,1080) if a.size in (None,'native') else tuple(int(v) for v in a.size.lower().split('x')))
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
    try:
        product, selected = select_storms(storms, a.select) if a.select else (a.cmd, None)
    except ValueError as error:
        ap.error(str(error))
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
    mapsrc = (MapSource(ps,assets,basin,ss=a.ss) if a.background in (None,'map') or a.cmd=='ace-html'
              else MetadataMapSource(ps,assets,basin))

    if a.size in (None,'native'):
        native_win=(window_for(ps,basin,[full_track(st) for st in order],W,H)
                    if a.crop=='auto' else ps.fit_aspect(parse_window(a.crop),W,H))
        W=math.ceil((native_win[1]-native_win[0])*mapsrc.world['ppd']-1e-8)
        H=math.ceil((native_win[3]-native_win[2])*mapsrc.world['ppd']-1e-8)
        print('Native map density output: %dx%d (%.1f px/degree)' % (W,H,mapsrc.world['ppd']))

    if a.cmd == 'ace-html':
        win = (window_for(ps,basin,[full_track(st) for st in order],1920,1080)
               if a.crop == 'auto' else ps.fit_aspect(parse_window(a.crop),1920,1080))
        try:
            render_ace_html(ps,order,mapsrc,win,out,assets,os.path.basename(season),a.background or 'map',a.layers or 'both')
        finally:
            mapsrc.im.close()
        return

    if a.cmd in ('all','overview','storms','ace-density'):
        saved = {}
        if a.heat_parameters:
            with open(a.heat_parameters,encoding='utf-8') as f: saved=json.load(f)
        settings = dict(background=a.background or saved.get('background','map'),
                        layers=a.layers or saved.get('layers','both'),field=dict(width=saved.get('field_width',a.heat_field_width),
                                    sigma=saved.get('sigma',a.heat_sigma),
                                    radius=saved.get('radius',a.heat_radius),
                                    sample_minutes=saved.get('sample_minutes',a.heat_step)),
                        opacity=saved.get('opacity',a.heat_opacity),
                        auto_max=saved.get('auto_max',a.heat_max==0),
                        legend_max=saved.get('legend_max',a.heat_max))
        f=settings['field']
        if not (64 <= f['width'] <= 4096 and 0 < f['sigma'] <= 10 and 0 < f['radius'] <= 30
                and 0 < f['sample_minutes'] <= 360 and 0 <= settings['opacity'] <= 1
                and (settings['auto_max'] or settings['legend_max'] > 0)
                and settings['background'] in ('map','black','transparent')
                and settings['layers'] in ('both','track','heat')):
            ap.error('Invalid heat parameters')
        win = (window_for(ps,basin,[full_track(st) for st in order],W,H)
               if a.crop == 'auto' else ps.fit_aspect(parse_window(a.crop),W,H))
        only={x.strip().zfill(2) for x in a.only.split(',')} if a.only else None
        try:
            render_heat_overviews(ps,order,mapsrc,W,H,win,out,assets,settings,
                                  products='all' if product=='ace-density' else product,
                                  only=only,labels=a.labels,lw=a.line,selected=selected)
        finally: mapsrc.im.close()
        return

def render_single(argv):
    parser=argparse.ArgumentParser(description='Independent single-storm track preview')
    parser.add_argument('project')
    parser.add_argument('--config')
    parser.add_argument('--assets')
    parser.add_argument('--out',help='Output directory, relative to project unless absolute')
    parser.add_argument('--size',default='native')
    parser.add_argument('--background',choices=['map','black','transparent'])
    parser.add_argument('--layers',choices=['both','track','heat'])
    parser.add_argument('--black',action='store_true')
    parser.add_argument('--plain',action='store_true',help='Omit ACE heat')
    parser.add_argument('--heat-parameters',help='HTML-saved settings JSON')
    parser.add_argument('--line',type=float,default=.7)
    args=parser.parse_args(argv)
    project=os.path.abspath(args.project)
    if not os.path.isdir(os.path.join(project,'sourcedata')):
        parser.error('Expected <project>/sourcedata/')
    renderer=track_style()
    configs=([os.path.abspath(args.config)] if args.config else
             sorted(__import__('glob').glob(os.path.join(project,'build','*.yaml')))+
             sorted(__import__('glob').glob(os.path.join(project,'build','*.yml'))))
    if len(configs)>1: parser.error('Multiple configs: select --config explicitly')
    if configs:
        cfg=renderer._load_config(configs[0])
        if args.assets: cfg.setdefault('paths',{})['assets']=os.path.abspath(args.assets)
    else:
        cfg={'paths':{'storm':project,'sourcedata':'sourcedata','build':'build','output':'output',
                      'assets':os.path.abspath(args.assets or _SKILL_ASSETS)},
             'storm':{'id':os.path.basename(project),'name_en':os.path.basename(project)},'data':{}}
    renderer._apply_config(cfg);renderer._bind_paths();renderer._cfg_span();renderer._build()
    p={}
    if args.heat_parameters:
        with open(args.heat_parameters,encoding='utf-8') as f:p=json.load(f)
    background=args.background or ('black' if args.black else p.get('background','map'))
    layers=args.layers or ('track' if args.plain else p.get('layers','both'))
    return render_bound_single(renderer,background,layers,args.size,args.out,args.heat_parameters,args.line,
                               'preview_black' if background=='black' else 'preview')


def render_bound_single(renderer,background='map',layers='both',size='native',outdir=None,
                        heat_parameters=None,line=.7,stem='preview'):
    if background not in ('map','black','transparent') or layers not in ('both','track','heat'):
        raise ValueError('Invalid preview background/layers')
    project=os.path.abspath(renderer.ROOT)
    p={}
    if heat_parameters:
        with open(heat_parameters,encoding='utf-8') as f:p=json.load(f)
    st=dict(S=renderer.S,renderer=renderer,ctx={k:renderer.__dict__.get(k) for k in PS_CTX},
            dir=os.path.basename(project),en=os.path.basename(project))
    geo=load_pass1()
    geo.ASSETS=renderer.ASSETS
    W,H=(1920,1080) if size=='native' else tuple(int(v) for v in size.lower().split('x'))
    ex=geo.track_extent([{'ctx':{'S':st['S']}}])
    basin=geo.pick_basin(*ex,fit=(W,H))
    win=window_for(geo,basin,[full_track(st)],W,H)
    assets=renderer.ASSETS
    maps=MapSource(geo,assets,basin,ss=1) if background=='map' else None
    if size=='native':
        meta=geo._basins()['EARTH']
        W=math.ceil((win[1]-win[0])*meta['ppd']-1e-8)
        H=math.ceil((win[3]-win[2])*meta['ppd']-1e-8)
    out=os.path.abspath(os.path.join(project,outdir or 'output/preview'))
    os.makedirs(out,exist_ok=True)
    try:
        frame=preview_frame(maps,win,W,H,background)
        report=dict(size=[W,H],window=list(win),background=background,layers=layers,outline=False)
        if layers in ('both','heat'):
            parameters=dict(width=p.get('field_width',960),sigma=p.get('sigma',3),
                            radius=p.get('radius',15),sample_minutes=p.get('sample_minutes',30))
            if not (64<=parameters['width']<=4096 and 0<parameters['sigma']<=10
                    and 0<parameters['radius']<=30 and 0<parameters['sample_minutes']<=360
                    and 0<=p.get('opacity',.4)<=1 and
                    (p.get('auto_max',True) or p.get('legend_max',0)>0)):
                raise ValueError('Invalid preview heat parameters')
            field,info=pixel_ace_field([st],win,**parameters)
            maximum=rounded_heat_max(info['actual_peak'] if p.get('auto_max',True) else p['legend_max'])
            with Image.open(os.path.join(assets,'gui','ace_heat.png')) as image:ramp=image.convert('RGBA')
            opacity=p.get('opacity',.4)
            overlay_pixel_heat(frame,field,ramp,maximum,opacity)
            report.update(info,legend_max=maximum,opacity=opacity,parameters=parameters)
        if layers in ('both','track'):draw_track(frame,st,make_proj(*win,W,H),geo,win,line)
        path=os.path.join(out,stem+'.png')
        save_preview(frame,path,background)
        with open(os.path.join(out,stem+'.json'),'w',encoding='utf-8') as f:json.dump(report,f,indent=2)
        print('Independent preview -> '+path)
        return path
    finally:
        if maps:maps.im.close()


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        try: stream.reconfigure(encoding='utf-8',errors='replace')
        except (AttributeError,ValueError): pass
    parser=argparse.ArgumentParser(description='Standalone static track previews; no video rendering or effect extraction')
    parser.add_argument('mode',choices=['single','season','html'])
    parser.add_argument('project')
    parser.add_argument('--product',choices=['all','overview','storms'],default='all')
    parser.add_argument('--background',choices=['map','black','transparent'])
    parser.add_argument('--layers',choices=['both','track','heat'])
    parser.add_argument('--plain',action='store_true',help='Omit heat; retain native resolution and pure-colour paths')
    args,rest=parser.parse_known_args(argv)
    selection=[]
    for key in ('background','layers'):
        if getattr(args,key) is not None:selection += ['--'+key,getattr(args,key)]
    rest=selection+rest
    if args.mode=='single':
        render_single([args.project]+(['--plain'] if args.plain else [])+rest)
    elif args.mode=='html':
        render_season(['ace-html','--season',args.project]+rest)
    else:
        render_season([args.product,'--season',args.project]+(['--layers','track'] if args.plain else [])+rest)


if __name__=='__main__':
    main(sys.argv[1:])
