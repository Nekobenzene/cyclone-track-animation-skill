# -*- coding: utf-8 -*-
"""
Typhoon track animation renderer - SMCY1.3 style.

Renders a broadcast-style typhoon track animation from
  * best-track / post-analysis text files,
  * an optional Himawari-8 infrared loop,
  * the SMCY1.3 asset pack (map sources, glowing TC icons, landfall fx, sfx).

The visual style (layout, fonts, colours, timings, panel geometry) is FROZEN -
see references/storm-style-spec.md. Only the storm-specific values come from a config
file; everything else is shared so every storm looks identical.

usage:  python typhoon_anim.py --config storm.yaml preview|assets|test|render|audio|mux|poster|info|all
"""
import os, re, sys, math, wave, subprocess, json, shutil
from datetime import datetime, timedelta
from functools import lru_cache
from collections import OrderedDict

# Shared skill runtime; each renderer remains self-contained.
_SKILL_SHARED = os.environ.get('TYPHOON_SKILL_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SKILL_DEPS = os.path.join(_SKILL_SHARED, 'runtime', 'python')
if not getattr(sys, 'frozen', False) and os.path.isdir(_SKILL_DEPS):
    sys.path.insert(0, _SKILL_DEPS)
    os.environ['PYTHONPATH'] = _SKILL_DEPS + os.pathsep + os.environ.get('PYTHONPATH', '')
os.environ['PATH'] = os.path.join(_SKILL_SHARED, 'runtime', 'bin') + os.pathsep + os.environ.get('PATH', '')
_SKILL_ASSETS = os.path.join(_SKILL_SHARED, 'assets', 'SMCY1.3')

import numpy as np
try:
    import cv2
except ModuleNotFoundError:
    cv2 = None  # Still previews need only NumPy and Pillow.
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter

# ----------------------------------------------------------------------------
# configuration (storm specific; everything below the STYLE section is frozen)
# ----------------------------------------------------------------------------
CFG, _S, _D = {}, {}, {}
_CONFIG_DIR = None

class _FileConfig(dict):
    """Config mapping retaining its file origin without adding YAML keys."""
    def __init__(self, values, directory):
        super().__init__(values or {})
        self.directory = directory

def _load_config(path):
    path = os.path.abspath(path)
    txt = open(path, encoding='utf-8').read()
    directory = os.path.dirname(path)
    try:
        import yaml
        return _FileConfig(yaml.safe_load(txt), directory)
    except ImportError:
        pass
    try:                                    # JSON is a YAML subset
        return _FileConfig(json.loads(txt), directory)
    except Exception:
        raise SystemExit('PyYAML required for YAML configs (pip install pyyaml), '
                         'or supply a .json config')

def _c(path, default=None):
    cur = CFG
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur

def _apply_config(cfg):
    global CFG, _S, _D, _CONFIG_DIR
    _CONFIG_DIR = getattr(cfg, 'directory', None)
    CFG = cfg or {}
    _S = CFG.get('storm', {})
    _D = CFG.get('data', {})

# ----------------------------------------------------------------------------
# paths (bound from the config)
#
# workspace layout - one folder per storm, shared resources under res/:
#   <root>/res/SMCY1.3/                 asset pack
#   <root>/single/<Storm>/sourcedata/      track txt files + satellite loop + damage notes
#   <root>/single/<Storm>/build/           config, intermediates, historical scripts
#   <root>/single/<Storm>/output/          finished MP4 + poster
#   <root>/single/<Storm>/旧版（无用）/      superseded cuts
# ----------------------------------------------------------------------------
ROOT = SRC = ASSETS = BUILD = OUTDIR = TMP = ICOND = CLOUDD = FXD = '.'
OUTMP4 = POSTER = RAWM = WAV = ''

def _bind_paths():
    global ROOT, SRC, ASSETS, BUILD, OUTDIR
    global TMP, ICOND, CLOUDD, FXD, OUTMP4, POSTER, RAWM, WAV, CACHE
    # the storm folder itself (paths.storm, or the legacy paths.workdir)
    config_dir = _CONFIG_DIR or os.getcwd()
    ROOT = os.path.abspath(os.path.join(config_dir,
        _c('paths.storm', _c('paths.workdir', '.'))))
    # inputs: default "<storm>/sourcedata", fall back to the storm folder itself
    SRC = os.path.abspath(os.path.join(ROOT, _c('paths.sourcedata', 'sourcedata')))
    if not os.path.isdir(SRC):
        SRC = ROOT
    # Set paths.assets to <work>/res/SMCY1.3; sibling default is legacy.
    ASSETS = os.path.abspath(os.path.join(config_dir, _c('paths.assets',
                                os.path.join(os.path.dirname(ROOT), 'SMCY1.3'))))
    BUILD = os.path.abspath(os.path.join(ROOT, _c('paths.build', 'build')))
    OUTDIR = os.path.abspath(os.path.join(ROOT, _c('paths.output', 'output')))
    tag = str(_c('paths.tag', 'anim'))
    TMP = os.path.join(BUILD, 'tmp')
    # item 11: the extracted library art is shared, not per storm, so N storms
    # cost one copy instead of N.  It sits BESIDE the asset pack, not inside it:
    # `SMCY1.3` is the read-only source of truth and must not accumulate 0.5 GB
    # of derived frames.  `paths.cache` overrides.
    CACHE = os.path.abspath(os.path.join(config_dir, _c('paths.cache',
                               os.path.join(os.path.dirname(ASSETS), '_cache'))))
    ICOND = os.path.join(CACHE, 'icons')
    CLOUDD = os.path.join(BUILD, 'cloud')          # a storm's own cloud frames
    FXD = os.path.join(CACHE, 'fx')
    OUTMP4 = os.path.join(OUTDIR, _c('output.mp4', 'typhoon_track_animation.mp4'))
    POSTER = os.path.join(OUTDIR, _c('output.poster', 'typhoon_poster.png'))
    RAWM = os.path.join(BUILD, 'video_silent.mp4')
    WAV = os.path.join(BUILD, 'audio.wav')
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    _ensure_cache_dirs()

def _ensure_cache_dirs():
    """Derived media is disposable: a fresh install must create its own roots."""
    for path in (CACHE, ICOND, FXD):
        os.makedirs(path, exist_ok=True)

def _auto_panorama():
    """Fit the whole track between the cards and below the summary banner."""
    global SPAN1_LON, PANO_C
    if str(_c('view.panorama', '')).lower() != 'auto':
        return
    lo0, lo1 = float(S.lon.min()), float(S.lon.max())
    la0, la1 = float(S.lat.min()), float(S.lat.max())
    # Keep the complete path in the clear rectangle between both card columns
    # and below the summary banner. Extra padding covers stroke/marker extents.
    left = CARD_X_L + CARD_W + 40.0
    right = W - CARD_M - CARD_W - 40.0
    top, bottom = 235.0 + 40.0, H - 48.0
    SPAN1_LON = max((lo1 - lo0) * W / (right - left),
                    (la1 - la0) * W / (bottom - top), 22.8)
    span_lat = SPAN1_LON * H / W
    cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
    PANO_C = ((lo0 + lo1) / 2.0 - (cx / W - 0.5) * SPAN1_LON,
              (la0 + la1) / 2.0 + (cy / H - 0.5) * span_lat)
    print('  panorama auto: span %.1f x %.1f deg  centre (%.1f, %.1f)' %
          (SPAN1_LON, span_lat, PANO_C[0], PANO_C[1]))
    for label, p in (('asset pack', ASSETS), ('source data', SRC)):
        if not os.path.isdir(p):
            raise SystemExit('%s not found: %s' % (label, p))

WIND_AXIS = 185.0          # graph y-axis top, auto-extended past 185 kt
ACE_MAX = 40.0             # ACE bar full scale, auto-extended for big seasons

def _cfg_span():
    """panorama framing: explicit centre+span, or 'auto' to fit the whole track
    below the summary banner (which occupies the top 235 px of the frame)"""
    global SPAN0_LON, SPAN1_LON, PANO_C
    SPAN0_LON = float(_c('view.tracking_span_lon', SPAN0_LON))
    SPAN1_LON = float(_c('view.panorama_span_lon', SPAN1_LON))
    p = _c('view.panorama_center')
    if p:
        PANO_C = (float(p[0]), float(p[1]))

# ----------------------------------------------------------------------------
# video / camera  (frozen style)
# ----------------------------------------------------------------------------
W, H, FPS = 1920, 1080, 120  # authored layout; frames evaluated at 120 fps
OUTPUT_W, OUTPUT_H = 1920, 1080
SPAN0_LON = 22.8                            # tracking view
SPAN1_LON = 52.0                            # pulled-back panorama
PANO_C = (130.9, 25.6)                      # panorama centre (lon, lat)
INTRO, MAIN = 5.0, 46.0
# Reserved end-card slot: zero duration until a new design is implemented.
PULL, HOLD, SUMMARY = 2.0, 2.0, 0.0
T_MAIN = INTRO + MAIN
T_PULL = T_MAIN + PULL
# rule 7: a card column holds CARD_CYCLE seconds and they run until every card
# has been shown, so the panorama stretches to fit the busiest side.  A fixed
# 2 s hold could only ever show the first column.
NTIME = {'hold': HOLD}
T_SUM = T_PULL + HOLD
TOTAL = T_SUM + SUMMARY
NFRAMES = int(round(TOTAL * FPS))

def cards_per_column():
    """how many info cards fit one panorama column"""
    return max(1, int((H - 250 - 40) // (100 + 10)))

def set_hold(seconds):
    """re-time the ending once the card counts are known"""
    global HOLD, T_SUM, TOTAL, NFRAMES
    HOLD = max(HOLD, float(seconds))
    NTIME['hold'] = HOLD
    T_SUM = T_PULL + HOLD
    TOTAL = T_SUM + SUMMARY
    NFRAMES = int(round(TOTAL * FPS))
    globals()['HOLD'] = HOLD

F_SAIRA = os.path.join(_SKILL_ASSETS, 'font', '_saira_master', 'Saira', 'fonts', 'ttf')
F_MONO, F_MONOB = os.path.join(F_SAIRA, 'Saira-Regular.ttf'), os.path.join(F_SAIRA, 'Saira-Bold.ttf')
F_SOURCE_HAN = os.path.join(_SKILL_ASSETS, 'font', 'SourceHanSansSC')
F_CJK = os.path.join(F_SOURCE_HAN, 'SourceHanSansSC-Regular.otf')
F_CJKM = os.path.join(F_SOURCE_HAN, 'SourceHanSansSC-Medium.otf')
F_CJKB = os.path.join(F_SOURCE_HAN, 'SourceHanSansSC-Bold.otf')
F_UI, F_UIB = os.path.join(F_SAIRA, 'Saira-SemiBold.ttf'), os.path.join(F_SAIRA, 'Saira-Bold.ttf')

# ----------------------------------------------------------------------------
# levels / colours
# ----------------------------------------------------------------------------
COL = {'DB': (206, 220, 236), 'TD': (196, 220, 255), 'TS': (58, 226, 92),
       'C1': (255, 232, 40), 'C2': (255, 158, 30), 'C3': (244, 86, 32),
       'C4': (232, 34, 28), 'C5': (255, 60, 226), 'C5+': (214, 106, 255),
       'RV': (176, 192, 214), 'EX': (152, 172, 214)}
C5PP_A = np.array([126, 44, 176], dtype=np.float32)   # deep purple @170 kt
C5PP_B = np.array([40, 74, 178], dtype=np.float32)    # deep blue  @185 kt
LABEL = {'DB': 'TROPICAL DISTURBANCE  热带扰动', 'TD': 'TROPICAL DEPRESSION',
         'TS': 'TROPICAL STORM', 'C1': 'CATEGORY 1', 'C2': 'CATEGORY 2',
         'C3': 'CATEGORY 3', 'C4': 'CATEGORY 4', 'C5': 'CATEGORY 5',
         'C5+': 'CATEGORY 5+', 'C5++': 'CATEGORY 5++',
         'RV': 'REMNANT VORTEX  残余涡流', 'EX': 'EXTRATROPICAL  温带气旋'}

COL.update({'MV': COL['DB'], 'MD': COL['TD'], 'SD': COL['TD'], 'SS': COL['TS']})
LABEL.update({'MV': 'TROPICAL WAVE  东风波', 'MD': 'MONSOON DEPRESSION  季风低压',
              'SD': 'SUBTROPICAL DEPRESSION  副热带低压',
              'SS': 'SUBTROPICAL STORM  副热带风暴'})

def level_of(wind, phase):
    if phase in ('SD', 'SS'):
        return 'SD' if wind < 34 else 'SS'
    if phase != 'TC':
        return phase
    if wind < 34:  return 'TD'
    if wind < 64:  return 'TS'
    if wind < 83:  return 'C1'
    if wind < 96:  return 'C2'
    if wind < 113: return 'C3'
    if wind < 137: return 'C4'
    if wind <= 155: return 'C5'
    if wind < 170: return 'C5+'
    return 'C5++'

C6_END = np.array([198, 232, 255], dtype=np.float32)        # 200 kt anchor


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

# --- rule 16: CMA (m/s) + extended Beaufort card ---------------------------
# The mapping is the unit conversion the agency chart draws (JTWC kt row aligned
# with the CMA m/s row): m/s = kt * 0.51444, rounded the way the chart rounds.
# Knots read straight off the chart.  The relation is NOT the unit conversion
# (0.514444): it runs at 0.50 m/s per kt up to 80 kt, drops to ~0.357 through the
# middle, and returns to 0.50 above 150 kt.
CMA_KNOTS = [(30.0, 15.0), (80.0, 40.0), (150.0, 65.0), (160.0, 70.0), (190.0, 85.0)]
CMA_EASE = 0.75          # 75 % linear + 25 % smoothstep = "basically linear, eased"


# China's extended Beaufort scale (GB/T 28591) upper bounds in m/s
BEAUFORT = [(0.2, '0'), (1.5, '1'), (3.3, '2'), (5.4, '3'), (7.9, '4'),
            (10.7, '5'), (13.8, '6'), (17.1, '7'), (20.7, '8'), (24.4, '9'),
            (28.4, '10'), (32.6, '11'), (36.9, '12'), (41.4, '13'),
            (46.1, '14'), (50.9, '15'), (56.0, '16'), (61.2, '17')]
# CMA tropical-cyclone grades, low bound in m/s, with the spec's colours
CMA_GRADES = [(51.0, '超强台风', (232, 62, 62)),
              (41.5, '强台风', (255, 150, 214)),
              (32.7, '台风', (255, 150, 40)),
              (24.5, '强热带风暴', (255, 214, 60)),
              (17.2, '热带风暴', (86, 170, 255)),
              (10.8, '热带低压', (110, 210, 110)),
              (0.0, '热带扰动', (206, 214, 226))]

def kt_to_cma_ms(kt):
    """JTWC kt -> CMA m/s, as the agency chart draws it"""
    kt = float(kt)
    k0, v0 = CMA_KNOTS[0]
    ke, ve = CMA_KNOTS[-1]
    if kt <= k0:                       # below the first knot: the 0.50 run
        return kt * (v0 / k0)
    if kt >= ke:                       # above the last: 0.50 again
        return ve + (kt - ke) * ((CMA_KNOTS[-1][1] - CMA_KNOTS[-2][1]) /
                                 (CMA_KNOTS[-1][0] - CMA_KNOTS[-2][0]))
    for (a, b), (c, d) in zip(CMA_KNOTS, CMA_KNOTS[1:]):
        if a <= kt <= c:
            u = (kt - a) / (c - a)
            e = CMA_EASE * u + (1.0 - CMA_EASE) * (u * u * (3.0 - 2.0 * u))
            return b + (d - b) * e
    return ve

def beaufort_of(ms):
    for hi, name in BEAUFORT:
        if ms <= hi:
            return name
    return '17级以上'

def cma_grade_of(ms):
    for lo, name, col in CMA_GRADES:
        if ms >= lo:
            return name, col
    return CMA_GRADES[-1][1], CMA_GRADES[-1][2]

def _italic_mixed(base, xy, s, f_ascii, f_cjk, fill):
    """draw a mixed CJK/Latin string with an italic slant.  SimHei has no italic
    face, so the text is rendered to its own layer and sheared."""
    f = f_cjk
    tmp = Image.new('RGBA', (int(mixed_w(ImageDraw.Draw(base), s, f_ascii, f_cjk)) + 40, 40),
                    (0, 0, 0, 0))
    text_in_box(ImageDraw.Draw(tmp), (4, 0, tmp.width - 20, 24),
                s, f_ascii, f_cjk, fill)
    shear = 0.22
    w, h = tmp.size
    out = tmp.transform((w + int(shear * h), h), Image.AFFINE,
                        (1, shear, -shear * h, 0, 1, 0), resample=Image.BICUBIC)
    base.alpha_composite(out, (int(xy[0]), int(xy[1])))


def _lerp_rgb(a, b, u):
    u = max(0.0, min(1.0, u))
    return tuple(int(round(a[i] + (b[i] - a[i]) * u)) for i in range(3))

def theme_dim(wind):
    """how far the icon art is darkened at extreme intensity (1.0 = as authored)"""
    if wind <= 185.0:
        return 1.0
    return max(0.20, 1.0 - 0.80 * min(1.0, (wind - 185.0) / 15.0))

def landfall_scale(wind):
    """>155 kt landfalls grow by 5 % per knot, capped at 200 kt.  This applies to the
    impact effect only - the `Landed` marker is never scaled (spec rule 13)."""
    if wind <= 155.0:
        return 1.0
    return 1.0 + (min(wind, 200.0) - 155.0) * 0.05

# --- smooth (gradual) level transitions -------------------------------------
BANDS = [('TD', 0, 33), ('TS', 34, 63), ('C1', 64, 82), ('C2', 83, 95),
         ('C3', 96, 112), ('C4', 113, 136), ('C5', 137, 155),
         ('C5+', 156, 169), ('C5++', 170, 999)]
TRANS_K = 3.5      # kt half-width of an intensity transition
ICON_BLEND_KT = 14.0   # kt: how far a level's icon keeps fading after its band
TRANS_H = 2.5      # hour half-width of a phase transition

def intensity_weights(w):
    """soft alpha for EVERY level, from a Gaussian over the band each one covers.

    A band's alpha is 1 while the intensity is inside it and falls off with the
    DISTANCE outside it, so neighbouring levels stay partly visible and a fast
    intensity change dissolves through the intermediate art instead of snapping.
    """
    out = {}
    for lvl, lo, hi in BANDS:
        d = max(0.0, lo - w, w - hi)          # 0 inside the band
        a = math.exp(-(d / ICON_BLEND_KT) ** 2)
        if a > 0.004:
            out[lvl] = a
    tot = sum(out.values())
    if tot <= 0.0:                            # cannot happen: the bands tile
        return {BANDS[-1][0]: 1.0}
    return {k: v / tot for k, v in out.items()}


def band_index(w):
    i = 0
    for k, (lvl, lo, hi) in enumerate(BANDS):
        if w >= lo: i = k
    return i

def _phase_side(ph, w):
    """weights contributed by one side of a phase boundary"""
    return intensity_weights(w) if ph == 'TC' else {level_of(w, ph): 1.0}

def build_phases():
    """phase boundaries: midpoint between the last fix of one phase and the first
    fix of the next - derived, so any decomposition works"""
    global PHASE_BOUNDS
    PHASE_BOUNDS = []
    for i in range(1, len(S.hours)):
        if S.phase[i] != S.phase[i - 1]:
            PHASE_BOUNDS.append((float(S.hours[i]) if S.phase_at_fix[i] else
                                 (float(S.hours[i - 1]) + float(S.hours[i])) / 2.0,
                                 S.phase[i - 1], S.phase[i]))
    print('  phases: ' + ', '.join('%s->%s @h%.0f' % (a, b, h) for h, a, b in PHASE_BOUNDS))

def _phase_at(h):
    ph = PHASE_BOUNDS[0][1] if PHASE_BOUNDS else S.phase[0]
    for hb, pa, pb in PHASE_BOUNDS:
        if h >= hb: ph = pb
    return ph

def state_weights(h, w):
    # phase boundaries are derived from the series, never hard-coded
    for hb, pa, pb in PHASE_BOUNDS:
        if abs(h - hb) <= TRANS_H:
            t = (h - (hb - TRANS_H)) / (2.0 * TRANS_H)
            out = {}
            for k, v in _phase_side(pa, w).items(): out[k] = out.get(k, 0.0) + v * (1.0 - t)
            for k, v in _phase_side(pb, w).items(): out[k] = out.get(k, 0.0) + v * t
            return out
    ph = _phase_at(h)
    base = intensity_weights(w) if ph == 'TC' else {level_of(w, ph): 1.0}
    # Inside a rapid-intensification window the band change should read as
    # sudden, so the crossfade is sharpened.  It is NOT replaced by a blend to
    # the window's target level: with the 6 h / 24 h window test an event can run
    # 40 h, and holding the icon at the target would show a category the wind has
    # not reached for most of it.  The level always follows the wind.
    for h0, h1, _l0, _l1, _fx in RI_EVENTS:
        if h0 <= h <= h1 and h1 > h0:
            e = 1.0 / max(1e-6, RI_BLEND_FRAC)
            out = {k: (v ** e) for k, v in base.items()}
            tot = sum(out.values()) or 1.0
            return {k: v / tot for k, v in out.items()}
    return base

def state_color(h, w, sw):
    c = np.zeros(3, dtype=np.float32)
    tot = sum(sw.values()) or 1.0
    for lvl, wt in sw.items():
        c += (wt / tot) * np.array(theme_col(w, lvl), dtype=np.float32)
    return tuple(int(v) for v in np.clip(c, 0, 255))

def dominant(sw):
    return max(sw.items(), key=lambda kv: kv[1])[0]

@lru_cache(maxsize=128)
def font(path, size):
    return ImageFont.truetype(path, size)

def _text_font(text, fnt):
    """Select a CJK-capable face for user text; keep Latin-only typography intact."""
    if fnt is not None and any(0x2E80 <= ord(ch) <= 0xFFFF for ch in str(text)):
        path = str(getattr(fnt, 'path', '')).lower()
        bold = any(tag in path for tag in ('bold', 'consolab', 'arialbd', 'msyhbd'))
        return font(F_CJKB if bold else F_CJK, fnt.size)
    return fnt


def _font_runs(text, fnt):
    text = str(text)
    if fnt is None:
        return [(text, fnt)]
    path = str(getattr(fnt, 'path', '')).lower()
    bold = any(tag in path for tag in ('bold', 'msyhbd'))
    latin = globals()['font'](F_MONOB if bold else F_MONO, fnt.size)
    # Retain the requested Saira weight when the caller already chose one.
    if 'saira' in path:
        latin = fnt
    chinese = globals()['font'](F_CJKB if bold else F_CJK, fnt.size)
    if 'sourcehansanssc' in path:
        chinese = fnt
    return [(run, chinese if cjk else latin) for run, cjk in _runs(text)]


def draw_text(d, xy, text, font=None, **kwargs):
    runs = _font_runs(text, font)
    if len(runs) <= 1:
        value, face = runs[0] if runs else ('', font)
        return d.text(xy, value, font=face, **kwargs)
    # Compose mixed text on one baseline; Latin/digits always stay in Saira.
    anchor = kwargs.pop('anchor', None) or 'la'
    width = sum(d.textlength(value, font=face) for value, face in runs)
    boxes = [d.textbbox((0, 0), value, font=face, anchor='ls') for value, face in runs]
    top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
    x, y = xy
    if anchor[0] == 'm': x -= width / 2
    elif anchor[0] == 'r': x -= width
    vertical = anchor[1]
    if vertical == 't': y -= top
    elif vertical == 'm': y -= (top + bottom) / 2
    elif vertical == 'b': y -= bottom
    elif vertical == 'a': y += font.getmetrics()[0]
    elif vertical == 'd': y -= font.getmetrics()[1]
    for value, face in runs:
        d.text((x, y), value, font=face, anchor='ls', **kwargs)
        x += d.textlength(value, font=face)


def text_width(d, text, font=None, **kwargs):
    return sum(d.textlength(value, font=face, **kwargs)
               for value, face in _font_runs(text, font))


def _runs(s):
    out, cur, mode = [], '', None
    for ch in s:
        m = ord(ch) > 0x2E80
        if mode is None or m == mode:
            cur += ch
        else:
            out.append((cur, mode)); cur = ch
        mode = m
    if cur:
        out.append((cur, mode))
    return out

def mixed(d, xy, s, f_ascii, f_cjk, fill, tr=0.0):
    x, y = xy
    for run, m in _runs(s):
        f = f_cjk if m else f_ascii
        for ch in run:
            draw_text(d, (x, y), ch, font=f, fill=fill)
            x += text_width(d, ch, font=f) + tr
    return x

def mixed_w(d, s, f_ascii, f_cjk, tr=0.0):
    w = 0.0
    for run, m in _runs(s):
        f = f_cjk if m else f_ascii
        for ch in run:
            w += text_width(d, ch, font=f) + tr
    return w

def mixed_base(d, xy, s, f_ascii, f_cjk, fill, tr=0.0):
    """mixed draw on a shared baseline, so latin and CJK sit level"""
    x, y = xy
    for run, m in _runs(s):
        f = f_cjk if m else f_ascii
        for ch in run:
            draw_text(d, (x, y), ch, font=f, fill=fill, anchor='ls')
            x += text_width(d, ch, font=f) + tr
    return x

def mixed_top(d, xy, s, f_ascii, f_cjk, fill, tr=0.0):
    """mixed draw whose glyph TOPS sit at xy - the same optical position as
    draw_text(d, ..., anchor='la').  A pure-latin string keeps the latin ascent, so
    switching a row to the mixed helper does not move it."""
    x, y = xy
    has_cjk = any(m for _r, m in _runs(s))
    f0 = f_cjk if has_cjk else f_ascii
    return mixed_base(d, (x, y + f0.getmetrics()[0]), s, f_ascii, f_cjk, fill, tr)


def text_in_box(d, box, text, f_ascii, f_cjk, fill, tr=0.0, centre=False):
    """Align visible glyphs, not font ascenders; shrink only overflowing rows."""
    x0, y0, x1, y1 = box
    while True:
        runs = [(run, f_cjk if cjk else f_ascii) for run, cjk in _runs(text)]
        bounds = [d.textbbox((0, 0), run, font=f, anchor='ls') for run, f in runs]
        top = min((b[1] for b in bounds), default=0)
        bottom = max((b[3] for b in bounds), default=0)
        width = mixed_w(d, text, f_ascii, f_cjk, tr)
        if (width <= x1 - x0 and bottom - top <= y1 - y0) or min(f_ascii.size, f_cjk.size) <= 8:
            break
        f_ascii = f_ascii.font_variant(size=f_ascii.size - 1)
        f_cjk = f_cjk.font_variant(size=f_cjk.size - 1)
    x = x0 + (x1 - x0 - width) / 2 if centre else x0
    baseline = (y0 + y1 - top - bottom) / 2
    mixed_base(d, (x, baseline), text, f_ascii, f_cjk, fill, tr)

def tracked(d, xy, s, fnt, fill, tr=0.0):
    x, y = xy
    for ch in s:
        draw_text(d, (x, y), ch, font=fnt, fill=fill)
        x += text_width(d, ch, font=fnt) + tr
    return x

def tracked_w(d, s, fnt, tr):
    return sum(text_width(d, c, font=fnt) for c in s) + tr * max(0, len(s) - 1)

def _ramp(t, a, b):
    if t <= a: return 0.0
    if t >= b: return 1.0
    x = (t - a) / (b - a)
    return x * x * (3 - 2 * x)

def gauss(x, m, s):
    return np.exp(-((x - m) / s) ** 2)

# ----------------------------------------------------------------------------
# track data
# ----------------------------------------------------------------------------
class MonotoneCubic:
    """shape-preserving cubic Hermite (Fritsch-Carlson).

    A plain linear join of 3-hourly fixes draws flat treads between equal
    values and corners everywhere else - a staircase.  A natural cubic
    overshoots and invents peaks the data does not have.  This one is smooth,
    hits every fix exactly and never overshoots.
    """

    def __init__(self, x, y):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        n = len(self.x)
        if n < 3:
            self.m = np.zeros(n)
            if n == 2:
                self.m[:] = (self.y[1] - self.y[0]) / (self.x[1] - self.x[0])
            return
        d = np.diff(self.y) / np.diff(self.x)
        m = np.empty(n)
        m[0], m[-1] = d[0], d[-1]
        m[1:-1] = np.where(d[:-1] * d[1:] <= 0, 0.0, (d[:-1] + d[1:]) / 2.0)
        for i in range(n - 1):                     # Fritsch-Carlson limiter
            if d[i] == 0:
                m[i] = m[i + 1] = 0.0
                continue
            a, b = m[i] / d[i], m[i + 1] / d[i]
            q = a * a + b * b
            if q > 9.0:
                t = 3.0 / math.sqrt(q)
                m[i], m[i + 1] = t * a * d[i], t * b * d[i]
        self.m = m

    def __call__(self, xq):
        xq = np.asarray(xq, dtype=float)
        if len(self.x) < 2:
            return np.full(xq.shape, self.y[0] if len(self.y) else 0.0)
        i = np.clip(np.searchsorted(self.x, xq, 'right') - 1, 0, len(self.x) - 2)
        h = self.x[i + 1] - self.x[i]
        t = np.clip((xq - self.x[i]) / np.where(h == 0, 1.0, h), 0.0, 1.0)
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * self.y[i] + (t3 - 2 * t2 + t) * h * self.m[i]
                + (-2 * t3 + 3 * t2) * self.y[i + 1] + (t3 - t2) * h * self.m[i + 1])


def collapse_plateaus(hours, values):
    """collapse every run of equal values to one knot at the run's midpoint.

    Without this a plateau renders as a flat tread joined by two corners - the
    staircase look.  With it the curve keeps rising slowly through the plateau
    and reaches the plateau value at its middle.
    """
    hours = np.asarray(hours, dtype=float)
    values = np.asarray(values, dtype=float)
    n = len(hours)
    if n < 3:
        return hours, values
    hh, vv = [], []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[j + 1] == values[i]:
            j += 1
        if j > i:
            hh.append(0.5 * (hours[i] + hours[j]))    # midpoint of the run
            vv.append(values[i])
        else:
            hh.append(hours[i])
            vv.append(values[i])
        i = j + 1
    return np.array(hh, dtype=float), np.array(vv, dtype=float)


# --- data-format helpers ---------------------------------------------------
# Two time spellings are accepted in every data file:
#   YYYY-MM-DD-HH-MM-SS   (the original long form, used by the shipped storms)
#   YYYYMMDDHHmmSS          (14 digits, explicit four-digit year)
FIX_FMT_LONG = re.compile(r'^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$')
FIX_FMT_SHORT = re.compile(r'^\d{14}$')

def parse_fix_time(tok):
    """Parse an explicit four-digit year; never infer its century."""
    tok = tok.strip()
    if FIX_FMT_SHORT.fullmatch(tok) and len(tok) == 14:
        return datetime(int(tok[:4]), int(tok[4:6]), int(tok[6:8]),
                        int(tok[8:10]), int(tok[10:12]), int(tok[12:14]))
    if FIX_FMT_LONG.fullmatch(tok):
        return datetime(*(int(v) for v in tok.split('-')))
    raise ValueError('Expected YYYYMMDDHHmmSS (14 digits) or '
                     'YYYY-MM-DD-HH-MM-SS; two-digit years are ambiguous: %r' % tok)

# segment files, in life-cycle order; the short names win, the long ones remain
# supported so every shipped storm keeps loading
SEGMENTS = [('DB', 'Disturbance'), ('TC', 'BestTrack'),
            ('RV', 'Remnant_Vortex'), ('EX', 'Extratropical'),
            ('DB-LO', 'DB-LO'), ('DB-aL', 'DB-aL'), ('DB-MV', 'DB-MV'),
            ('DB-MD', 'DB-MD'), ('MV', 'Tropical_Wave'), ('MD', 'Monsoon_Depression'), ('SD', 'Subtropical_Depression'), ('SS', 'Subtropical_Storm')]

def normalize_phase(value):
    value = value.upper()
    aliases = {'DB-LO': 'DB', 'DB-AL': 'DB', 'DB-MV': 'MV', 'DB-MD': 'MD',
               'ST': 'SD', 'TD': 'TC', 'TS': 'TC',
               **{k: 'TC' for k in ('C1', 'C2', 'C3', 'C4', 'C5', 'C5+', 'C5++')}}
    value = aliases.get(value, value)
    if value not in ('DB', 'MV', 'MD', 'TC', 'RV', 'EX', 'SD', 'SS'):
        raise ValueError('Unknown cyclone type: %s' % value)
    return value


def segment_phase(filename, fallback='TC'):
    stem = os.path.splitext(os.path.basename(filename))[0].upper()
    return {'DB': 'DB', 'DB-LO': 'DB', 'DB-AL': 'DB',
            'DB-MV': 'MV', 'DB-MD': 'MD', 'MV': 'MV', 'MD': 'MD', 'SD': 'SD', 'SS': 'SS'}.get(stem, fallback)


def find_segment(short, long):
    """prefer <SHORT>.txt, else any file ending _<Long>.txt"""
    p = os.path.join(SRC, short + '.txt')
    if os.path.isfile(p):
        return p
    if os.path.isdir(SRC):
        for f in sorted(os.listdir(SRC)):
            if f.endswith('_%s.txt' % long):
                return os.path.join(SRC, f)
    return None

def auto_series():
    """the series list when the config does not declare one.

    An empty placeholder file (`DB.txt` created ahead of the data, or an
    `EX.txt` for a storm that never transitioned) is skipped rather than
    contributing a zero-point segment.
    """
    track = os.path.join(SRC, 'track.txt')
    if os.path.isfile(track):
        return [dict(file='track.txt')]
    out = []
    for short, long in SEGMENTS:
        p = find_segment(short, long)
        if not p:
            continue
        if not has_data_rows(p):
            print('  segment %s is empty - skipped' % os.path.basename(p))
            continue
        out.append(dict(file=os.path.basename(p), phase=segment_phase(p, short)))
    return out

def has_data_rows(path):
    """a segment file that carries at least one parsable fix"""
    try:
        for ln in open(path, encoding='utf-8'):
            t = ln.split()
            if len(t) >= 5 and not t[0].startswith('#'):
                return True
    except OSError:
        return False
    return False


class Series:
    """full life cycle, piecewise phase - built from the config's series list"""
    def __init__(self):
        def rd(p, default):
            out = []
            current = default
            for line_no, ln in enumerate(open(os.path.join(SRC, p), encoding='utf-8-sig'), 1):
                t = ln.split('#', 1)[0].split()
                if not t:
                    continue
                if len(t) not in (5, 6):
                    raise ValueError('%s:%d: expected 5 or 6 columns' % (p, line_no))
                if len(t) == 6:
                    try:
                        current = normalize_phase(t[5])
                    except ValueError as exc:
                        raise ValueError('%s:%d: %s' % (p, line_no, exc)) from exc
                if current is None:
                    raise ValueError('%s:%d: first track fix must specify its type' % (p, line_no))
                def num(v):
                    return float('nan') if v.upper() in ('N/A', 'NA', '-') else float(v)
                point = [parse_fix_time(t[0]), float(t[1]), float(t[2]), num(t[3]), num(t[4])]
                out.append((point, current, len(t) == 6))
            return out
        track = os.path.join(SRC, 'track.txt')
        specs = [dict(file='track.txt')] if os.path.isfile(track) else (_D.get('series') or auto_series())
        if not specs:
            raise SystemExit('no track files: provide track.txt or data.series / legacy phase files')
        raw = []
        for sp in specs:
            unified = os.path.basename(sp['file']).lower() == 'track.txt'
            default = None if unified else normalize_phase(segment_phase(sp['file'], sp.get('phase', 'TC')))
            pts = rd(sp['file'], default)
            sf = int(sp.get('skip_first', 0) or 0)
            sl = int(sp.get('skip_last', 0) or 0)
            pts = pts[sf:len(pts) - sl if sl else None]
            raw.extend((point, phase, unified or explicit) for point, phase, explicit in pts)
        raw.sort(key=lambda r: r[0][0])
        merged = []
        for record in raw:
            if merged and record[0][0] == merged[-1][0][0]:
                old = merged[-1]
                if old[1] != record[1] or not np.allclose(old[0][1:], record[0][1:], equal_nan=True):
                    raise ValueError('Conflicting fixes at %s' % record[0][0])
                continue
            merged.append(record)
        raw = merged
        if not raw:
            raise ValueError('No track fixes remain after reading / trimming input')
        t0 = raw[0][0][0]
        self.phase_at_fix = [r[2] for r in raw]
        self.t0 = t0
        self.t     = [r[0][0] for r in raw]
        self.phase = [r[1] for r in raw]
        self.hours = np.array([(r[0][0] - t0).total_seconds() / 3600.0 for r in raw])
        self.lon   = np.array([r[0][1] for r in raw])
        self.lat   = np.array([r[0][2] for r in raw])
        self.wind  = np.array([r[0][3] for r in raw])
        self.pres  = np.array([r[0][4] for r in raw])
        # longitude is kept in 0..360 so a track that crosses the dateline stays
        # continuous: -177.8 becomes 182.2 and the polyline never jumps the map
        self.lon = np.mod(self.lon, 360.0)
        for i in range(1, len(self.lon)):        # unwrap any residual seam
            while self.lon[i] - self.lon[i - 1] < -180.0:
                self.lon[i] += 360.0
            while self.lon[i] - self.lon[i - 1] > 180.0:
                self.lon[i] -= 360.0
        # ---- re-analysis overrides: a separate (non-uniform) intensity grid ----
        # only fixes that actually carry an intensity feed this grid, so a
        # path-only densified fix never injects a NaN into the curve
        valid = ~np.isnan(self.wind)
        ih = [float(self.hours[i]) for i in range(len(self.hours)) if valid[i]]
        iw = [float(self.wind[i]) for i in range(len(self.hours)) if valid[i]]
        ip = [float(self.pres[i]) for i in range(len(self.hours)) if valid[i]]
        if not ih:
            raise SystemExit('no fix in the series carries a wind value')
        # a fix may carry a wind but no pressure ("N/A" in the data).  Fill those
        # by interpolation so the pressure curve stays finite - a NaN knot would
        # otherwise reach the HUD and blow up on '%d' % round(nan).
        _pa = np.array(ip, dtype=float)
        _bad = np.isnan(_pa)
        if _bad.any():
            if (~_bad).any():
                _pa[_bad] = np.interp(np.array(ih, dtype=float)[_bad],
                                      np.array(ih, dtype=float)[~_bad], _pa[~_bad])
                print('  %d fix(es) had no pressure - interpolated' % int(_bad.sum()))
            else:
                raise SystemExit('no fix in the series carries a pressure value')
            ip = list(_pa)
        for ov in (_D.get('reanalysis', {}) or {}).get('set', []) or []:
            j = int(np.argmin(np.abs(np.array(ih) - float(ov['h']))))
            if 'wind' in ov: iw[j] = float(ov['wind'])
            if 'pres' in ov: ip[j] = float(ov['pres'])
        for ins in (_D.get('reanalysis', {}) or {}).get('insert', []) or []:
            k = int(np.searchsorted(np.array(ih), float(ins['h'])))
            ih.insert(k, float(ins['h']))
            iw.insert(k, float(ins['wind']))
            ip.insert(k, float(ins['pres']))
        self.ihours = np.array(ih, dtype=float)
        self.iwind  = np.array(iw, dtype=float)
        self.ipres  = np.array(ip, dtype=float)
        # smooth display curve for wind / pressure.  Wind and pressure are
        # collapsed and interpolated INDEPENDENTLY - a pressure plateau must not
        # drag the wind curve with it.
        ease = str(_D.get('plateau_ease', True)).lower() not in ('false', '0', 'no')
        if ease:
            wh, wv = collapse_plateaus(self.ihours, self.iwind)
            ph, pv = collapse_plateaus(self.ihours, self.ipres)
        else:
            wh, wv, ph, pv = self.ihours, self.iwind, self.ihours, self.ipres
        self.wknots, self.pknots = (wh, wv), (ph, pv)
        self.WF = MonotoneCubic(wh, wv)
        self.PF = MonotoneCubic(ph, pv)
        if str(_D.get('intensity_curve', 'monotone')).lower() == 'linear':
            self.WF = lambda q: np.interp(q, wh, wv)
            self.PF = lambda q: np.interp(q, ph, pv)
        if ease:
            print('  plateau easing: %d -> %d wind knots, %d -> %d pressure knots'
                  % (len(self.ihours), len(wh), len(self.ihours), len(ph)))
        # ACE: sample the intensity on the 00/06/12/18Z synoptic grid and sum
        # v^2 there.  That is the WMO convention, it needs no particular fix
        # spacing, and for a track whose fixes already sit on that grid it
        # reproduces the discrete sum exactly.  Drawing the running total as a
        # continuous ramp also stops the bar jerking 6-hourly.
        self.ace_end_h = float(_D.get('ace_end_h', self.hours[-1]))
        off = (-self.t0.hour) % 6                 # hours to the first synoptic time
        syn_h = np.arange(float(off), self.hours[-1] + 1e-6, 6.0)
        syn_h = syn_h[syn_h <= self.ace_end_h + 1e-6]
        if len(syn_h):
            # read the intensity off the RAW grid (fixes + re-analysis), never
            # off the display curve: plateau easing is a cosmetic choice and
            # must not move a published number
            w_syn = np.interp(syn_h, self.ihours, self.iwind)
            # Row type is effective at its timestamp, including repeated TC/RV cycles.
            indices = np.clip(np.searchsorted(self.hours, syn_h, side='right') - 1,
                              0, len(self.phase) - 1)
            tc_syn = np.array([self.phase[i] == 'TC' for i in indices])
            a = np.where(tc_syn & (w_syn >= 34), w_syn ** 2, 0.0) / 1e4
            cum = np.concatenate([[0.0], np.cumsum(a)])
            self.ace = np.interp(self.hours, np.concatenate([[syn_h[0]], syn_h]), cum)
            self.ace_total = float(cum[-1])
        else:
            self.ace = np.zeros(len(self.hours))
            self.ace_total = 0.0
        self.step_h = float(np.median(np.diff(self.hours))) if len(self.hours) > 1 else 6.0
        self.duration_h = float(self.hours[-1])

S = None                      # built by _build() once the config is loaded

@lru_cache(maxsize=8192)
def sample(h):
    h = float(max(0.0, min(S.duration_h, h)))
    # segment lookup against the REAL fix times, so 3-hourly and 6-hourly
    # tracks both interpolate correctly
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
    ace  = float(np.interp(h, S.hours, S.ace))
    ph   = S.phase[min(len(S.phase) - 1, int(np.searchsorted(S.hours, h, 'right')) - 1)]
    return lon, lat, wind, pres, ace, ph

# ---- time warp -------------------------------------------------------------
# the profile slows down at genesis, the strongest peak, landfall and
# dissipation; the two interior points are normally given as data fractions so
# the pauses land on the right moments for any storm length
_N = 4000
_tau = np.linspace(0.0, 1.0, _N)
_sp = np.ones_like(_tau)
_cum = _tau.copy()

def _build_warp():
    """(re)build the speed profile once the series and landfalls are known"""
    global _sp, _cum
    tpk = float(_c('view.warp_peak_tau', 0.53))
    tld = float(_c('view.warp_land_tau', 0.71))
    if str(_c('view.warp', '')).lower() == 'auto' and S is not None:
        pks = _D.get('peaks') or []
        if pks:
            p = max(pks, key=lambda x: float(np.interp(float(x['h']), S.ihours, S.iwind)))
            tpk = float(p['h']) / S.duration_h
        if LANDFALLS:
            tld = max(float(l['h']) for l in LANDFALLS) / S.duration_h
    _sp = (1.0 - 0.42 * gauss(_tau, tpk, 0.085)    # peak
               - 0.26 * gauss(_tau, tld, 0.055)    # landfall
               - 0.16 * gauss(_tau, 0.06, 0.07)    # genesis
               - 0.12 * gauss(_tau, 0.98, 0.05))   # dissipation
    _cum = np.concatenate([[0.0], np.cumsum((_sp[:-1] + _sp[1:]) * 0.5 * np.diff(_tau))])
    _cum /= _cum[-1]
    print('  warp: peak at tau=%.3f, landfall at tau=%.3f' % (tpk, tld))

_build_warp()

def tau_to_u(t): return float(np.interp(t, _tau, _cum))
def u_to_tau(u): return float(np.interp(u, _cum, _tau))
def t_of_hours(h): return INTRO + u_to_tau(h / S.duration_h) * MAIN
def hours_of_t(t):
    if t <= INTRO: return 0.0
    if t >= INTRO + MAIN: return S.duration_h
    return tau_to_u((t - INTRO) / MAIN) * S.duration_h

def cross(v, rising):
    """first (rising) / last (falling) data hour where the curve crosses v"""
    hs = np.arange(0.0, S.duration_h, 0.01)
    ws = np.asarray(S.WF(hs), dtype=float)
    if rising:
        idx = np.where((ws[:-1] < v) & (ws[1:] >= v))[0]
        return float(hs[idx[0]]) if len(idx) else None
    idx = np.where((ws[:-1] >= v) & (ws[1:] < v))[0]
    return float(hs[idx[-1]]) if len(idx) else None

def crossings(v, rising=True, skip_phases=()):
    """every crossing of v - a storm can weaken below TS and re-intensify, and
    each upgrade should fire its own effect.  Crossings inside `skip_phases` are
    ignored: a gale recovering inside an extratropical system is not a tropical
    storm upgrade."""
    hs = np.arange(0.0, S.duration_h, 0.01)
    ws = np.asarray(S.WF(hs), dtype=float)
    if rising:
        idx = np.where((ws[:-1] < v) & (ws[1:] >= v))[0]
    else:
        idx = np.where((ws[:-1] >= v) & (ws[1:] < v))[0]
    out = []
    for k in idx:                       # collapse crossings inside one fix gap
        h = float(hs[k])
        if skip_phases and _phase_at(h) in skip_phases:
            continue
        if not out or h - out[-1] > 12.0:
            out.append(h)
    return out

BANNER_BY_LEVEL = {'TD': 'Summary-N-TC-TD.mp4', 'TS': 'Summary-N-TC-TS.mp4',
                   'C1': 'Summary-N-TC-C1.mp4', 'C2': 'Summary-N-TC-C2.mp4',
                   'C3': 'Summary-N-TC-C3.mp4', 'C4': 'Summary-N-TC-C4.mp4',
                   'C5': 'Summary-N-TC-C5.mp4', 'C5+': 'Summary-N-TC-C5.mp4',
                   'C5++': 'Summary-N-TC-C5.mp4'}

def peak_wind():
    """strongest configured peak, in knots"""
    pks = _D.get('peaks') or []
    if not pks or S is None:
        return 0.0
    return max(float(S.WF(p['h'])) for p in pks)

def banner_asset():
    """the banner art matches the storm's peak category - a C2 storm must not
    wear the C5 banner"""
    explicit = _c('banner.asset') or _CL.get('banner')
    if explicit:
        return explicit
    return BANNER_BY_LEVEL.get(level_of(peak_wind(), 'TC'), 'Summary-N-TC-C5.mp4')

def _last_landfall_h():
    src = landfall_file()
    if src:
        recs = _parse_landfall_file(os.path.join(SRC, src))
        if recs: return (recs[-1]['when'] - S.t0).total_seconds() / 3600.0
    lf = _D.get('landfalls') or []
    if isinstance(lf, list) and lf: return float(lf[-1]['h'])
    return 0.0

def upgrade_hours():
    """Every strengthening entry into TS or SS, including phase-only entries."""
    hs = np.arange(0.0, S.duration_h + 0.01, 0.01)
    hs = hs[hs <= S.duration_h]
    ws = np.asarray(S.WF(hs), dtype=float)
    candidates = [float(hb) for hb, _pa, _pb in PHASE_BOUNDS]
    for i in np.where((ws[:-1] < 34.0) & (ws[1:] >= 34.0))[0]:
        lo, hi = float(hs[i]), float(hs[i + 1])
        for _ in range(32):
            mid = (lo + hi) / 2.0
            if float(S.WF(mid)) < 34.0:
                lo = mid
            else:
                hi = mid
        candidates.append(hi)
    events = []
    for h in sorted(candidates):
        eps = 1e-4
        before, after = max(0.0, h - eps), min(S.duration_h, h + eps)
        w0, w1 = float(S.WF(before)), float(S.WF(after))
        old = level_of(w0, _phase_at(before))
        new = level_of(w1, _phase_at(after))
        if new in ('TS', 'SS') and old != new and w1 > w0 + 1e-7:
            if not events or h - events[-1] > 1e-5:
                events.append(h)
    return events


def build_key():
    peaks = _D.get('peaks') or []
    return dict(disturbance=0.0, ts=cross(34, True), c1=cross(64, True),
                c4=cross(113, True), c5end=cross(113, False),
                peak1=peaks[0]['h'] if peaks else 0.0,
                peak2=peaks[1]['h'] if len(peaks) > 1 else S.duration_h,
                ts_all=upgrade_hours(),
                w170a=cross(170, True), w170b=cross(170, False),
                landfall=float(_c('audio.landfall_h', 0.0)) or _last_landfall_h(),
                xt=float(_c('audio.xt_h', S.duration_h)),
                end=S.duration_h)

KEY = {}

def _ts_fx_hours():
    """TC and subtropical 34 kt upgrades share this FX; EX never triggers it."""
    return [h for h in KEY.get('ts_all', ()) if _phase_at(h) in ('TC', 'SD', 'SS')]


# ----------------------------------------------------------------------------
# base map - the whole-world basin map, route and resolution only
#
# `map/basins/EARTH.png` is the global equirectangular map: the same 0..360 /
# +-90 frame the camera already works in.  It arrives already composited, so the
# separate Graticule/RegionLine overlay and the 0.94 dim that the old
# `map/sources/` route needed are gone with the route, and its grid is read at
# load rather than assumed, so raising the file's resolution needs no code
# change.
# ----------------------------------------------------------------------------
_BASE = None
_DIMS = None
def base_map():
    global _BASE, _DIMS
    if _BASE is None:
        # the basin map is a known asset, not an untrusted download, and at
        # 21600x10800 it is past PIL's 178.9 Mpx decompression-bomb limit
        Image.MAX_IMAGE_PIXELS = None
        _BASE = np.asarray(Image.open(os.path.join(
            ASSETS, 'map', 'basins', 'EARTH.png')).convert('RGB'))
        _DIMS = _BASE.shape[1], _BASE.shape[0]
    return _BASE

_VIG = None
def vignette():
    global _VIG
    if _VIG is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        v = 1.0 - 0.34 * np.clip((r - 0.55) / 0.95, 0, 1) ** 1.5
        _VIG = np.dstack([v, v, v]).astype(np.float32)
    return _VIG

def cam_frame(cam_lon, cam_lat, span_lon=None):
    """sub-pixel camera crop; returns (rgb uint8 frame, projector)"""
    if span_lon is None:
        span_lon = SPAN0_LON
    span_lat = span_lon * 9.0 / 16.0
    B = base_map()
    MW, MH = _DIMS                       # the base map's own grid
    sw = span_lon / 360.0 * MW
    sh = span_lat / 180.0 * MH
    fx = (cam_lon - span_lon / 2.0) / 360.0 * MW
    fy = (90.0 - cam_lat - span_lat / 2.0) / 180.0 * MH
    ix, iy = int(math.floor(fx)), int(math.floor(fy))
    dx, dy = fx - ix, fy - iy
    iw, ih = int(math.ceil(sw)) + 2, int(math.ceil(sh)) + 2
    ix = max(0, min(MW - iw, ix)); iy = max(0, min(MH - ih, iy))
    sub = B[iy:iy + ih, ix:ix + iw]
    M = np.float32([[1, 0, -dx], [0, 1, -dy]])
    img = cv2.warpAffine(sub, M, (int(round(sw)), int(round(sh))),
                         flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(img, (0, 0), 1.35)
    img = cv2.addWeighted(img, 1.5, blur, -0.5, 0)        # unsharp for the tight zoom
    img = np.clip(img.astype(np.float32) * vignette(), 0, 255).astype(np.uint8)
    lon0 = (ix + dx) / MW * 360.0
    lat1 = 90.0 - (iy + dy) / MH * 180.0
    def proj(lon, lat):
        return ((lon - lon0) / span_lon * W, (lat1 - lat) / span_lat * H)
    return img, proj

# ----------------------------------------------------------------------------
# asset extraction
# ----------------------------------------------------------------------------
ICONS = {'DB': ('disturbance/N-DB-aL.mp4', True), 'TD': ('tc_sshws/N-TD-D.mp4', True),
         'TS': ('tc_sshws/N-TC-TS.mp4', True), 'C1': ('tc_sshws/N-TC-C1.mp4', True),
         'C2': ('tc_sshws/N-TC-C2.mp4', True), 'C3': ('tc_sshws/N-TC-C3.mp4', True),
         'C4': ('tc_sshws/N-TC-C4.mp4', True), 'C5': ('tc_sshws/N-TC-C5.mp4', True),
         'C5+': ('tc_sshws/N-TC-C5.mp4', True), 'C5++': ('tc_sshws/N-TC-C5.mp4', True),
         'RV': ('N-TC-X.mp4', True), 'EX': ('extratropicals/N-EX-EX.mp4', True)}
ICON_FPS, N_ICON = 20, 600
# the icon art is 1800 frames at 60 fps and the library turns it 6 whole times
# over that loop; we keep every third frame, so 600 frames still = 6 turns
ICON_TURNS = 6.0

ICONS.update({'MV': ('disturbance/N-DB-aWV.mp4', True),
              'MD': ('disturbance/N-TD-MD.mp4', True),
              'SD': ('extratropicals/N-EX-SD.mp4', True),
              'SS': ('extratropicals/N-EX-SS.mp4', True)})

def icon_jobs():
    jobs = dict(ICONS)
    if S is not None and np.any(S.lat < 0):
        jobs.update({'S_' + k: (rel.replace('N-', 'S-'), flag)
                     for k, (rel, flag) in ICONS.items()})
    return jobs


def extract_icons():
    for k, (rel, _) in icon_jobs().items():
        src = os.path.join(ASSETS, 'mainicon', rel.replace('/', os.sep))
        d = os.path.join(ICOND, k.replace('+', 'p'))
        if os.path.isdir(d) and len(os.listdir(d)) >= N_ICON - 2:
            continue
        os.makedirs(d, exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-vf',
                        "select=not(mod(n\\,3)),setpts=N/%d/TB" % ICON_FPS,
                        '-fps_mode', 'passthrough', '-start_number', '0',
                        os.path.join(d, '%04d.png')], check=True)
        print('icon', k, len(os.listdir(d)))

def extract_fx():
    _ensure_cache_dirs()
    jobs = [('landfall/[Landing]C1.mp4', 'landing', 60),
            ('landfall/Landed-C1.mp4', 'landed', 60),
            ('landfall/[Landing]C5.mp4', 'landing5', 60),
            ('landfall/Landed-C5.mp4', 'landed5', 60),
            ('landfall/landfall-C6.mp4', 'landing6', 60),
            ('landfall/[Landing]S.mp4', 'landingS', 60),
            ('landfall/Landed-S.mp4', 'landedS', 60),
            ('landfall/[Landing]D.mp4', 'landingD', 60),
            ('landfall/landfall-TD.mp4', 'landingTD', 60),
            ('landfall/Landed-D.mp4', 'landedD', 60),
            ('landfall/[Landing]C2.mp4', 'landing2', 60),
            ('landfall/[Landing]C3.mp4', 'landing3', 60),
            ('landfall/[Landing]C4.mp4', 'landing4', 60),
            ('landfall/Landed-C2.mp4', 'landed2', 60),
            ('landfall/Landed-C3.mp4', 'landed3', 60),
            ('landfall/Landed-C4.mp4', 'landed4', 60),
            ('gui/TY-LOGO-N.mp4', 'logo', 20),
            ('particle/note_ts.mp4', 'notets', 60),
            ('particle/sweep.gif', 'sweep', 10),
            ('particle/ERI.gif', 'eri', 10)]
    # banner used by the pulled-back panorama card.  Cache per asset so a change
    # of peak level actually re-extracts instead of reusing the old frames - and
    # drop the other caches, or a stale one gets picked up later.
    _bname = 'sumban_' + banner_asset().replace('Summary-N-TC-', '').replace('.mp4', '')
    for _old in list(os.listdir(FXD)):
        if _old.startswith('sumban') and _old != _bname:
            shutil.rmtree(os.path.join(FXD, _old), ignore_errors=True)
    d = os.path.join(FXD, _bname)
    if not (os.path.isdir(d) and len(os.listdir(d)) > 20):
        os.makedirs(d, exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i',
                        os.path.join(ASSETS, 'summary', banner_asset()),
                        '-t', '5', '-vf', 'fps=60', '-start_number', '0',
                        os.path.join(d, '%03d.png')], check=True)
        print('fx sumban', len(os.listdir(d)))
    for rel, name, fps in jobs:
        d = os.path.join(FXD, name)
        if os.path.isdir(d) and len(os.listdir(d)) > 5:
            continue
        os.makedirs(d, exist_ok=True)
        src = os.path.join(ASSETS, rel.replace('/', os.sep))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src,
                        '-vf', 'setpts=N/%d/TB' % fps, '-fps_mode', 'passthrough',
                        '-start_number', '0', os.path.join(d, '%03d.png')], check=True)
        print('fx', name, len(os.listdir(d)))

def extract_cloud():
    if not CLOUD_FILE:
        print('cloud: none configured, skipping')
        return
    if not os.path.isdir(CLOUDD):
        os.makedirs(CLOUDD, exist_ok=True)
    if len(os.listdir(CLOUDD)) > 100:
        return
    vf = 'select=not(mod(n\\,%d))' % CLOUD_STEP_EVERY
    crop = int(_CL.get('crop', 0) or 0)
    if crop:                       # a wide product only needs its centre here
        vf += ',crop=%d:%d' % (crop, crop)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i',
                    os.path.join(SRC, CLOUD_FILE),
                    '-vf', vf, '-fps_mode', 'passthrough',
                    '-q:v', '3', '-start_number', '0',
                    os.path.join(CLOUDD, '%04d.jpg')], check=True)
    print('cloud', len(os.listdir(CLOUDD)))

# cloud video: frame f -> hours since 09-08 18Z  (uniform except one 46 h gap)
_CL = {}
CLOUD_FILE = ''
CLOUD_STEP_EVERY = 4
CLOUD_H0 = CLOUD_STEP = 0.0
CLOUD_F0 = CLOUD_F1 = CLOUD_G0 = CLOUD_G1 = 0
CLOUD_HA = CLOUD_HB = CLOUD_HEND = 0.0

def cloud_state(h):
    """returns (frame_index or None, available)"""
    if not CLOUD_FILE:
        return None, False
    if h < CLOUD_H0 - 0.5:
        return None, False
    if h <= CLOUD_HA:
        return (h - CLOUD_H0) / CLOUD_STEP, True
    if CLOUD_G1 <= CLOUD_G0:            # single continuous loop -> hold the last frame
        return CLOUD_F1, True
    if h < CLOUD_HB:
        return None, False
    if h <= CLOUD_HEND + 1:
        return CLOUD_G0 + (h - CLOUD_HB) / CLOUD_STEP, True
    return CLOUD_G1, True

# ----------------------------------------------------------------------------
# panel geometry  (all fonts are 1.5x v4, panels grown to match)
# ----------------------------------------------------------------------------
P_TL  = (40, 30, 530, 336)
P_ACE = (1160, 210, 720, 154)
P_GR  = (40, 530, 700, 356)
P_LG  = (40, 894, 700, 58)
P_TL2 = (40, 962, 1840, 84)
CLOUD_C = (1640, 620)
CLOUD_R = 210

def panel(d, box, fill=(7, 11, 22, 205), border=(255, 255, 255, 92), r=4):
    x, y, w, h = box
    d.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill,
                        outline=border, width=1)

# ----------------------------------------------------------------------------
# static HUD
# ----------------------------------------------------------------------------
HUD_CORNER_SCALE = 0.85


def compact_corner_hud(layer):
    """Scale completed static + live corner groups together; timeline stays native."""
    out = layer.copy()
    groups = [((0, 0, 700, 390), 'TL'),
              ((740, 0, W, 415), 'TR'),
              ((0, 510, 760, 954), 'BL')]
    for box, anchor in groups:
        part = layer.crop(box)
        out.paste((0, 0, 0, 0), box)
        size = tuple(max(1, round(v * HUD_CORNER_SCALE)) for v in part.size)
        part = part.resize(size, Image.Resampling.LANCZOS)
        if anchor == 'TL':
            xy = (round(40 * (1 - HUD_CORNER_SCALE)), round(30 * (1 - HUD_CORNER_SCALE)))
        elif anchor == 'TR':
            xy = (1880 - round((1880 - box[0]) * HUD_CORNER_SCALE), round(30 * (1 - HUD_CORNER_SCALE)))
        else:
            xy = (round(40 * (1 - HUD_CORNER_SCALE)), 952 - round((952 - box[1]) * HUD_CORNER_SCALE))
        out.alpha_composite(part, xy)
    return out


def build_hud():
    hud = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(hud)
    f_lbl = font(F_MONO, 22)
    panel(d, P_TL)
    tracked(d, (66, 50), 'UTC TIME', f_lbl, (236, 243, 252, 255), 3.0)
    tracked(d, (66, 146), 'POSITION', f_lbl, (236, 243, 252, 255), 3.0)

    f1 = font(F_UI, 60); f2 = font(F_CJK, 30); f3 = font(F_MONO, 20)
    s1 = _S.get('title', 'TYPHOON')
    w1 = tracked_w(d, s1, f1, 4.5)
    tracked(d, (1880 - w1, 30), s1, f1, (255, 255, 255, 255), 4.5)
    draw_text(d, (1880, 112), '%s  -  %s' % (_S.get('name_cn_long', _S.get('name_cn', '')),
                                       _S.get('id', '')),
           font=f2, fill=(244, 249, 254, 255), anchor='ra')
    draw_text(d, (1880, 160), _S.get('source_line', 'BEST TRACK + POST-ANALYSIS'), font=f3,
           fill=(224, 234, 248, 255), anchor='ra')

    panel(d, P_ACE)
    tracked(d, (P_ACE[0] + 18, P_ACE[1] + 14), 'ACCUMULATED CYCLONE ENERGY (TC)',
            font(F_MONO, 21), (240, 246, 254, 255), 1.5)
    draw_text(d, (P_ACE[0] + P_ACE[2] - 18, P_ACE[1] + 62), 'x10^4 kt2',
           font=font(F_MONO, 21), fill=(232, 240, 252, 255), anchor='ra')

    panel(d, P_GR)
    tracked(d, (P_GR[0] + 18, P_GR[1] + 14), 'INTENSITY  ', font(F_MONO, 21),
            (236, 243, 252, 255), 1.5)
    mixed(d, (P_GR[0] + 186, P_GR[1] + 14), '强度演变', font(F_MONO, 21),
          font(F_CJK, 21), (236, 243, 252, 255), 1.5)
    gx0, gy0 = P_GR[0] + 78, P_GR[1] + 62
    gx1, gy1 = P_GR[0] + P_GR[2] - 62, P_GR[1] + P_GR[3] - 50
    # LEFT axis = pressure, RIGHT axis = wind.  The category gridlines belong to
    # the wind curve, so their values sit on the right.
    for v in range(870, 1011, 20):
        yy = gy1 - ((v - 855.0) / (1015.0 - 855.0)) * (gy1 - gy0)
        if gy0 - 1 <= yy <= gy1 + 1:
            d.line([gx0 - 6, yy, gx0, yy], fill=(226, 236, 250, 130), width=1)
            draw_text(d, (gx0 - 11, yy), str(v), font=font(F_MONO, 16),
                   fill=(226, 236, 250, 240), anchor='rm')
    for k, v in (('C1', 64), ('C2', 83), ('C3', 96), ('C4', 113), ('C5', 137),
                 ('C5+', 155), ('C5++', 170)):
        yy = gy1 - (min(WIND_AXIS, v) / WIND_AXIS) * (gy1 - gy0)
        gc = COL[k] if k in COL else theme_col(170, 'C5++')
        d.line([gx0, yy, gx1, yy], fill=gc + (52,), width=1)
        d.line([gx1, yy, gx1 + 6, yy], fill=gc + (150,), width=1)
        draw_text(d, (gx1 + 11, yy), str(v), font=font(F_MONO, 16),
               fill=gc + (240,), anchor='lm')
    d.line([gx0, gy0, gx0, gy1], fill=(255, 255, 255, 60), width=1)
    d.line([gx0, gy1, gx1, gy1], fill=(255, 255, 255, 60), width=1)
    draw_text(d, (gx1 - 6, gy1 + 26), date_span_label(), font=font(F_MONO, 18),
           fill=(204, 216, 234, 255), anchor='ra')
    for xx in (gx0, gx1):
        d.line([xx, gy1 + 6, xx, gy1 + 14], fill=(255, 255, 255, 90), width=1)

    panel(d, P_LG)
    lx = P_LG[0] + 16
    for k in ('TD', 'TS', 'C1', 'C2', 'C3', 'C4', 'C5', 'C5+', 'C5++'):
        c = COL[k] if k != 'C5++' else theme_col(170, 'C5++')
        d.ellipse([lx, P_LG[1] + 21, lx + 16, P_LG[1] + 37], fill=c)
        draw_text(d, (lx + 21, P_LG[1] + 29), k, font=font(F_MONO, 18),
               fill=(244, 249, 255, 255), anchor='lm')
        lx += 75

    panel(d, P_TL2)
    tx0, tx1 = P_TL2[0] + 170, P_TL2[0] + P_TL2[2] - 36
    ty = P_TL2[1] + 32
    d.line([tx0, ty, tx1, ty], fill=(255, 255, 255, 70), width=2)
    for h, lab in day_ticks():
        x = tx0 + (h / S.duration_h) * (tx1 - tx0)
        d.line([x, ty - 10, x, ty + 10], fill=(255, 255, 255, 185), width=2)
        draw_text(d, (x, ty + 17), lab, font=font(F_MONO, 18),
               fill=(232, 240, 252, 255), anchor='ma')
    for k in range(96):
        h = 24.0 * k + 12.0
        if h > S.duration_h: break
        x = tx0 + (h / S.duration_h) * (tx1 - tx0)
        d.line([x, ty - 5, x, ty + 5], fill=(255, 255, 255, 80), width=1)
    tracked(d, (P_TL2[0] + 20, ty), month_label(), font(F_MONO, 21),
            (236, 243, 252, 255), 2.0)
    return hud

# ----------------------------------------------------------------------------
# damage events
# ----------------------------------------------------------------------------
DAMAGE = []
LANDFALLS = []
RI_EVENTS = []
RI_FX_SKIP = ('C1', 'C5+', 'C5++')   # jumps landing here blend without the ERI burst
RI_BLEND_FRAC = 0.45           # a RI blend completes in this share of its interval
PHASE_BOUNDS = []
LABEL_HOLD_S = 2.0         # rule 2: a map label lives this long
LABEL_FADE_S = 0.6         # ...then fades over this
MARKER_SCALE = 0.30        # rule 3: Landed marker at 30 % of its old size
CARD_FADE = 0.55          # rule 3: a column slides + fades out over this long
CARD_CYCLE = 4.0           # rule 7: a card column shows for this long
HUD_IN_DUR = 0.55          # item 6: how long a panel takes to fly in
HUD_IN_SLIDE = 70          # ...and how far it travels, in pixels
CARD_W = 440               # end-card width
CARD_X_L = 40              # left (peak) column
CARD_M = 40                # right (landfall) column margin
EF_ICON_SCALE = 0.75       # how small the icon goes while a pinhole-eye storm holds C3
POPUP_DUR = 2.9
POPUP_SPEED = 1.5          # rule 15: damage popups fly 1.5x faster
POPUP_APEX = 147.0
RI_FX_DUR = 0.3

def landfall_file():
    """the config's data.landfall_file, or the standard sourcedata\landfall.txt"""
    spec = _D.get('landfall_file')
    if spec:
        return spec
    p = os.path.join(SRC, 'landfall.txt')
    return 'landfall.txt' if os.path.isfile(p) else None

def _parse_landfall_file(path):
    """normalised landfall list, one line per landfall.  Two layouts are read:

        <Name>   <UTC time>   <lon>   <lat>        <- current format
        Itbayat  20260913170000 121.84 20.79

        <Name>   <M.D> <HHz>  <lat>   <lon>        <- legacy format
        Itbayat  9.13 17z     20.79   121.84

    The two are told apart by the token three from the right: the legacy month
    always carries a dot, a timestamp never does.  The legacy layout also has
    latitude before longitude; the current one is lon-first like the track.

    A time may be YYYYMMDDHHmmSS, YYYY-MM-DD-HH-MM-SS, or M.D + HHz.  The year is
    explicit in full timestamps; only legacy M.D entries inherit the series
    start year and roll over at new year.
    """
    out = []
    if not os.path.isfile(path):
        raise SystemExit('data.landfall_file not found: %s' % path)
    legacy = bool(_D.get('landfall_legacy', False))
    for ln in open(path, encoding='utf-8'):
        t = ln.split()
        if len(t) < 4 or t[0].startswith('#'):
            continue
        if len(t) >= 5 and re.match(r'^\d{1,2}\.\d{1,2}$', t[-4]) \
                and re.match(r'^\d{1,2}(:\d{2})?z?$', t[-3], re.I):
            legacy = True
        try:
            if legacy:
                lon = float(t[-1]); lat = float(t[-2])
                mo, dy = (int(v) for v in t[-4].split('.'))
                hm = t[-3].lower().rstrip('z')
                hh, _, mi = hm.partition(':')
                hh = int(hh); mi = int(mi) if mi else 0
                name = ' '.join(t[:-4])
                yr = S.t0.year
                if (mo, dy) < (S.t0.month, S.t0.day):
                    yr += 1
                when = datetime(yr, mo, dy, hh, mi)
            else:
                when = parse_fix_time(t[-3])
                lon = float(t[-2]); lat = float(t[-1])
                name = ' '.join(t[:-3])
        except (ValueError, IndexError):
            raise SystemExit('bad landfall line: %r' % ln.rstrip())
        out.append(dict(name=name, when=when, lat=lat, lon=lon))
    return out

def _align_lon(lon, ref):
    """put a place's longitude into the same 0..360 branch the track uses, so a
    dateline-crossing storm measures distances (and plots) correctly"""
    best, bd = lon, None
    for k in (-1, 0, 1, 2):
        cand = lon + 360.0 * k
        d = abs(cand - ref)
        if bd is None or d < bd:
            best, bd = cand, d
    return best

def min_dist_hours(lon, lat):
    lon = _align_lon(lon, float(np.mean(S.lon)))
    hs = np.arange(0.0, S.duration_h, 0.05)
    lo = np.interp(hs, S.hours, S.lon); la = np.interp(hs, S.hours, S.lat)
    d = np.hypot((la - lat) * 111.0, (lo - lon) * 111.0 * np.cos(np.radians(lat)))
    return float(hs[int(np.argmin(d))]), float(d.min())

def _build():
    # A reused interpreter may load another storm; cached samples are storm-specific.
    sample.cache_clear()
    trail_point.cache_clear()
    """materialise every storm-specific table once the config is bound"""
    global S, KEY, DAMAGE, LANDFALLS, _CL, CLOUD_FILE, CLOUD_STEP_EVERY
    global CLOUD_H0, CLOUD_STEP, CLOUD_F0, CLOUD_F1, CLOUD_G0, CLOUD_G1
    global CLOUD_HA, CLOUD_HB, CLOUD_HEND
    S = Series()
    build_phases()          # KEY needs the phase map, so build it first
    KEY = build_key()
    _CL = CFG.get('cloud', {}) or {}
    CLOUD_FILE = _CL.get('file', '')
    CLOUD_STEP_EVERY = int(_CL.get('extract_every', 4))
    CLOUD_H0 = float(_CL.get('h0', 0.0))
    CLOUD_STEP = float(_CL.get('step_h', 2.5 / 60.0))
    c1 = _CL.get('segment1', [0, 0]); c2 = _CL.get('segment2', [0, 0])
    CLOUD_F0, CLOUD_F1 = int(c1[0]), int(c1[1])
    CLOUD_G0, CLOUD_G1 = int(c2[0]), int(c2[1])
    CLOUD_HA = CLOUD_H0 + CLOUD_F1 * CLOUD_STEP
    CLOUD_HB = float(_CL.get('resume_h', 0.0))
    CLOUD_HEND = CLOUD_HB + (CLOUD_G1 - CLOUD_G0) * CLOUD_STEP
    # ---- Num.txt / hypo.txt (optional, sit beside the track files) ----
    _num = os.path.join(SRC, 'Num.txt')
    if os.path.isfile(_num):
        vals = [l.rstrip('\n').strip() for l in open(_num, encoding='utf-8')]
        vals = ['' if v.lower() in ('-', 'n/a', 'none', 'null') else v for v in vals]
        while vals and vals[-1] == '':
            vals.pop()
        vals += [''] * (3 - len(vals))
        S.ids = dict(db=vals[0], dep=vals[1], named=vals[2])
        if vals[2]:
            try:
                S.named_t = parse_fix_time(vals[2])
            except ValueError:
                S.named_t = None
        print('  numbers: invest %s / depression %s%s'
              % (S.ids['db'] or '-', S.ids['dep'] or '-',
                 ' / named %s' % S.named_t.strftime('%m-%d %HZ') if getattr(S, 'named_t', None) else ''))
    _hyp = os.path.join(SRC, 'hypo.txt')
    if os.path.isfile(_hyp):
        v = open(_hyp, encoding='utf-8').read().strip().lower()
        _S['hypothetical'] = v in ('true', '1', 'yes', 'y')
        print('  hypothetical: %s (from hypo.txt)' % _S['hypothetical'])

    # damage: data.damage in the config, or damage.txt beside the track files
    _dmg = _D.get('damage')
    if not _dmg:
        _dp = os.path.join(SRC, 'damage.txt')
        if os.path.isfile(_dp):
            _dmg = []
            for _i, _ln in enumerate(open(_dp, encoding='utf-8')):
                if _ln.strip().startswith('#'):
                    continue
                # an optional '|group' tail lets neighbouring places collapse into
                # one pop-up; '|' keeps it unambiguous for names with spaces
                _grp = None
                if '|' in _ln:
                    _ln, _grp = _ln.split('|', 1)
                    _grp = _grp.strip() or None
                _t = _ln.split()
                if len(_t) < 5 or _t[0].startswith('#'):
                    continue
                try:
                    _lon = float(_t[0]); _lat = float(_t[1])
                except ValueError:
                    continue
                _lraw = _t[-1].strip()
                _dead = re.sub(r'[^0-9]', '', _t[-2]) or '0'
                _loss = 0.0
                if _lraw not in ('/', '-', ''):
                    try:
                        _loss = float(_lraw.replace(',', ''))
                    except ValueError:
                        _loss = 0.0
                _u = str(_D.get('damage_loss_unit', 'yuan')).lower()
                _yi = _loss * {'yuan': 1e-8, 'wan': 1e-4, 'yi': 1.0}.get(_u, 1e-8)
                _nm = ' '.join(_t[2:-2])
                _dmg.append(dict(cn=_nm, en=_nm, lon=_lon, lat=_lat,
                                 dead=int(_dead), lost=0,
                                 loss=('%g' % _yi) if _yi else '0',
                                 group=_grp))
            if _dmg:
                print('  damage from damage.txt: %d places' % len(_dmg))

    raw = [dict(cn=e.get('cn', ''), en=e.get('en', ''),
                lon=float(e['lon']), lat=float(e['lat']),
                dead=int(e.get('dead', 0)), lost=int(e.get('lost', 0)),
                loss=str(e.get('loss', '0')),
                loss_text=e.get('loss_text'),
                priority=int(e.get('priority', 0)),
                group=e.get('group'))
           for e in (_dmg or [])]
    # nearby places sharing a `group` collapse into ONE pop-up: the totals are
    # summed and the event sits on its hardest-hit member (a centroid could land
    # in the sea, and playing them one after another swamps the frame)
    DAMAGE, gmap = [], {}
    for e in raw:
        g = e['group']
        if not g:
            DAMAGE.append(e)
            continue
        if g not in gmap:
            e['_members'] = [e]
            e['_anchor'] = e['dead'] + e['lost']
            e['_name'] = e['cn']
            gmap[g] = e
            DAMAGE.append(e)
            continue
        m = gmap[g]
        m['_members'].append(e)
        m['dead'] += e['dead']
        m['lost'] += e['lost']
        try:
            m['loss'] = '%g' % (float(m['loss'] or 0) + float(e['loss'] or 0))
        except ValueError:
            pass
        m['priority'] = max(m['priority'], e['priority'])
        if (e['dead'] + e['lost']) > m['_anchor']:
            m['_anchor'] = e['dead'] + e['lost']
            m['lon'], m['lat'] = e['lon'], e['lat']
    global WIND_AXIS
    WIND_AXIS = float(_c('view.wind_axis_max', 0) or 0) or \
        max(185.0, float(np.ceil(float(S.iwind.max()) / 10.0) * 10.0))
    if WIND_AXIS > 185.0:
        print('  wind axis extended to %.0f kt (peak %.0f kt)' % (WIND_AXIS, S.iwind.max()))
    global ACE_MAX
    ACE_MAX = float(_c('view.ace_max', 0) or 0) or max(40.0, np.ceil(S.ace_total / 10.0) * 10.0)
    if ACE_MAX > 40.0:
        print('  ACE bar scaled to %.0f (total %.2f)' % (ACE_MAX, S.ace_total))
    for m in DAMAGE:
        mem = m.pop('_members', None)
        if mem and len(mem) > 1:
            print('  merged %-12s <- %-28s %d dead+missing, %s CNY' %
                  (m['group'], ' + '.join(x['cn'] for x in mem),
                   m['dead'] + m['lost'], m['loss']))
            m['cn'] = m['group']
        m.pop('_anchor', None)
    POPUP_DUR = float(_c('damage.popup_duration', 2.9) or 2.9)
    # a short pop-up should not fly as high as a long one
    POPUP_APEX = 147.0 * min(1.0, POPUP_DUR / 1.6)
    for e in DAMAGE:
        e['lon'] = _align_lon(e['lon'], float(np.mean(S.lon)))
        e['h'], e['km'] = min_dist_hours(e['lon'], e['lat'])
        # rule 1: start half a popup early, so the animation is half-done at the
        # moment of closest approach
        e['t'] = t_of_hours(e['h']) - POPUP_DUR / 2.0
    gap = float(_c('damage.min_gap', 0.0) or 0.0)
    DAMAGE.sort(key=lambda e: (int(e.get('priority', 0)), e['t']))
    # neighbour places (Tokyo / Saitama / Kanagawa ...) are only ~1 deg apart, so
    # consecutive numbers are fanned out a little around their own location
    spread = float(_c('damage.spread', 0.0) or 0.0)
    fan = [(0, 0), (-1, 0), (1, 0), (0, -1), (-1, -1), (1, -1)]
    for i, e in enumerate(DAMAGE):
        fx, fy = fan[i % len(fan)]
        e['dx'] = fx * spread
        e['dy'] = fy * spread * 0.62
    prev = -1e9
    for e in DAMAGE:
        e['t'] = max(e['t'], prev + gap)
        prev = e['t']
    LANDFALLS = []
    spec = landfall_file()
    if spec:
        # data file carries time + position; the config carries presentation,
        # keyed by the same short name (case-insensitive)
        pres = _D.get('landfalls') or {}
        if isinstance(pres, list):        # tolerate the inline list form
            pres = {e.get('name', e.get('place', '')): e for e in pres}
        low = {str(k).lower(): v for k, v in pres.items()}
        for rec in _parse_landfall_file(os.path.join(SRC, spec)):
            st = dict(low.get(rec['name'].lower(), {}))
            h = (rec['when'] - S.t0).total_seconds() / 3600.0
            LANDFALLS.append(dict(
                h=h, lon=rec['lon'], lat=rec['lat'],
                fx=st.get('fx'), landed=st.get('landed'),
                en=st.get('en', 'LANDFALL'), cn=st.get('cn', '登陆'),
                place=st.get('place', rec['name']),
                stamp=st.get('stamp', rec['when'].strftime('%m-%d %HZ')),
                cat=st.get('cat', ''), size=int(st.get('size', 108)),
                off_y=int(st.get('off_y', 30)),
                simple_dx=int(st.get('simple_dx', 152)),
                simple_dy=int(st.get('simple_dy', 0)),
                color=tuple(st.get('color', [255, 196, 120]))))
    else:
        LANDFALLS = [dict(h=float(lf['h']), lon=float(lf['lon']), lat=float(lf['lat']),
                          fx=lf.get('fx'), landed=lf.get('landed'),
                          en=lf.get('en', 'LANDFALL'), cn=lf.get('cn', '登陆'),
                          place=lf.get('place', ''), stamp=lf.get('stamp', ''),
                          cat=lf.get('cat', ''), size=int(lf.get('size', 108)),
                          off_y=int(lf.get('off_y', 30)),
                          simple_dx=int(lf.get('simple_dx', 152)),
                          simple_dy=int(lf.get('simple_dy', 0)),
                          color=tuple(lf.get('color', [255, 196, 120])))
                     for lf in ((_D.get('landfalls') or {}).values()
                                if isinstance(_D.get('landfalls'), dict)
                                else (_D.get('landfalls') or []))]
    # impact clip, marker and sound follow the intensity AT LANDFALL: anything
    # above 155 kt switches to the super-cyclone set.  A config may still pin
    # fx / landed explicitly.
    LF_SET = {'C5++': ('landing6', 'landed5'), 'C5+': ('landing6', 'landed5'),
              'C5': ('landing5', 'landed5'), 'C4': ('landing4', 'landed4'),
              'C3': ('landing3', 'landed3'), 'C2': ('landing2', 'landed2'),
              'C1': ('landing', 'landed'), 'TS': ('landingS', 'landedS'),
              'TD': ('landingTD', 'landedD')}
    for lf in LANDFALLS:
        lf['lon'] = _align_lon(lf['lon'], float(np.mean(S.lon)))
        lf['simple_anchor'] = 'lm' if lf['simple_dx'] > 0 else 'rm'
        wv = float(S.WF(lf['h']))
        lf['wind'] = wv
        ph = _phase_at(lf['h'])
        lvl = level_of(wv, ph)
        if lvl not in LF_SET:
            lvl = 'TS' if wv >= 34.0 else 'TD'
        lf['lvl'] = lvl
        # A landfall counts as an event down to a tropical depression, which has
        # its own impact clip, marker and sound.  A remnant vortex or an
        # extratropical system coming ashore does NOT: it is not a landfall, and
        # before this it fell through to the C1 art and a 20 kt remnant vortex
        # landed like a category-1 typhoon (and sounded like one).
        lf['no_fx'] = (ph != 'TC')
        if not lf.get('fx'):
            lf['fx'] = None if lf['no_fx'] else LF_SET[lvl][0]
        if not lf.get('landed'):
            lf['landed'] = None if lf['no_fx'] else LF_SET[lvl][1]
        lf['scale'] = landfall_scale(wv)
    for lf in LANDFALLS:
        if lf['scale'] > 1.0:
            print('  super landfall %-12s %5.0f kt -> C6 set, scale %.0f%%'
                  % (lf['place'], lf['wind'], lf['scale'] * 100))
    # the time warp needs the landfalls, so build it here and not earlier
    _build_warp()
    # rule 7: stretch the panorama so every card column gets its CARD_CYCLE
    _per = cards_per_column()
    _cols = max((len(_D.get('peaks') or []) + _per - 1) // _per,
                (len(LANDFALLS) + _per - 1) // _per, 1)
    set_hold(_cols * CARD_CYCLE + 0.9)
    if _cols > 1:
        print('  ending: %d card columns, panorama held %.1f s' % (_cols, NTIME['hold']))
    # rapid intensification: two adjacent fixes jumping >= 2 SSHWS bands
    # phase boundaries: midpoint between the last fix of one phase and the
    # first fix of the next - derived, so any decomposition works
    global RI_EVENTS, PHASE_BOUNDS, RI_FX_SKIP, RI_BLEND_FRAC
    RI_FX_SKIP = tuple(_D.get('ri_no_fx_bands', ['C1', 'C5+', 'C5++']))
    RI_BLEND_FRAC = float(_D.get('ri_blend_frac', 0.45) or 0.45)
    RI_EVENTS = []
    if _D.get('rapid_intensification', True):
        # Rule 11.  The old test (two SSHWS bands inside one fix gap) misses a
        # sustained burst that gains a band at a time.  The current test slides
        # over the whole smoothed curve and marks a window when either:
        #   * 6 h gains >= 20 kt, or
        #   * 24 h gains >= 60 kt with no 6 h sub-window gaining < 10 kt
        # Overlapping/contiguous windows merge into ONE event; the ERI burst is
        # centred on the event's midpoint.
        step = float(_D.get('ri_step_h', 0) or 1.0)
        hs = np.arange(0.0, S.duration_h + 1e-6, step)
        spans = []
        for h in hs:
            if h + 6.0 <= S.duration_h + 1e-6:
                if float(S.WF(h + 6.0)) - float(S.WF(h)) >= 20.0:
                    spans.append((float(h), float(h) + 6.0))
            if h + 24.0 <= S.duration_h + 1e-6:
                if float(S.WF(h + 24.0)) - float(S.WF(h)) >= 60.0:
                    if all(float(S.WF(h + 6 * (k + 1))) - float(S.WF(h + 6 * k)) >= 10.0
                           for k in range(4)):
                        spans.append((float(h), float(h) + 24.0))
        spans.sort()
        merged = []
        for a, b in spans:
            if merged and a <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for h0, h1 in merged:
            b0 = band_index(float(S.WF(h0)))
            b1 = band_index(float(S.WF(h1)))
            # Suppress the burst only for a hop WITHIN the top bands.  Judging it
            # by the event's END band swallowed real bursts: a 31 h climb from TD
            # to C5+ ends in C5+ and was silently muted (Dianmu's first peak).
            # The original rule meant "a C4 -> C5+ / C5 -> C5++ hop is not news",
            # so key it on where the event STARTS.
            top = set(RI_FX_SKIP) | {'C4', 'C5'}
            RI_EVENTS.append((h0, h1, BANDS[b0][0], BANDS[b1][0],
                              BANDS[b0][0] not in top))
    for e in RI_EVENTS:
        print('  RI  h=%6.1f -> %6.1f  (%4.1f h)  %-4s -> %-4s   %s'
              % (e[0], e[1], e[1] - e[0], e[2], e[3],
                 'blend + ERI burst' if e[4] else 'blend only (no ERI burst)'))

# ----------------------------------------------------------------------------
# icon sprites (screen blended, optional tint)
# ----------------------------------------------------------------------------
_ic = {}
ICON_H = 236

# Copied from season/pass1: all impact sizes are relative to the icon glyph.
LFX_K = 2.966 * 1.2
LFX_FADE_KT = 170.0
LFX_FADE_PER_KT = 0.005


def landfall_impact_size(wind):
    """Season's exact linear-size rule; persistent Landed markers are unchanged."""
    wind = min(wind, 200.0)
    fade = max(0.0, 1.0 - LFX_FADE_PER_KT * (LFX_FADE_KT - wind))
    return max(4, int(round(LFX_K * ICON_H * landfall_scale(wind) * fade)))
def icon_sprite(lvl, phase, wind=None, hemisphere='N'):
    """square canvas so sprites of different levels can be cross-faded"""
    key = (lvl, phase, hemisphere)
    if key in _ic:
        return _ic[key]
    d = os.path.join(ICOND, ('S_' if hemisphere == 'S' else '') + lvl.replace('+', 'p'))
    p = os.path.join(d, '%04d.png' % (phase % N_ICON))
    im = Image.open(p).convert('RGB')
    r = ICON_H / float(im.height)
    im = im.resize((max(1, int(im.width * r)), ICON_H), Image.LANCZOS)
    canvas = Image.new('RGB', (ICON_H, ICON_H), (0, 0, 0))
    canvas.paste(im, ((ICON_H - im.width) // 2, 0))
    if len(_ic) > 800:
        _ic.clear()
    _ic[key] = canvas
    return canvas

ICON_FADE_KT = 3.0        # spec: fade spans +/- this around a band boundary

def icon_pair(wind, ph):
    """(icon on screen, incoming icon, the incoming one's opacity).

    The crossfade is linear in INTENSITY, not in time.  Around a band boundary
    `b` the incoming icon rises from 0 at `b - ICON_FADE_KT` to 1 at
    `b + ICON_FADE_KT` - so the C5 boundary at 137 kt starts blending at 134 and
    finishes at 140.  Because the opacity is a function of the wind alone, a
    weakening storm plays exactly the same fade in reverse, and a storm sitting
    on a boundary *shows* the blend, which is itself the information that it is
    on the boundary.
    """
    if ph != 'TC' or not np.isfinite(wind):
        return level_of(wind, ph), None, 0.0
    names = [b[0] for b in BANDS]
    starts = [b[1] for b in BANDS[1:]]
    b = min(starts, key=lambda x: abs(x - wind))
    m = ICON_FADE_KT
    if abs(wind - b) <= m:
        j = names.index(BANDS[[q[1] for q in BANDS].index(b)][0])
        u = (wind - (b - m)) / (2.0 * m)
        return names[j - 1], names[j], min(1.0, max(0.0, u))
    return level_of(wind, 'TC'), None, 0.0

_tint_cache = {}


def _sample_icon_colour(images):
    """Median bright chroma from rotating art; exclude white text and black."""
    pixels = []
    for im in images:
        rgb = np.asarray(im, dtype=np.float32)
        value = rgb.max(axis=2)
        saturation = (value - rgb.min(axis=2)) / np.maximum(value, 1.0)
        selected = (saturation > 0.2) & (value >= 32.0)
        if selected.any():
            cutoff = np.percentile(value[selected], 75)
            pixels.append(rgb[selected & (value >= cutoff)])
    if not pixels:
        raise ValueError('TC reference icon has no usable coloured pixels')
    return np.median(np.concatenate(pixels), axis=0).astype(np.float32)


@lru_cache(maxsize=4)
def _tc_icon_palette(icon_directory):
    """Sample actual TC sprites once per asset cache, including rendered tints."""
    palette = {}
    for lvl in ('TD', 'TS', 'C1', 'C2', 'C3', 'C4', 'C5', 'C5+', 'C5++', 'blue'):
        art = 'C5++' if lvl == 'blue' else lvl
        images = []
        for nf in (0, 25, 50, 75):
            im = icon_sprite(art, nf)
            if lvl in ('C5+', 'C5++', 'blue'):
                wind = {'C5+': 160.0, 'C5++': 170.0, 'blue': 185.0}[lvl]
                q = tuple(int(v // 8) * 8 for v in theme_col(wind, art))
                im = tinted(('ex-reference', art, nf, q), im, q)
            images.append(im)
        palette[lvl] = _sample_icon_colour(images)
    return palette


@lru_cache(maxsize=4)
def _ace_ex_endpoint(asset_directory):
    """Read the actual ACE fill's right-edge colour for the EX 200 kt node."""
    path = os.path.join(asset_directory, 'gui', 'ace', 'ace_color_1000.png')
    with Image.open(path) as image:
        rgb = np.asarray(image.convert('RGB'), dtype=np.float32)
    return np.median(rgb[:, -1, :], axis=0)


def ex_icon_colour(wind):
    """Linear RGB interpolation through TC band midpoints, without plateaus."""
    if wind > 200.0:
        return np.asarray(palette_colour(wind, HIGHWIND_BODY), dtype=np.float32)
    palette = _tc_icon_palette(ICOND)
    # C5++ has an open-ended category range; use its authored high-wind
    # purple/blue/ACE-endpoint anchors rather than the sentinel upper bound (999).
    nodes = [((lo + hi) / 2.0, palette[lvl]) for lvl, lo, hi in BANDS[:-1]]
    nodes += [(170.0, palette['C5++']), (185.0, palette['blue']),
              (200.0, _ace_ex_endpoint(ASSETS))]
    speeds = [speed for speed, _ in nodes]
    colours = np.asarray([colour for _, colour in nodes])
    return np.array([np.interp(wind, speeds, colours[:, channel])
                     for channel in range(3)], dtype=np.float32)



@lru_cache(maxsize=4)
def _ss_upgrade_colour(icon_directory):
    source = Image.open(os.path.join(icon_directory, 'SS', '0000.png')).convert('RGB')
    rgb = np.asarray(source, dtype=np.float32)
    value = rgb.max(axis=2)
    saturation = (value - rgb.min(axis=2)) / np.maximum(value, 1.0)
    coloured = (saturation > 0.65) & (value > 64) & (rgb[..., 1] >= rgb[..., 0])
    colour = np.median(rgb[coloured], axis=0) if coloured.any() else _sample_icon_colour([source])
    return colour / max(1.0, float(colour.max()))


def upgrade_sprite(im, h):
    """SS upgrades borrow SS artwork's chroma; retain white cores and luminance."""
    if _phase_at(h) in ('SD', 'SS'):
        rgb = np.asarray(im, dtype=np.float32)
        value = rgb.max(axis=2)
        saturation = (value - rgb.min(axis=2)) / np.maximum(value, 1.0)
        mask = np.clip((saturation - 0.04) / 0.26, 0.0, 1.0)
        mask = mask * mask * (3.0 - 2.0 * mask)
        target = value[..., None] * _ss_upgrade_colour(ICOND)
        rgb += (target - rgb) * mask[..., None]
        im = Image.fromarray(np.rint(np.clip(rgb, 0, 255)).astype(np.uint8))
    if sample(h)[1] < 0:
        im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return im


def ex_icon_tinted(im, wind):
    """Recolour EX chroma continuously, preserving its white core and lettering."""
    if not np.isfinite(wind) or wind <= 30.0:
        return im
    base = np.asarray(im, dtype=np.float32)
    value = base.max(axis=2)
    saturation = (value - base.min(axis=2)) / np.maximum(value, 1.0)
    # Work directly in RGB: HSV's integer hue and TC's 8-value cache bins
    # produce visible steps during a slow wind ramp.
    # Keep the authored brightness. A per-frame median changes abruptly as
    # the arms rotate; its exposure boost clipped orange into flashing yellow.
    target = value[..., None] * (ex_icon_colour(wind) / 255.0)
    u = min(1.0, (wind - 30.0) / 7.0)
    u = u * u * (3.0 - 2.0 * u)
    # Feather the chroma mask so antialiased halo pixels do not form a hard
    # coloured contour. Exactly neutral pixels (core, letters, black) stay put.
    mask = np.clip((saturation - 0.04) / 0.26, 0.0, 1.0)
    mask = mask * mask * (3.0 - 2.0 * mask)
    mix = mask[..., None] * u
    out = base * (1.0 - mix) + target * mix
    return Image.fromarray(np.rint(out).astype(np.uint8))


def _grey_lightning_layer(source, baseline):
    """Separate dark blue discharge filaments from the neutral C7 artwork."""
    value = source.min(axis=2)
    ridge = np.maximum(0.0, cv2.GaussianBlur(value, (0, 0), 1.6) - value)
    neutral_edges = np.maximum(0.0, cv2.GaussianBlur(baseline, (0, 0), 1.6) - baseline)
    chroma = np.clip((source[..., 2] - source[..., 0] - 5.0) / 18.0, 0.0, 1.0)
    h, w = value.shape
    yy, xx = np.mgrid[:h, :w]
    radius = np.sqrt((xx - (w - 1) / 2.0)**2 + (yy - (h - 1) / 2.0)**2) / h
    # Protect EX lettering and exclude the neutral source's number and rings.
    radial = np.clip((radius - 0.16) / 0.035, 0.0, 1.0)
    ridge = np.maximum(0.0, ridge - neutral_edges - 3.0) * chroma * radial
    core = np.clip(ridge * 12.0, 0.0, 255.0)
    hot = np.clip((ridge - 15.0) * 20.0, 0.0, 255.0)
    glow = cv2.GaussianBlur(core, (0, 0), 1.1)
    rgb = np.stack([core*.45 + hot*.55 + glow*.08,
                    core*.65 + hot*.35 + glow*.15, core + glow*.3], axis=2)
    # Blur can bleed into the protected centre, so mask the final layer too.
    rgb *= radial[..., None]
    return Image.fromarray(np.rint(np.clip(rgb, 0.0, 255.0)).astype(np.uint8))


def extract_ex_lightning():
    """Build a disposable, shared lightning-only cache from uncoloured C7 art."""
    directory = os.path.join(FXD, 'ex_lightning_gray_v1')
    complete = os.path.join(directory, 'complete.txt')
    if os.path.isfile(complete) and all(os.path.isfile(os.path.join(directory, '%04d.png' % i))
                                          for i in range(N_ICON)):
        return
    os.makedirs(directory, exist_ok=True)
    source = os.path.join(ASSETS, 'mainicon', 'tc_sshws', 'N-TC-C6(7).mp4')
    metadata = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
        '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'json', source]))
    width, height = (int(metadata['streams'][0][k]) for k in ('width', 'height'))
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', source, '-vf',
        r'select=not(mod(n\,3))', '-fps_mode', 'passthrough', '-f', 'rawvideo',
        '-pix_fmt', 'rgb24', '-'])
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 3)
    if len(frames) != N_ICON:
        raise ValueError('Unexpected C7 frame count: %d' % len(frames))
    turns = int(ICON_TURNS)
    period = N_ICON // turns
    # At each rotation angle, the brightest neutral pixel estimates the body
    # before the dark discharge. It removes static arm/ring edges from detection.
    baseline = frames.reshape(turns, period, height, width, 3).min(axis=4).max(axis=0)
    for i, frame in enumerate(frames):
        layer = _grey_lightning_layer(frame.astype(np.float32),
                                      baseline[i % period].astype(np.float32))
        layer = layer.resize((ICON_H, ICON_H), Image.Resampling.LANCZOS)
        layer.save(os.path.join(directory, '%04d.png' % i))
    with open(complete, 'w', encoding='utf-8') as marker:
        marker.write('gray C7, six-turn neutral baseline, native-resolution discharge extraction\n')
    print('fx EX lightning', N_ICON)


def ex_icon_with_lightning(im, nf, wind):
    if not np.isfinite(wind) or wind < 100.0:
        return im
    path = os.path.join(FXD, 'ex_lightning_gray_v1', '%04d.png' % (nf % N_ICON))
    return ImageChops.screen(im, _asset_frames.get(path, size=im.size))


@lru_cache(maxsize=8)
def _tc_digit_mask(icon_directory, size):
    """Stable mask from the original magenta 5, independent of lightning frames."""
    source = icon_sprite('C5++', 0).resize(size, Image.Resampling.LANCZOS)
    rgb = np.asarray(source, dtype=np.float32)
    value = rgb.max(axis=2)
    saturation = (value - rgb.min(axis=2)) / np.maximum(value, 1.0)
    h, w = value.shape
    yy, xx = np.mgrid[:h, :w]
    # The numeral occupies the centre; exclude the white eye, rings and bolts.
    region = ((xx >= w*.43) & (xx <= w*.57) &
              (yy >= h*.40) & (yy <= h*.59))
    mask = np.clip((saturation - .18) / .32, 0.0, 1.0)
    mask *= np.clip((245.0 - value) / 30.0, 0.0, 1.0)
    return mask * region


def tc_digit_tinted(im, wind):
    """Darken only the TC numeral to black-red over 185..200 kt."""
    if not np.isfinite(wind) or wind <= 185.0:
        return im
    u = float(np.clip((wind - 185.0) / 15.0, 0.0, 1.0))
    u = u * u * (3.0 - 2.0 * u)
    mask = _tc_digit_mask(ICOND, im.size)[..., None] * u
    rgb = np.asarray(im, dtype=np.float32)
    out = rgb * (1.0 - mask) + np.array([30.0, 3.0, 9.0]) * mask
    return Image.fromarray(np.rint(out).astype(np.uint8))


def single_badge_colours(wind, lvl, colour):
    if wind > 185.0 and lvl == 'C5++':
        return theme_col(wind, lvl), _lerp_rgb((255, 255, 255), (30, 3, 9), _ramp(wind, 185.0, 200.0))
    return colour, _lerp_rgb((8, 10, 16), (255, 255, 255), _ramp(wind, 176.0, 182.0))


def single_card_colour(wind, lvl):
    return theme_col(wind, lvl)


def single_highwind_text(wind, start, end=(198, 232, 255)):
    return _lerp_rgb(start, end, _ramp(wind, 185.0, 200.0))


@lru_cache(maxsize=8)
def _banner_digit_mask(reference_path, size):
    with Image.open(reference_path) as reference:
        rgb = np.asarray(reference.convert('RGB').resize(size, Image.Resampling.LANCZOS), dtype=np.float32)
    value = rgb.max(axis=2)
    saturation = (value-rgb.min(axis=2)) / np.maximum(value, 1.0)
    h, w = value.shape
    yy, xx = np.mgrid[:h, :w]
    region = ((xx >= w*.090) & (xx <= w*.117) &
              (yy >= h*.16) & (yy <= h*.83))
    return (np.clip((saturation-.18)/.32, 0.0, 1.0) *
            np.clip((245.0-value)/30.0, 0.0, 1.0) * region)


def banner_digit_tinted(im, reference_path, wind):
    if not np.isfinite(wind) or wind <= 185.0:
        return im
    u = float(np.clip((wind-185.0)/15.0, 0.0, 1.0))
    u = u*u*(3.0-2.0*u)
    mask = _banner_digit_mask(reference_path, im.size)[..., None]*u
    out = np.asarray(im, dtype=np.float32)*(1.0-mask) + np.array([30.0, 3.0, 9.0])*mask
    return Image.fromarray(np.rint(out).astype(np.uint8))


def icon_tint_colour(wind, lvl):
    """Shared icon/impact tint rule; lower-category artwork keeps its own hue."""
    if lvl not in ('C5+', 'C5++'):
        return None
    return theme_col(wind, lvl) if wind > 200 else tuple(int(v // 8) * 8 for v in theme_col(wind, lvl))
def glow_strength(wind, lvl):
    """spec: the lower bands carry NO halo, C5++ gets a weak one, and past
    180 kt it grows strong.  Applied as an additive blurred copy, so it is a
    deliberate effect rather than a side effect of the hue replace."""
    if lvl != 'C5++':
        return 0.0
    return 0.25 + 0.55 * _ramp(wind, 170.0, 184.0)

_glow_cache = {}
def with_glow(im, s, colour=None, spread=1.0):
    """additive halo that spares the bright core.

    A plain add blows the number out past 180 kt, so the blurred copy is only
    added where the base pixel is still dark - the halo grows outward while the
    numeral and the eye stay crisp.
    """
    if s <= 0.01:
        return im
    key = (id(im), round(s, 2), colour, round(spread, 3))
    v = _glow_cache.get(key)
    if v is None:
        b = im.filter(ImageFilter.GaussianBlur(18 * spread))
        base = np.asarray(im).astype(np.float32)
        g = np.asarray(b).astype(np.float32) * s
        if colour is not None:
            g = g.max(axis=2)[..., None] * (np.array(colour, dtype=np.float32) / 255.0)
            # Keep the eye and its dark 5 clear of the coloured outer halo.
            yy, xx = np.mgrid[:im.height, :im.width]
            radial = np.hypot(xx - im.width / 2, yy - im.height / 2) / im.height
            g *= np.clip((radial - .16) / .12, 0, 1)[..., None]
        head = np.clip((200.0 - base.max(axis=2)) / 200.0, 0.0, 1.0)[..., None]
        v = Image.fromarray(np.clip(base + g * head, 0, 255).astype(np.uint8))
        if len(_glow_cache) > 400:
            _glow_cache.clear()
        _glow_cache[key] = v
    return v

def tinted(key, im, col):
    """hue-replace the coloured parts, keep the white core white -> real contrast"""
    v = _tint_cache.get(key)
    if v is None:
        rgb = np.asarray(im)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        sat = hsv[..., 1] / 255.0
        val = hsv[..., 2] / 255.0
        sel = sat > 0.28
        tc = np.array(col, dtype=np.float32) / 255.0
        mx = float(tc.max()); mn = float(tc.min())
        v_t = mx
        s_t = 0.0 if mx <= 0 else (mx - mn) / mx
        if sel.any():
            sv = float(np.median(val[sel])) or 1.0
            ss = float(np.median(sat[sel])) or 1.0
            hsv[..., 0][sel] = _hue_of(col)
            hsv[..., 1][sel] = np.clip(sat[sel] / max(ss, 0.15) * s_t * 255.0, 0, 255)
            hsv[..., 2][sel] = np.clip(val[sel] / max(sv, 0.15) * v_t * 255.0, 0, 255)
        out = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)
        v = Image.fromarray(out)
        if len(_tint_cache) > 400:
            _tint_cache.clear()
        _tint_cache[key] = v
    return v

def _hue_of(col):
    c = np.uint8([[[int(col[0]), int(col[1]), int(col[2])]]])
    return int(cv2.cvtColor(c, cv2.COLOR_RGB2HSV)[0, 0, 0])

def arm_angle(im, nb=72):
    """orientation of a two-armed spiral, in degrees over 0..180.

    The icons have 2-fold rotational symmetry, so the angle is taken modulo 180.
    A radial histogram of the bright pixels weighted by radius favours the arms
    over the bright but central eye.
    """
    g = np.asarray(im.convert('L').resize((64, 64), Image.BILINEAR), dtype=float)
    g = g - g.mean()
    if not np.isfinite(g).all() or g.max() <= 0:
        return 0.0
    yy, xx = np.mgrid[0:64, 0:64]
    dx, dy = xx - 31.5, yy - 31.5
    r = np.hypot(dx, dy)
    m = (g > g.std() * 0.5) & (r > 6.0)
    if m.sum() < 10:
        return 0.0
    th = np.arctan2(dy[m], dx[m])
    w = g[m] * r[m]
    hist, edges = np.histogram(np.mod(th, np.pi), bins=nb, range=(0.0, np.pi),
                               weights=w)
    k = int(np.argmax(hist))
    return float(np.degrees(0.5 * (edges[k] + edges[k + 1])))


def screen_paste(frame, sprite, cx, cy):
    w, h = sprite.size
    x0 = int(round(cx - w / 2.0)); y0 = int(round(cy - h / 2.0))
    box = (x0, y0, x0 + w, y0 + h)
    frame.paste(ImageChops.screen(frame.crop(box), sprite), box)

# ----------------------------------------------------------------------------
# cloud inset
# ----------------------------------------------------------------------------
def cloud_mask(size):
    r = size / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.sqrt((xx - r + 0.5) ** 2 + (yy - r + 0.5) ** 2) / r
    a = np.clip((1.0 - d) / 0.42, 0, 1)
    a = a * a * (3 - 2 * a)
    rng = np.random.default_rng(3)
    a *= 0.965 + 0.035 * rng.random((size, size)).astype(np.float32)
    return a

_CMASK = None
_NCLOUD = None
def cloud_overlay(frame_idx, alpha):
    global _CMASK, _NCLOUD
    size = CLOUD_R * 2
    if _CMASK is None:
        _CMASK = cloud_mask(size)
    if _NCLOUD is None:
        _NCLOUD = len(os.listdir(CLOUDD))
    fi = int(round(frame_idx / float(CLOUD_STEP_EVERY)))
    fi = max(0, min(_NCLOUD - 1, fi))
    g = Image.open(os.path.join(CLOUDD, '%04d.jpg' % fi)).convert('L')
    cx, cy = g.width // 2, g.height // 2
    half = 250                                   # drops the burned-in watermarks
    g = g.crop((cx - half, cy - half, cx + half, cy + half)).resize((size, size), Image.LANCZOS)
    v = np.asarray(g).astype(np.float32) / 255.0
    v = np.clip((v - 0.05) / 0.95, 0, 1) ** 1.02          # brighter, punchier clouds
    a = _CMASK * float(alpha) * 0.98
    rgb = np.dstack([v * 0.94, v * 0.97, v * 1.00]) * a[..., None]   # premultiplied
    out = np.dstack([np.clip(rgb * 255, 0, 255), np.zeros_like(a)]).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')

# ----------------------------------------------------------------------------
# renderer
# ----------------------------------------------------------------------------
class FrameCache:
    """Bound decoded RGB assets by pixel bytes; callers receive owned copies."""
    def __init__(self, limit=32 * 1024 * 1024):
        self.limit, self.bytes = limit, 0
        self.items = OrderedDict()

    def get(self, path, size=None, tint=None):
        key = (path, size, tint)
        if key in self.items:
            self.items.move_to_end(key)
            return self.items[key].copy()
        with Image.open(path) as source:
            im = source.convert('RGB')
        if tint is not None:
            # Reuse the existing colour algorithm without retaining a second cache.
            token = ('lazy-banner', key)
            im = tinted(token, im, tint)
            _tint_cache.pop(token, None)
        if size is not None:
            im = im.resize(size, Image.LANCZOS)
        cost = im.width * im.height * 3
        if cost <= self.limit:
            while self.items and self.bytes + cost > self.limit:
                _, old = self.items.popitem(last=False)
                self.bytes -= old.width * old.height * 3
            self.items[key] = im
            self.bytes += cost
        return im.copy()


_asset_frames = FrameCache()


class BannerFrames:
    """Keep paths, not 300 decoded frames, until a banner frame is displayed."""
    def __init__(self, paths):
        self.paths = paths
        self.tint = None
        self.digit_wind = 0.0

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, index):
        im = _asset_frames.get(self.paths[index], tint=self.tint)
        reference = self.paths[min(60, len(self.paths)-1)]
        return banner_digit_tinted(im, reference, self.digit_wind)


@lru_cache(maxsize=4096)
def trail_point(h):
    lo, la, wind, _, _, _ = sample(h)
    return lo, la, state_color(h, wind, state_weights(h, wind))


class R:
    def __init__(self):
        # Direct test/poster/render entry points also work before an assets pass.
        cmd_assets()
        self._pano = None
        self.hud = build_hud()
        # item 6: the four corner panels and the timeline each get their own
        # entrance.  Cropping the finished HUD is enough - no need to rebuild the
        # drawing code panel by panel.
        self.hud_parts = []
        rest = self.hud.copy()
        HUD_IN = [(P_TL, 'L', 0.10), (P_ACE, 'R', 0.28), (P_GR, 'L', 0.46),
                  (P_LG, 'L', 0.62), (P_TL2, 'D', 0.78)]
        for box, side, delay in HUD_IN:
            x, y, w, h = box
            self.hud_parts.append((box, self.hud.crop((x, y, x + w, y + h)),
                                   side, delay))
            rest.paste((0, 0, 0, 0), (x, y, x + w, y + h))
        self.hud_rest = rest
        self.f_hero = font(F_MONOB, 50)
        self.f_val  = font(F_MONOB, 38)
        self.f_badge = font(F_UIB, 24)
        self.f_note = font(F_MONOB, 39)
        # a storm given a tornado-style rating instead of an SSHWS category
        # (spec: Dujuan's 105 kt 2nd peak reads EF 3 / 强龙卷风).  Config only.
        self.ef_mode = bool(_S.get('ef_rating'))
        self.gx0, self.gy0 = P_GR[0] + 78, P_GR[1] + 62
        self.gx1, self.gy1 = P_GR[0] + P_GR[2] - 62, P_GR[1] + P_GR[3] - 50
        self.ace_bar = (P_ACE[0] + 18, P_ACE[1] + 96, 684, 44)
        self.banner = []
        g = Image.open(os.path.join(ASSETS, 'gui', 'ace', 'ace_color_1000.png')).convert('RGB')
        self.ace_ruler = g.resize((self.ace_bar[2], self.ace_bar[3]), Image.LANCZOS)
        self.fx = {k: sorted(os.path.join(FXD, k, f) for f in os.listdir(os.path.join(FXD, k)))
                   for k in os.listdir(FXD)}
        # the banner is held as decoded frames so it can be recoloured to the
        # peak intensity (super-cyclone rule 3).  Look the folder up BY NAME:
        # several `sumban_*` caches can survive in the build folder, and taking
        # the first match handed every storm the C2 banner.
        _want = 'sumban_' + banner_asset().replace('Summary-N-TC-', '').replace('.mp4', '')
        _key = _want if _want in self.fx else next(
            (k for k in sorted(self.fx) if k.startswith('sumban')), None)
        self.banner = BannerFrames(self.fx.get(_key, []) if _key else [])
        pk = _D.get('peaks') or []
        self.peak_wind = peak_wind()
        self.banner.digit_wind = self.peak_wind
        self.peak_lvl = level_of(self.peak_wind, 'TC') if pk else 'C5'
        if (self.banner and self.peak_wind > 155.0
                and str(_c('banner.tint', 'auto')).lower() != 'false'):
            # the banner takes the colour of the level the peak actually
            # reaches - a 160 kt peak is C5+, not the C5++ ramp
            col = theme_col(self.peak_wind, level_of(self.peak_wind, 'TC'))
            key = 'sumban%d' % (int(col[0]) << 16 | int(col[1]) << 8 | int(col[2]))
            self.banner.tint = tuple(col)
            print('  banner tinted to peak colour %s (%.0f kt)' % (str(col), self.peak_wind))
        # camera path: (lon, lat, span_lon) for every frame, incl. the pull-back
        self.cam = []
        end_lo, end_la, _, _, _, _ = sample(S.duration_h)
        for i in range(NFRAMES):
            t = i / FPS
            if t < INTRO:
                h = 0.0
            elif t <= T_MAIN:
                h = hours_of_t(t)
            else:
                h = S.duration_h
            lo, la, w, p, a, ph = sample(h)
            h2 = min(S.duration_h, h + 0.9); h1 = max(0.0, h - 0.9)
            l2, a2 = np.interp(h2, S.hours, S.lon), np.interp(h2, S.hours, S.lat)
            l1, a1 = np.interp(h1, S.hours, S.lon), np.interp(h1, S.hours, S.lat)
            vx, vy = l2 - l1, a2 - a1
            n = math.hypot(vx, vy) or 1.0
            lead = 0.035 * SPAN0_LON / 2.0
            cl, ca, sp = lo + vx / n * lead, la + vy / n * lead, SPAN0_LON
            if t > T_MAIN:                       # pull back to the whole track
                u = min(1.0, (t - T_MAIN) / PULL)
                e = u * u * (3 - 2 * u)
                cl = (lo + vx / n * lead) * (1 - e) + PANO_C[0] * e
                ca = (la + vy / n * lead) * (1 - e) + PANO_C[1] * e
                sp = SPAN0_LON * (1 - e) + SPAN1_LON * e
            self.cam.append([cl, ca, sp])
        c = np.array(self.cam)
        k = np.hanning(101); k /= k.sum()            # ~1.7 s smoothing: no shake
        for j in range(3):
            c[:, j] = np.convolve(np.pad(c[:, j], 50, mode='edge'), k, 'valid')
        c[:, 2] = np.clip(c[:, 2], SPAN0_LON, SPAN1_LON)
        self.cam = c
        self.cloud_alpha = np.zeros(NFRAMES, dtype=np.float32)
        for i in range(NFRAMES):
            h = hours_of_t(i / FPS)
            self.cloud_alpha[i] = 1.0 if cloud_state(h)[1] else 0.0
        k2 = np.hanning(61); k2 /= k2.sum()
        self.cloud_alpha = np.convolve(np.pad(self.cloud_alpha, 30, mode='edge'), k2, 'valid')

    # ---- pieces -----------------------------------------------------------
    @staticmethod
    def dashed(d, pts, fill, width, dash=16, gap=11):
        on, acc = True, 0.0
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]; x1, y1 = pts[i]
            seg = math.hypot(x1 - x0, y1 - y0)
            if seg <= 0.01: continue
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

    def trail(self, ov, hours, proj):
        d = ImageDraw.Draw(ov)
        pts = []
        h = 0.0
        while h < hours - 1e-6:
            h = min(hours, h + 0.8)
            lo, la, _ = trail_point(h)
            pts.append((h, lo, la))
        lo, la, _ = trail_point(hours)
        pts.append((hours, lo, la))
        # colour every sample point continuously (gradual level changes)
        cols = []
        for (hh, _, _) in pts:
            cols.append(trail_point(hh)[2])
        xy = [proj(p[1], p[2]) for p in pts]
        if len(xy) > 1:
            # split into solid / dashed runs: the derived remnant-vortex phase
            # is dashed (never hard-code its hour window - it moves per storm)
            def is_rv(i):
                return _phase_at(pts[i][0]) == 'RV'
            runs = []
            cur = [0]
            for i in range(1, len(pts)):
                if is_rv(i) != is_rv(i - 1):
                    runs.append((is_rv(i - 1), cur + [i]))
                    cur = [i - 1]
                cur.append(i)
            runs.append((is_rv(len(pts) - 1), cur))
            for rv, idx in runs:
                if len(idx) < 2: continue
                rp = [xy[k] for k in idx]
                if rv:
                    self.dashed(d, rp, (0, 0, 0, 110), 12)
                    self.dashed(d, rp, cols[idx[-1]] + (255,), 6)
                else:
                    d.line(rp, fill=(0, 0, 0, 120), width=12, joint='curve')
                    for a, b in zip(idx[:-1], idx[1:]):
                        d.line([xy[a], xy[b]], fill=cols[b] + (255,), width=6)
        for i in range(len(S.hours)):
            if S.hours[i] > hours: break
            x, y = proj(S.lon[i], S.lat[i])
            w_i = float(np.interp(S.hours[i], S.ihours, S.iwind))
            c = state_color(S.hours[i], w_i, state_weights(S.hours[i], w_i))
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(10, 14, 22, 220),
                      outline=c + (255,), width=2)

    def glow(self, ov, cx, cy, wind, col, pulse, fade=1.0):
        d = ImageDraw.Draw(ov)
        if wind > 200:
            col = highwind_halo_colour(wind)
        r = 32 + (min(wind, WIND_AXIS) / WIND_AXIS) * 96.0
        for k, a in ((1.9, 10), (1.5, 14), (1.15, 18), (0.88, 22)):
            rr = r * k * (1.0 + 0.012 * pulse)
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col + (int(a * fade),))
        rr = r * 1.6 * (1.0 + 0.02 * pulse)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col + (int(78 * fade),), width=2)

    def icon_label(self, h, ph):
        """Keep the most recent available identity; missing fields add no label."""
        ids = getattr(S, 'ids', None) or {}
        invest, depression = ids.get('db', ''), ids.get('dep', '')
        label, colour = invest, (206, 214, 226)
        first_tc = next((float(S.hours[i]) for i, phase in enumerate(S.phase)
                         if phase == 'TC'), float('inf'))
        if h >= first_tc and depression:
            label, colour = depression, (140, 220, 140)
        named = getattr(S, 'named_t', None)
        if named is not None and h >= (named - S.t0).total_seconds() / 3600.0:
            name = _S.get('name_en', '')
            if name:
                label, colour = name, (255, 240, 210)
        return label, colour

    def badge_text(self, lvl, wind):
        """the CATEGORY badge text.  A hypothetical storm that has been given a
        tornado-style rating shows EF n and 强龙卷风 (spec: Dujuan EF3), italic."""
        txt = LABEL[lvl]
        if self.ef_mode and lvl in ('C3', 'C4', 'C5', 'C5+', 'C5++'):
            txt = txt.replace('CATEGORY', 'EF')
            txt = txt.replace('强台风', '强龙卷风')
        return txt

    def status(self, ov, t_data, lon, lat, wind, pres, lvl, col):
        d = ImageDraw.Draw(ov)
        c = col
        draw_text(d, (66, 78), t_data.strftime('%Y-%m-%d  %H:%M'), font=self.f_hero,
               fill=(255, 255, 255, 255))
        draw_text(d, (66, 174), '%s   %s' % (fmt_lat(lat), fmt_lon(lon)), font=self.f_val,
               fill=(186, 236, 255, 255))
        badge = self.badge_text(lvl, wind)
        fc = font(F_CJKB, 22)
        bw = mixed_w(d, badge, self.f_badge, fc, 0.0) + 28
        badge_bg, fg = single_badge_colours(wind, lvl, c)
        d.rounded_rectangle([66, 239, 66 + bw, 273], radius=4, fill=badge_bg + (245,))
        text_in_box(d, (79, 243, 66 + bw - 13, 269), badge,
                    self.f_badge, fc, fg + (255,), centre=True)
        # rule 16: the CMA grade + extended Beaufort force, same card styling,
        # directly under the CATEGORY badge.  The CMA scale itself is never
        # printed - only the force and the Chinese grade.
        ms = kt_to_cma_ms(wind)
        if lvl == 'EX':
            # item 1: the CMA tropical scale does not describe an extratropical
            # system, so it takes the same grey as the disturbance card and says
            # what it actually is
            bf, grade, gcol = '', '温带气旋', (206, 214, 226)
        else:
            grade, gcol = cma_grade_of(ms)
            bf = beaufort_of(ms)
        # spec: this reads EF / 强龙卷风 only while the storm holds SSHWS C3,
        # and reverts to normal once it drops to C2
        ef = self.ef_mode and lvl in ('C3', 'C4', 'C5', 'C5+', 'C5++')
        if ef:
            grade = '强龙卷风'          # spec: 强台风 -> 强龙卷风, italic
        # the overflow label is "17级以上" - it already carries 级, so a plain
        # number gets the suffix and the overflow label does not
        f_txt = bf if (not bf or '级' in bf) else bf + ' 级'
        txt = ('%s   %s' % (f_txt, grade)) if f_txt else grade
        fc2 = font(F_CJKM, 20)
        bw2 = mixed_w(d, txt, self.f_badge, fc2, 0.0) + 26
        d.rounded_rectangle([66, 279, 66 + bw2, 311], radius=4, fill=gcol + (240,))
        if ef:
            _italic_mixed(ov, (66 + 12, 283), txt, self.f_badge, fc2, (10, 12, 18, 255))
        else:
            text_in_box(d, (78, 283, 66 + bw2 - 12, 307), txt,
                        self.f_badge, fc2, (10, 12, 18, 255), centre=True)
        # belt and braces: never format a NaN into the badge
        ws = '--' if not np.isfinite(wind) else '%d' % round(wind)
        ps = '--' if not np.isfinite(pres) else '%d' % round(pres)
        draw_text(d, (66, 324), '%s kt  -  %s hPa' % (ws, ps),
               font=font(F_MONOB, 30), fill=(255, 255, 255, 255))

    def ace(self, ov, ace):
        d = ImageDraw.Draw(ov)
        bx, by, bw, bh = self.ace_bar
        draw_text(d, (bx, P_ACE[1] + 40), '%.2f' % ace, font=font(F_MONOB, 42),
               fill=(255, 255, 255, 255))
        frac = min(1.0, ace / ACE_MAX)
        d.rectangle([bx, by, bx + bw, by + bh], fill=(9, 13, 24, 255))   # opaque cover
        wpx = int(bw * frac)
        if wpx > 1:                       # reveal, never stretch
            ov.paste(self.ace_ruler.crop((0, 0, wpx, bh)), (bx, by))
        d.rectangle([bx, by, bx + bw, by + bh], outline=(255, 255, 255, 190))
        # rule 14: integer ticks along the trough, so the value can be read off
        step = 10.0 if ACE_MAX > 25 else 5.0
        v = step
        while v < ACE_MAX - 1e-6:
            x = bx + bw * (v / ACE_MAX)
            lit = v <= ace + 1e-6
            d.line([x, by + bh, x, by + bh + (9 if lit else 6)],
                   fill=(255, 255, 255, 230 if lit else 120), width=2)
            if int(v) % 20 == 0 or ACE_MAX <= 25:
                draw_text(d, (x, by + bh + 12), '%d' % v, font=font(F_MONO, 15),
                       fill=(226, 236, 250, 235 if lit else 150), anchor='ma')
            v += step

    def graph(self, ov, hours, wind, pres, ph):
        d = ImageDraw.Draw(ov)
        gx0, gy0, gx1, gy1 = self.gx0, self.gy0, self.gx1, self.gy1
        def wx(h): return gx0 + (h / S.duration_h) * (gx1 - gx0)
        def wy(v): return gy1 - (min(WIND_AXIS, v) / WIND_AXIS) * (gy1 - gy0)
        def py(v): return gy1 - ((v - 855.0) / (1015.0 - 855.0)) * (gy1 - gy0)
        n = max(2, int(hours * 2) + 1)
        hs = np.linspace(0, max(hours, 1e-3), n)
        ws = np.asarray(S.WF(hs), dtype=float)
        ps = np.asarray(S.PF(hs), dtype=float)
        for i in range(1, n):                      # pressure, dashed
            if i % 2: continue
            d.line([wx(hs[i - 1]), py(ps[i - 1]), wx(hs[i]), py(ps[i])],
                   fill=(226, 236, 250, 200), width=2)
        for i in range(1, n):                      # wind, NO fill, gradual colour
            wm = (ws[i] + ws[i - 1]) / 2.0
            hh = (hs[i] + hs[i - 1]) / 2.0
            d.line([wx(hs[i - 1]), wy(ws[i - 1]), wx(hs[i]), wy(ws[i])],
                   fill=state_color(hh, wm, state_weights(hh, wm)) + (255,), width=3)
        cxp, cyp = wx(hours), wy(wind)
        d.line([cxp, gy0 - 6, cxp, gy1], fill=(255, 255, 255, 70), width=1)
        d.ellipse([cxp - 5, cyp - 5, cxp + 5, cyp + 5],
                  fill=theme_col(wind, level_of(wind, ph)) + (255,),
                  outline=(255, 255, 255, 235), width=2)
        _placed = []                     # (x, label-y) of the labels drawn so far
        for i, pk in enumerate(_D.get('peaks') or []):
            hpk = float(pk['h'])
            txt = pk.get('graph', 'peak%d' % (i + 1))
            col = tuple(pk.get('color', [255, 210, 120]))
            if hours >= hpk:
                a = _ramp(hours, hpk, hpk + 2.0)
                x, y = wx(hpk), wy(float(S.WF(hpk)))
                d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=col + (int(230 * a),), width=2)
                # A peak near the top of the axis has no room for a label above
                # it, so drop below the marker; then push down until the label
                # clears every one already drawn.
                ly = y - 14.0
                if ly < gy0 + 16.0:
                    ly = y + 30.0
                thr = text_width(d, txt, font=font(F_MONO, 17)) + 14.0
                while any(abs(x - px) < thr and abs(ly - py) < 20 for px, py in _placed):
                    ly += 20.0
                ly = min(ly, gy1 - 4.0)
                _placed.append((x, ly))
                draw_text(d, (x, ly), txt, font=font(F_MONO, 17),
                       fill=col + (int(230 * a),), anchor='mb')
        draw_text(d, (gx1 - 2, gy0 - 20), 'WIND kt', font=font(F_MONO, 18),
               fill=(245, 249, 255, 245), anchor='ra')
        draw_text(d, (gx0 + 4, gy0 - 20), 'MSLP hPa', font=font(F_MONO, 18),
               fill=(226, 236, 250, 240), anchor='la')

    def timeline(self, ov, hours, col):
        d = ImageDraw.Draw(ov)
        tx0, tx1 = P_TL2[0] + 170, P_TL2[0] + P_TL2[2] - 36
        ty = P_TL2[1] + 32
        x = tx0 + (hours / S.duration_h) * (tx1 - tx0)
        d.line([x, ty - 16, x, ty + 13], fill=col + (235,), width=4)
        d.polygon([(x - 9, ty - 16), (x + 9, ty - 16), (x, ty - 6)], fill=col + (255,))
        draw_text(d, (tx0, ty - 42), 'T + %d h' % int(hours), font=font(F_MONO, 20),
               fill=(240, 246, 254, 248))
        draw_text(d, (tx1, ty - 42),
               (S.t0 + timedelta(hours=hours)).strftime('%b %d  -  %H:%MZ').upper(),
               font=font(F_MONO, 20), fill=(240, 246, 254, 248), anchor='ra')

    def damage(self, frame, t, proj):
        for e in DAMAGE:
            dt = t - e['t']
            if dt < -0.05 or dt > 3.4: continue
            x, y = proj(e['lon'], e['lat'])
            if not (-200 < x < W + 200 and -200 < y < H + 200): continue
            # sweep particles
            if 0.0 <= dt <= 0.9:
                i = min(len(self.fx['sweep']) - 1, int(dt * 10))
                sp = Image.open(self.fx['sweep'][i]).convert('RGBA').resize((300, 300), Image.LANCZOS)
                a = sp.getchannel('A').point(lambda v: int(v * min(1.0, (0.9 - dt) / 0.35)))
                sp.putalpha(a)
                frame.paste(sp, (int(x - 150), int(y - 150)), sp)
            # floating numbers (game-style damage popups)
            pops = []
            if e['dead'] + e['lost'] > 0:          # no popup when nobody died
                pops.append(('%s %d人' % (e['cn'], e['dead'] + e['lost']),
                             (255, 78, 78), 0.0))
            try:
                has_loss = float(str(e['loss']).replace(',', '')) > 0
            except (TypeError, ValueError):
                has_loss = bool(str(e['loss']).strip())
            if has_loss:
                # loss_text lets a place whose loss is far off the 亿 scale
                # (Hong Kong's HK$174,000) print its own unit
                pops.append((e.get('loss_text') or ('%s亿(CNY)' % e['loss']),
                             (255, 214, 60), 0.34 if pops else 0.0))
            for k, (val, colr, delay) in enumerate(pops):
                tau = (dt - delay) * POPUP_SPEED        # rule 15: 1.5x faster
                if tau < 0 or tau > POPUP_DUR: continue
                v0 = 4.0 * POPUP_APEX / POPUP_DUR          # apex height is fixed
                gg = 8.0 * POPUP_APEX / (POPUP_DUR ** 2)
                yy = y + e.get('dy', 0) - v0 * tau + 0.5 * gg * tau * tau
                xx = x + e.get('dx', 0) + (18 if k else -12) * tau
                # rule 15: a clear fade-out over the last third of the flight
                al = _ramp(tau, 0.0, 0.10 * POPUP_DUR) * \
                     _ramp(POPUP_DUR - tau, 0.0, 0.40 * POPUP_DUR)
                if al <= 0: continue
                d = ImageDraw.Draw(frame, 'RGBA')
                draw_text(d, (xx, yy), val, font=font(F_CJKB, 30),
                       fill=colr + (int(255 * al),), anchor='mm')

    # ---- markers that persist into the pulled-back panorama ---------------
    def _peaks(self):
        return tuple((float(pk['h']), float(pk['lon']), float(pk['lat']), pk['label'],
                      tuple(pk.get('color', [255, 214, 130])))
                     for pk in (_D.get('peaks') or []))

    def peak_tags(self, frame, proj, h, t=None, force=False):
        """rule 4: the marker is a coloured dot with a thin white ring, filled in
        that peak's own theme colour.  rule 2: its text fades out 2 s after it
        appears while the dot stays on the track."""
        dd = ImageDraw.Draw(frame, 'RGBA')
        for k, (hpk, lo, la, txt, _cfgcol) in enumerate(self._peaks()):
            if h < hpk and not force: continue
            col = theme_col(float(S.WF(hpk)), level_of(float(S.WF(hpk)), _phase_at(hpk)))
            if force:
                aa, ta = 1.0, 1.0
            else:
                aa = _ramp(h, hpk, hpk + 1.0)
                tt = t if t is not None else t_of_hours(hpk)
                ta = aa * (1.0 - _ramp(tt, t_of_hours(hpk) + LABEL_HOLD_S,
                                       t_of_hours(hpk) + LABEL_HOLD_S + LABEL_FADE_S))
            if aa <= 0.01: continue
            px, py = proj(lo, la)
            off = -1 if k % 2 == 0 else 1      # alternate above / below
            if ta > 0.01:
                dd.line([px + 34, py + 26 * off, px + 128, py + 76 * off],
                        fill=col + (int(140 * ta),), width=3)
                draw_text(dd, (px + 138, py + 78 * off), txt, font=font(F_MONOB, 24),
                        fill=col + (int(245 * ta),), anchor='lm')
                draw_text(dd, (px + 138, py + 110 * off),
                        (S.t0 + timedelta(hours=hpk)).strftime('%Y-%m-%d %HZ'),
                        font=font(F_MONO, 20), fill=(232, 240, 252, int(230 * ta)),
                        anchor='lm')
            dd.ellipse([px - 9, py - 9, px + 9, py + 9],
                       fill=col + (int(235 * aa),), outline=(255, 255, 255, int(230 * aa)),
                       width=2)

    def landfall_tag(self, frame, proj, t, force=False):
        """force=True -> panorama: no library marker, only a simple text tag"""
        for lf in LANDFALLS:
            if lf.get('no_fx'): continue        # not a landfall event (see _build)
            tl = t_of_hours(lf['h'])
            if t <= tl and not force: continue
            lx, ly = proj(lf['lon'], lf['lat'])
            if force:
                self._simple_tag(frame, lx, ly, lf)
                continue
            # rule 3: the library clip ends with the marker accelerating, shrinking
            # and vanishing.  Keep only the steady spin, loop it forever, and draw
            # it at 30 % of its former linear size.
            nf = len(self.fx[lf['landed']])
            keep = max(2, int(nf * 0.65))                   # drop the shrink-away
            fi = int((t - tl) / 1.6 * keep) % keep          # one turn per 1.6 s
            sp = Image.open(self.fx[lf['landed']][fi]).convert('RGB')
            msz = max(8, int(lf['size'] * MARKER_SCALE))
            sp = sp.resize((msz, msz), Image.LANCZOS)
            screen_paste(frame, sp, lx, ly)
            # rule 2: the text fades 2 s after it appears, the marker stays
            la = _ramp(t, tl + 0.9, tl + 1.6) * \
                 (1.0 - _ramp(t, tl + LABEL_HOLD_S, tl + LABEL_HOLD_S + LABEL_FADE_S))
            # a storm can come ashore many times in a couple of seconds of
            # screen time; without a hold the tags stack into a pile
            hold = float(_c('view.landfall_tag_hold', 0.0) or 0.0)
            if hold > 0:
                la *= _ramp(hold - (t - tl), 0.0, 0.7)
            if la <= 0.01: continue
            d = ImageDraw.Draw(frame, 'RGBA')
            a = int(240 * la)
            oy = lf.get('off_y', 30)
            d.line([lx + 20, ly + 18, lx + 96, ly + oy + 12],
                   fill=(255, 255, 255, int(130 * la)), width=2)
            draw_text(d, (lx + 104, ly + oy), lf['en'], font=font(F_MONOB, 22),
                   fill=(255, 255, 255, a), anchor='lm')
            mixed(d, (lx + 232, ly + oy), lf['cn'], font(F_MONOB, 22), font(F_CJKB, 21),
                  (255, 200, 200, a), 1.5)
            draw_text(d, (lx + 104, ly + oy + 30), '%s  -  %s' % (lf['place'], lf['stamp']),
                   font=font(F_MONO, 18), fill=(228, 238, 252, int(232 * la)), anchor='lm')

    def _simple_tag(self, frame, lx, ly, lf):
        """peak-style annotation used in the pulled-back panorama"""
        d = ImageDraw.Draw(frame, 'RGBA')
        col = (255, 176, 176) if lf is LANDFALLS[-1] else (255, 150, 220)
        dy = lf.get('simple_dy', 0)
        d.ellipse([lx - 9, ly - 9, lx + 9, ly + 9], fill=col + (220,))
        d.line([lx + 18, ly + (20 if dy >= 0 else -20), lx + 110, ly + dy * 0.6],
               fill=col + (150,), width=3)
        x0 = lx + 120
        draw_text(d, (x0, ly + dy - 12), lf['en'], font=font(F_MONOB, 24),
               fill=col + (245,), anchor='lm')
        draw_text(d, (x0, ly + dy + 20), '%s  -  %s' % (lf['place'], lf['stamp']),
               font=font(F_MONO, 20), fill=(234, 242, 254, 235), anchor='lm')

    # ---- frames -----------------------------------------------------------
    def _arm(self, kind, idx, sub):
        """cached arm angle: `kind='icon'` -> idx is the icon frame phase and sub
        the level; `kind='notets'` -> idx is the effect frame"""
        cache = getattr(self, '_armcache', None)
        if cache is None:
            cache = self._armcache = {}
        key = (kind, idx, sub)
        if key in cache:
            return cache[key]
        if kind == 'icon':
            a = arm_angle(icon_sprite(sub, idx))
        else:
            a = arm_angle(Image.open(self.fx['notets'][idx]))
        cache[key] = a
        return a

    def sprite_for(self, sw, nf, wind, phase=None, h=None):
        """At most TWO icons, blended into ONE layer.

        The incoming icon is laid over the outgoing one at opacity 0 and rises
        LINEARLY to 1 (`build_icon_schedule`), so the number inside the icon
        cross-fades with the colour; the outgoing icon is dropped at 1.  Blending
        into a single layer keeps it one sprite on screen, so nothing brightens
        and nothing jumps.

        TC tint is restricted to C5+/C5++: the lower bands already carry the
        right colour, and running them through `tinted()` brightens their soft
        halo (measured C1 +197 %, C5 +81 %), which reads as a glow nobody asked
        for. EX uses its separate continuous colour rule above 30 kt.
        """
        hemisphere = 'S' if h is not None and sample(h)[1] < 0 else 'N'

        def spr(lvl):
            s = icon_sprite(lvl, nf, hemisphere=hemisphere)
            if lvl == 'EX':
                coloured = ex_icon_tinted(s, wind)
                return ex_icon_with_lightning(coloured, nf, wind)
            if lvl in ('C5+', 'C5++'):
                q = icon_tint_colour(wind, lvl)
                s = tinted((hemisphere, lvl, nf, q), s, q)
                s = with_glow(s, glow_strength(wind, lvl),
                              highwind_halo_colour(wind) if wind > 200 else None,
                              1.0 + 0.2 * float(np.clip((wind - 300) / 200, 0, 1)))
                if lvl == 'C5++':
                    s = tc_digit_tinted(s, wind)
            return s

        # A phase change - low pressure becoming a remnant vortex or an
        # extratropical system, or the reverse - fades the incoming phase art in
        # LINEARLY IN TIME across TRANS_H hours either side of the boundary.
        #
        # Test it on the phase NAMES, never on "how many levels are active": an
        # ordinary band boundary inside the tropical cyclone (the TD/TS one at
        # 34 kt, say) also returns two levels, and treating that as a phase
        # change made TD and TS overlap around 30 kt and bypassed the wind-linear
        # band ramp, which is what made the icon switch feel jerky.
        if h is not None:
            for hb, pa, pb in PHASE_BOUNDS:
                if abs(h - hb) <= TRANS_H:
                    t = (h - (hb - TRANS_H)) / (2.0 * TRANS_H)
                    # Each side resolves to ONE icon.  'TC' is a phase, not a
                    # band, so it has to go through level_of - passing it to
                    # icon_sprite looks for an `icons\TC\` folder that does not
                    # exist.
                    def _side(ph):
                        return level_of(wind, ph)
                    la, lb = _side(pa), _side(pb)
                    # Same overlapping crossfade the band change uses: the
                    # incoming phase art fades in OVER the outgoing one, both
                    # moving at once.  A sequential out-then-in reads as two
                    # separate events instead of one transition.
                    if t <= 0.002:
                        return spr(la)
                    if t >= 0.998:
                        return spr(lb)
                    return Image.blend(spr(la), spr(lb), t)

        if phase is not None:
            under, over, u = icon_pair(wind, phase)
            if over is None or u <= 0.002:
                return spr(under)
            if u >= 0.998:
                return spr(over)
            return Image.blend(spr(under), spr(over), u)

        items = sorted(((l, w) for l, w in sw.items() if w > 0.0),
                       key=lambda kv: -kv[1])[:2]
        if not items:
            return None
        if len(items) == 1:
            return spr(items[0][0])
        (la, wa), (lb, wb) = items
        t = wb / max(1e-6, wa + wb)
        return Image.blend(spr(la), spr(lb), t)

    def _compose_hud(self, t):
        hudlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        hudlay.paste(self.hud_rest, (0, 0), self.hud_rest)
        # item 6: panels fly in, staggered, instead of all appearing at once
        for box, lay, side, delay in self.hud_parts:
            u = _ramp(t, INTRO + delay, INTRO + delay + HUD_IN_DUR)
            if u <= 0.001:
                continue
            a = lay
            if u < 0.999:
                a = lay.copy()
                a.putalpha(a.getchannel('A').point(lambda v: int(v * u)))
            off = int((1.0 - u) * HUD_IN_SLIDE)
            if side == 'L':
                xy = (box[0] - off, box[1])
            elif side == 'R':
                xy = (box[0] + off, box[1])
            else:
                xy = (box[0], box[1] + off)
            hudlay.alpha_composite(a, xy)

        return hudlay

    def frame_main(self, t, i):
        h = hours_of_t(t)
        lon, lat, wind, pres, ace, ph = sample(h)
        sw = state_weights(h, wind)
        lvl = dominant(sw)
        col = state_color(h, wind, sw)
        cam_lon, cam_lat, span = self.cam[i]
        img, proj = cam_frame(cam_lon, cam_lat, span)
        frame = Image.fromarray(img)

        # ---- HUD is built into its own layer so it can exit as a whole -----
        hud_ready = t >= INTRO + 0.78 + HUD_IN_DUR
        if hud_ready and getattr(self, '_hud_ready', None) is not None:
            hudlay = self._hud_ready.copy()
        else:
            hudlay = self._compose_hud(t)
            if hud_ready:
                self._hud_ready = hudlay.copy()

        # cloud inset (screen blended, feathered -> no visible square, no caption)
        ca = self.cloud_alpha[i]
        if t > T_MAIN:
            ca *= max(0.0, 1.0 - _ramp(t, T_MAIN, T_MAIN + PULL * 0.8))
        if ca > 0.01:
            cf, ok = cloud_state(h)
            if ok:
                ov = cloud_overlay(cf, ca)
                box = (CLOUD_C[0] - CLOUD_R, CLOUD_C[1] - CLOUD_R,
                       CLOUD_C[0] + CLOUD_R, CLOUD_C[1] + CLOUD_R)
                frame.paste(ImageChops.screen(frame.crop(box), ov.convert('RGB')), box)

        cx, cy = proj(lon, lat)
        # ---- item 3: storm icon + glow fade out while pulling back ---------
        sfade = 1.0
        if t > T_MAIN:
            sfade = max(0.0, 1.0 - _ramp(t, T_MAIN, T_MAIN + PULL * 0.7))
        halo = col
        if lvl in ('C5+', 'C5++'):               # keep the deep tint readable
            halo = tuple(min(255, int(v * 1.25 + 70)) for v in col)
        ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        if sfade > 0.02:
            self.glow(ov, cx, cy, wind, halo, math.sin(t * 1.6), sfade)
        self.trail(ov, h, proj)
        frame.paste(ov, (0, 0), ov)

        # storm icon (cross-faded between levels)
        if sfade > 0.02:
            nf = int((t - INTRO) * ICON_FPS)
            # ONE definition of the phase.  sample() returns a STEP at the fix
            # times, while the blend window is measured from the PHASE_BOUNDS
            # midpoint - using the step here let the icon fall back to the old
            # phase's art (TD at 26 kt) between the window closing and the next
            # fix, so TD flashed for a moment before the remnant returned.
            spr = self.sprite_for(sw, nf, wind, phase=_phase_at(h), h=h)
            if wind > 155:                  # +1 % linear per kt, cumulative
                sc = min(1.32, 1.0 + 0.01 * (wind - 155.0))
                n2 = int(round(spr.width * sc))
                spr = spr.resize((n2, n2), Image.LANCZOS)
            if self.ef_mode:
                # Dujuan only: a 4 km pinhole eye made the storm's footprint tiny,
                # so while it holds C3 the icon shrinks to a third of its size and
                # grows back when it drops to C2 (spec: size embodiment)
                u = _ramp(wind, 92.0, 99.0) * (1.0 - _ramp(wind, 118.0, 126.0))
                isc = 1.0 + (EF_ICON_SCALE - 1.0) * u
                n2 = max(8, int(round(spr.width * isc)))
                spr = spr.resize((n2, n2), Image.LANCZOS)
            if sfade < 0.99:
                spr = Image.eval(spr, lambda v: int(v * sfade))
            screen_paste(frame, spr, cx, cy)
            # rule 17: name the system beside its icon - invest, TD number, or
            # the storm's own name once it has one
            lbl, lcol = self.icon_label(h, ph)
            if lbl and sfade > 0.5:
                d17 = ImageDraw.Draw(frame, 'RGBA')
                a17 = int(235 * sfade * _ramp(t, INTRO + 0.4, INTRO + 1.4))
                if a17 > 0:
                    f17 = font(F_MONOB, 40)
                    # tucked against the icon's upper-right shoulder
                    lx17 = cx + spr.width * 0.36
                    ly17 = cy - spr.height * 0.36
                    draw_text(d17, (lx17 + 2, ly17 + 2), lbl, font=f17,
                             fill=(0, 0, 0, int(a17 * 0.55)), anchor='lm')
                    draw_text(d17, (lx17, ly17), lbl, font=f17,
                             fill=lcol + (a17,), anchor='lm')

        # rapid intensification: ERI particle, whole GIF in ~0.3 s
        for h0, h1, l0, l1, use_fx in RI_EVENTS:
            if not use_fx:
                continue
            # the burst's own midpoint lands on the event's midpoint
            te = t_of_hours((h0 + h1) / 2.0) - RI_FX_DUR / 2.0
            if te <= t <= te + RI_FX_DUR and self.fx.get('eri'):
                fi = min(len(self.fx['eri']) - 1, int((t - te) / RI_FX_DUR * len(self.fx['eri'])))
                sp = Image.open(self.fx['eri'][fi]).convert('RGBA').resize((340, 340), Image.LANCZOS)
                frame.paste(sp, (int(cx - 170), int(cy - 170)), sp)

        # TD -> TS upgrade flash - one per crossing, not just the first
        tc1 = None
        for hx in _ts_fx_hours():
            tx = t_of_hours(hx)
            if tx <= t <= tx + 0.5:
                tc1 = tx
                break
        if tc1 is not None:
            fi = min(len(self.fx['notets']) - 1, int((t - tc1) * 60))
            sp = upgrade_sprite(Image.open(self.fx['notets'][fi]).convert('RGB'), hx).resize((430, 430), Image.LANCZOS)
            # rule 10.  Both the TC icon and the upgrade effect are authored
            # starting at 0 degrees, and the icon turns ICON_TURNS times over one
            # loop of N_ICON frames - so the icon's angle is just arithmetic, no
            # image analysis.  The effect's frame 0 is 0 degrees, so rotating the
            # effect by the icon's angle at the trigger lines the arms up; the
            # angle is LATCHED there and never recomputed (the icon keeps
            # spinning, so re-deriving it every frame dragged the effect around
            # and flipped sign at the 0/360 wrap).
            _rot_cache = getattr(self, '_notets_rot', None)
            if _rot_cache is None:
                _rot_cache = self._notets_rot = {}
            _rot_key = round(tc1, 3)
            _rot = _rot_cache.get(_rot_key)
            if _rot is None:
                _nf_trig = int(round((tc1 - INTRO) * ICON_FPS))
                _rot = (ICON_TURNS * 360.0 / N_ICON) * (_nf_trig % N_ICON)
                _rot_cache[_rot_key] = _rot
            if abs(_rot) > 0.01:
                sp = sp.rotate(_rot, resample=Image.BICUBIC, fillcolor=(0, 0, 0))
            screen_paste(frame, sp, cx, cy)

        # peak markers along the track
        self.peak_tags(frame, proj, h, t)

        # landfall impacts (native 60 fps, no slow motion)
        for lf in LANDFALLS:
            tl = t_of_hours(lf['h'])
            if tl <= t <= tl + 1.0 and self.fx.get(lf['fx']):
                fi = min(len(self.fx[lf['fx']]) - 1, int((t - tl) * 60))
                sp = Image.open(self.fx[lf['fx']][fi]).convert('RGB')
                # Same wind interpolation and sizing as season's active renderer.
                impact_wind = float(np.interp(lf['h'], S.ihours, S.iwind))
                box = landfall_impact_size(impact_wind)
                k = box / max(sp.size)
                size = (max(1, int(sp.width * k)), max(1, int(sp.height * k)))
                tint = icon_tint_colour(impact_wind, level_of(impact_wind, 'TC'))
                if tint is None:
                    sp = sp.resize(size, Image.LANCZOS)
                else:
                    sp = _asset_frames.get(self.fx[lf['fx']][fi], size=size, tint=tint)
                lx, ly = proj(lf['lon'], lf['lat'])
                screen_paste(frame, sp, lx, ly)
        self.landfall_tag(frame, proj, t)

        self.damage(frame, t, proj)

        # dynamic HUD
        ov2 = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        self.status(ov2, S.t0 + timedelta(hours=h), lon, lat, wind, pres, lvl, col)
        self.ace(ov2, ace)
        self.graph(ov2, h, wind, pres, ph)
        self.timeline(ov2, h, col)
        hudlay.paste(ov2, (0, 0), ov2)
        hudlay = compact_corner_hud(hudlay)

        d = ImageDraw.Draw(hudlay, 'RGBA')
        # low-key notes near the peak(s): one per peak, or one shared note
        fn = font(F_CJKB, 39)
        notes = []
        for i, pk in enumerate(_D.get('peaks') or []):
            if pk.get('note'):
                notes.append((pk['note'], float(pk['h']) - 12.0, float(pk['h']) + 14.0))
        if not notes and _S.get('note'):
            pk = _D.get('peaks') or []
            notes.append((_S['note'],
                          (float(pk[0]['h']) - 12.0) if pk else 0.0,
                          (float(pk[-1]['h']) + 20.0) if pk else 0.0))
        vis = [(txt, _ramp(h, h0, h0 + 8.0) * _ramp(h1 - h, 0.0, 8.0))
               for txt, h0, h1 in notes]
        vis = [(t, a) for t, a in vis if a > 0.01]
        for i, (txt, na) in enumerate(vis):
            mixed_base(d, (40, 404 + 48 * i + fn.getmetrics()[0]), txt,
                       self.f_note, fn, (255, 255, 255, int(250 * na)))
        # the credit line names the agencies, so it carries Chinese - draw it
        # with the mixed helper or the names become tofu boxes
        cline = _S.get('credit_line', '')
        _fa, _fb = font(F_MONO, 18), font(F_CJK, 18)
        mixed_top(d, (W // 2 - mixed_w(d, cline, _fa, _fb) / 2.0, 1052), cline,
                  _fa, _fb, (214, 226, 242, 240))

        # panel exit during the pull-back
        if t > T_MAIN:
            self.summary_banner(frame, t)
            self.pano_cards(frame, t)
            ex = _ramp(t, T_MAIN, T_MAIN + PULL * 0.85)
            if ex > 0.995:
                return frame
            top = hudlay.crop((0, 0, W, 560)); bot = hudlay.crop((0, 560, W, H))
            a = top.getchannel('A').point(lambda v: int(v * (1 - ex)))
            top.putalpha(a)
            a = bot.getchannel('A').point(lambda v: int(v * (1 - ex)))
            bot.putalpha(a)
            frame.paste(top, (0, int(-ex * 230)), top)
            frame.paste(bot, (0, 560 + int(ex * 300)), bot)
            return frame

        frame.paste(hudlay, (0, 0), hudlay)
        return frame

    def frame_intro(self, t):
        frame = Image.new('RGB', (W, H), (0, 0, 0))
        i = int(t * 20) % len(self.fx['logo'])
        lg = Image.open(self.fx['logo'][i]).convert('RGB').resize((460, 460), Image.LANCZOS)
        canvas = Image.new('RGB', (W, H), (0, 0, 0))
        canvas.paste(lg, (int(W / 2 - 230), int(H / 2 - 270)))
        frame = ImageChops.screen(frame, canvas)
        d = ImageDraw.Draw(frame)
        a = _ramp(t, 0.9, 1.7)
        if a > 0:
            f1 = font(F_UIB, 60)
            s = intro_title()
            wd = tracked_w(d, s, f1, 6.0)
            tracked(d, ((W - wd) / 2, 690), s, f1, tuple(int(255 * a) for _ in range(3)), 6.0)
        a2 = _ramp(t, 1.8, 2.6)
        if a2 > 0:
            t2 = intro_name_line()
            mixed(d, (W / 2 - mixed_w(d, t2, font(F_MONO, 25), font(F_CJK, 25)) / 2.0, 762),
                  t2, font(F_MONO, 25), font(F_CJK, 25),
                  tuple(int(215 * a2) for _ in range(3)))
        a3 = _ramp(t, 2.6, 3.4)
        if a3 > 0:
            t3 = _S.get('intro_footer', '')
            mixed(d, (W / 2 - mixed_w(d, t3, font(F_MONO, 15), font(F_CJK, 15)) / 2.0, 828),
                  t3, font(F_MONO, 15), font(F_CJK, 15),
                  tuple(int(190 * a3) for _ in range(3)))
        f = _ramp(t, INTRO - 0.7, INTRO)
        if f > 0:
            c0 = self.cam[int(INTRO * FPS)]
            img, _ = cam_frame(c0[0], c0[1], c0[2])
            frame = Image.blend(frame, Image.fromarray(img), f)
        return frame

    # -- pulled-back "poster" frame (used by HOLD and as the summary backdrop)
    def pano_frame(self, trail=True):
        if getattr(self, '_pano', None) is None:
            # item 8: use the camera of the frame the hold actually starts on.
            # cam[NFRAMES-1] is further settled, so the track jumped at the cut.
            c = self.cam[min(NFRAMES - 1, int(round(T_PULL * FPS)))]
            img, proj = cam_frame(c[0], c[1], c[2])
            frame = Image.fromarray(img)
            ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            self.trail(ov, S.duration_h, proj)
            frame.paste(ov, (0, 0), ov)
            self.pano_markers(frame, proj)
            self._pano = frame
        return self._pano

    # ---- panorama annotations: fixed layout, no overlap, correct leaders ---
    def pano_tags(self, frame, proj):
        """everything is derived from the config, so the offsets cannot drift
        out of sync with the data the way a hard-coded table would"""
        d = ImageDraw.Draw(frame, 'RGBA')
        items = []
        for i, pk in enumerate(_D.get('peaks') or []):
            dx = int(pk.get('pano_dx', 152))
            dy = int(pk.get('pano_dy', -44 if i == 0 else 62))
            items.append((float(pk['lon']), float(pk['lat']), dx, dy,
                          'lm' if dx > 0 else 'rm',
                          tuple(pk.get('color', [255, 214, 130])),
                          pk['label'], _dt(float(pk['h'])).strftime('%Y-%m-%d %HZ')))
        for lf in LANDFALLS:
            # spec: the landing marker keeps its spinning square here too - it is
            # not swapped for a plain dot once the camera pulls back
            items.append((lf['lon'], lf['lat'], lf['simple_dx'], lf['simple_dy'],
                          lf['simple_anchor'], lf['color'],
                          '%s   %s' % (lf['en'], lf['stamp']), lf['place'],
                          lf.get('landed'), lf.get('size', 0)))
        # the config gives each tag a PREFERRED offset; when two project close
        # together the label is displaced until it clears - a storm with ten
        # maxima cannot be hand-tuned against a projection.  The track itself is
        # occupancy too, so a tag does not sit across the path.
        fT, fS = font(F_MONOB, 24), font(F_MONO, 20)
        placed = []
        for it in items:
            if len(it) > 8:                      # index the marker lookups
                break
        _h = 0.0
        while _h < S.duration_h + 1e-6:
            _lo, _la, _w, _p, _a, _ph = sample(_h)
            _x, _y = proj(_lo, _la)
            placed.append((_x - 9.0, _y - 15.0, _x + 9.0, _y + 15.0))
            _h += 0.8
        n_track = len(placed)
        for it in items:
            lon, lat, dx, dy, anch, col, title, sub = it[:8]
            px, py = proj(lon, lat)
            tw = max(text_width(d, title, font=fT), text_width(d, sub, font=fS)) + 14.0
            th = 52.0

            def _box(tx, ty, a):
                x0 = tx if a == 'lm' else tx - tw
                return (x0, ty - 18.0, x0 + tw, ty + th - 18.0)

            cands = [(dx, dy)]
            for k in (1, 2, 3, 4, 5, 6, 7):
                cands.append((dx, dy - 44 * k))
                cands.append((dx, dy + 44 * k))
            for k in (1, 2):                      # then slide along the leader
                cands.append((dx + 170 * k, dy))
                cands.append((dx - 170 * k, dy))
            best = None
            for cdx, cdy in cands:
                a = 'lm' if cdx > 0 else 'rm'
                tx, ty = px + cdx, py + cdy
                bx = _box(tx, ty, a)
                if bx[0] < 8 or bx[2] > W - 8 or bx[1] < 242 or bx[3] > H - 8:
                    continue
                if any(not (bx[2] < q0 or bx[0] > q2 or bx[3] < q1 or bx[1] > q3)
                       for q0, q1, q2, q3 in placed):
                    continue
                best = (tx, ty, a, bx)
                break
            if best is None:                      # nothing fits: keep the preference
                a = 'lm' if dx > 0 else 'rm'
                tx, ty = px + dx, py + dy
                best = (tx, ty, a, _box(tx, ty, a))
            tx, ty, anch, bx = best
            placed.append(bx)
            # a landfall keeps its spinning square; a peak is a white-ringed dot
            mk = it[8] if len(it) > 8 else None
            if mk and self.fx.get(mk):
                frames = self.fx[mk]
                keep = max(2, int(len(frames) * 0.65))       # drop the shrink-away
                sp = Image.open(frames[keep // 3 % keep]).convert('RGB')
                msz = max(8, int((it[9] or 60) * MARKER_SCALE))
                sp = sp.resize((msz, msz), Image.LANCZOS)
                screen_paste(frame, sp, px, py)
            else:
                d.ellipse([px - 7, py - 7, px + 7, py + 7], fill=col + (230,))
            d.line([px + (20 if dx > 0 else -20), py + (16 if dy >= 0 else -16),
                    tx + (-18 if dx > 0 else 18), ty],
                   fill=col + (155,), width=3)
            draw_text(d, (tx, ty - 13), title, font=fT, fill=col + (246,), anchor=anch)
            draw_text(d, (tx, ty + 19), sub, font=fS, fill=(236, 244, 254, 236), anchor=anch)

    # ---- rules 6 / 7 / 9: landing and peak info cards ---------------------
    def pano_markers(self, frame, proj):
        """rule 6: the panorama keeps the position markers but loses the text.

        A landing keeps its spinning square here too - it is what the viewer has
        been watching run along the path for the whole track, and swapping it for
        a dot at the last moment throws that away.
        """
        d = ImageDraw.Draw(frame, 'RGBA')
        for i, (hpk, lo, la, _t, _c) in enumerate(self._peaks()):
            px, py = proj(lo, la)
            col = theme_col(float(S.WF(hpk)), level_of(float(S.WF(hpk)), _phase_at(hpk)))
            d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=col + (235,),
                      outline=(255, 255, 255, 235), width=2)
        for lf in LANDFALLS:
            if lf.get('no_fx'): continue        # not a landfall event (see _build)
            lx, ly = proj(lf['lon'], lf['lat'])
            mk = lf.get('landed')
            if mk and self.fx.get(mk):
                frames = self.fx[mk]
                keep = max(2, int(len(frames) * 0.65))       # drop the shrink-away
                sp = Image.open(frames[keep // 3 % keep]).convert('RGB')
                msz = max(8, int(lf['size'] * MARKER_SCALE))
                sp = sp.resize((msz, msz), Image.LANCZOS)
                screen_paste(frame, sp, lx, ly)
                continue
            col = theme_col(float(lf.get('wind', 60.0)), lf.get('lvl', 'TS'))
            d.ellipse([lx - 7, ly - 7, lx + 7, ly + 7], fill=col + (225,),
                      outline=(255, 255, 255, 225), width=2)

    def _cards(self):
        """the two card lists: peaks (left) and landfalls (right)"""
        if getattr(self, '_cardcache', None) is not None:
            return self._cardcache
        pk = []
        for i, (hpk, lo, la, _t, _c) in enumerate(self._peaks()):
            w = float(S.WF(hpk))
            p = float(S.PF(hpk))
            lvl = level_of(w, _phase_at(hpk))
            card_colour = single_card_colour(w, lvl)
            pk.append(dict(txt=self.badge_text(lvl, w), col=card_colour,
                           tcol=card_colour,
                           wind=w,
                           l1='PEAK %d' % (i + 1),
                           l2='%d kt / %d hPa' % (round(w), round(p)),
                           l3='%s   %s' % (self._cat(lvl),
                                           (S.t0 + timedelta(hours=hpk)).strftime('%m-%d %HZ'))))
        lf = []
        for e in LANDFALLS:
            lvl = e.get('lvl', 'TS')
            wl = float(e.get('wind', 60.0))
            lf.append(dict(col=single_card_colour(wl, lvl),
                           tcol=single_card_colour(wl, lvl),
                           wind=wl,
                           l1=e.get('place', e['en']),
                           l2='%.2f%s  %.2f%s' % (abs(e['lat']), 'N' if e['lat'] >= 0 else 'S',
                                                  abs(e['lon'] % 360.0),
                                                  'E' if (e['lon'] % 360.0) < 180 else 'W'),
                           l3='%d kt   %s' % (round(float(e.get('wind', 0))), e.get('stamp', ''))))
        self._cardcache = (pk, lf)
        return self._cardcache

    @staticmethod
    def _cat(lvl):
        return {'TD': 'TROPICAL DEPRESSION', 'TS': 'TROPICAL STORM'}.get(lvl, lvl)

    def pano_cards(self, frame, t):
        """rules 6/7/9.  Cards ride in with the banner: landfalls from the right,
        peaks from the left, a column every CARD_CYCLE seconds.

        Rule 2 (tie-in): the sides do not retire independently.  Everyone stays
        until the busiest side has played all of its columns - so with two
        landfall columns and three peak columns the banner shows for three
        rounds, the peaks play three, and the landfalls play two and then hold
        their last column in place until the third round ends, when the banner
        and every card retract together.

        Rule 3 (exit): a column leaving the screen travels the way it came from -
        peaks slide left, landfalls slide right - while the next one enters.
        """
        pk, lf = self._cards()
        if not pk and not lf:
            return
        a0 = T_MAIN + 1.15
        if t < a0:
            return
        end = T_PULL + HOLD
        if t >= end:
            return
        CH, GAP = 100, 10
        per = cards_per_column()
        d = ImageDraw.Draw(frame, 'RGBA')

        def draw(col, side, alpha, exiting=False):
            if alpha <= 0.01 or not col:
                return
            # Peaks sit on the left, landfalls on the right.  Each column enters
            # from its own outside edge and LEAVES THE SAME WAY - peaks slide
            # left, landfalls slide right - so one sign covers both; swapping it
            # for the exit sent them out the wrong side.
            travel = CARD_W + 60
            sign = -1 if side == 'L' else 1
            off = int((1.0 - alpha) * travel * sign)
            y = 250
            for c in col:
                a = alpha          # the retraction already rides in `alpha`
                if side == 'L':
                    x0, x1 = CARD_X_L + off, CARD_X_L + CARD_W + off
                else:
                    x0, x1 = W - CARD_M - CARD_W + off, W - CARD_M + off
                if a > 0.01:
                    d.rounded_rectangle([x0, y, x1, y + CH], radius=5,
                                        fill=(8, 12, 22, int(205 * a)),
                                        outline=(255, 255, 255, int(78 * a)), width=1)
                    d.rectangle([x0, y, x0 + 8, y + CH], fill=c['col'] + (int(240 * a),))
                    text_in_box(d, (x0 + 22, y + 12, x1 - 14, y + 36), c['l1'], font(F_MONOB, 29), font(F_CJKB, 29),
                           fill=c.get('tcol', c['col']) + (int(250 * a),))
                    text_in_box(d, (x0 + 22, y + 47, x1 - 14, y + 66), c['l2'], font(F_MONO, 22), font(F_CJKM, 22),
                           fill=single_highwind_text(c.get('wind', 0.0), (232, 240, 252)) + (int(238 * a),))
                    text_in_box(d, (x0 + 22, y + 75, x1 - 14, y + 91), c['l3'], font(F_MONO, 19), font(F_CJKM, 19),
                           fill=single_highwind_text(c.get('wind', 0.0), (206, 218, 236)) + (int(225 * a),))
                y += CH + GAP

        ncol = {'L': max(1, (len(pk) + per - 1) // per),
                'R': max(1, (len(lf) + per - 1) // per)}
        el = t - a0
        cyc = int(el // CARD_CYCLE)
        ph = el - cyc * CARD_CYCLE
        u_in = _ramp(ph, 0.0, CARD_FADE)
        u_out = 1.0 - _ramp(ph, 0.0, CARD_FADE)
        # the final retraction is a SLIDE-OUT, not a fade in place, so the last
        # thing the viewer sees is the same motion the carousel has been using
        retract = 1.0 - _ramp(t, end - CARD_FADE, end)

        def page(items, k):
            return items[k * per:(k + 1) * per]

        for side, items in (('L', pk), ('R', lf)):
            cols = ncol[side]
            cur = min(cyc, cols - 1)
            prev = min(cyc - 1, cols - 1)
            if retract < 0.999:
                draw(page(items, cur), side, retract, exiting=True)
                continue
            if cyc == 0:
                # rule 9: the first column rides in too - it must not just appear
                draw(page(items, 0), side, _ramp(t, a0, a0 + 0.8))
                continue
            # A side that has run out of columns HOLDS its last one: there is no
            # outgoing column, so it must not replay the exit animation cycle
            # after cycle (prev == cur).  Only a real change animates.
            if prev != cur:
                draw(page(items, prev), side, u_out, exiting=True)
                draw(page(items, cur), side, u_in)
            else:
                draw(page(items, cur), side, 1.0)

    # ---- item 6: summary banner that slides in during the panorama --------
    def banner_t(self, t):
        """returns (alpha, x_offset) for the panorama summary banner"""
        a0 = T_MAIN + 0.55
        a1 = T_PULL + HOLD                     # panorama ends
        if t < a0 or t > a1: return 0.0, 1.0
        p = _ramp(t, a0, a0 + 0.8)             # slide in
        q = _ramp(t, a1 - 0.7, a1)             # slide out
        return p * (1.0 - q), (1.0 - p) + q

    def summary_banner(self, frame, t):
        """all facts printed directly on the Summary-N-TC-C5 banner, right 3/4,
        two lines, no extra dark strip"""
        aa, off = self.banner_t(t)
        if aa <= 0.01 or not self.banner: return
        BW, BH = 1700, 85
        # the library banner is authored at 60 fps; play it at its own rate so it
        # is not slowed down to match whatever the panorama hold happens to be
        fi = int((t - T_MAIN) * 60) % len(self.banner)
        card = self.banner[fi].resize((BW, BH), Image.LANCZOS)
        if aa < 0.995:
            card = Image.eval(card, lambda v: int(v * aa))
        d = ImageDraw.Draw(card, 'RGBA')
        a = int(255 * aa)
        sh = (12, 12, 12, int(190 * aa * (1.0 - _ramp(self.peak_wind, 185.0, 200.0))))
        x0 = 110 + int(off * 430)
        f_en, f_cn = font(F_UIB, 32), font(F_CJKB, 27)
        head = banner_head()
        headline_colour = single_highwind_text(self.peak_wind, (255, 255, 255), (30, 3, 9))
        data_colour = single_highwind_text(self.peak_wind, (255, 245, 252), (30, 3, 9))
        text_in_box(d, (446, 14, BW - 18, 44), head, f_en, f_cn, sh, 1.0)
        text_in_box(d, (444, 12, BW - 20, 42), head, f_en, f_cn, headline_colour + (a,), 1.0)
        line2 = banner_line2()
        f2, f2c = font(F_MONOB, 23), font(F_CJKB, 23)
        text_in_box(d, (446, 54, BW - 18, 76), line2, f2, f2c, sh)
        text_in_box(d, (444, 52, BW - 20, 74), line2, f2, f2c, data_colour + (a,))
        frame.paste(card, (x0, 30))

    def frame_hold(self, t):
        frame = self.pano_frame().copy()
        self.summary_banner(frame, t)
        self.pano_cards(frame, t)
        return frame

    def frame_summary(self, t):
        """Reserved end-card hook; currently an unchanged panorama.

        SUMMARY is zero, so normal exports never schedule this slot. Future
        designs can implement this hook and assign a duration; the former
        dim/blur, statistics, credits and fade-to-black are intentionally removed.
        """
        return self.pano_frame().copy()

    def render(self, i):
        t = i / FPS
        if t < INTRO: return self.frame_intro(t)
        if t < T_MAIN: return self.frame_main(t, i)
        if t < T_PULL: return self.frame_main(t, i)
        if t < T_SUM: return self.frame_hold(t)
        if SUMMARY > 0 and t < TOTAL: return self.frame_summary(t)
        return self.frame_hold(min(t, T_SUM))

def fmt_lat(v): return '%.1f%s' % (abs(v), 'N' if v >= 0 else 'S')
def fmt_lon(v):
    v = (v + 180) % 360 - 180
    return '%.1f%s' % (abs(v), 'E' if v >= 0 else 'W')

def _dt(h):
    return S.t0 + timedelta(hours=float(h))

def date_span_label():
    """y-axis footer of the intensity panel, e.g. SEP 08 - SEP 17"""
    a, b = S.t0, _dt(S.duration_h)
    return '%s - %s' % (a.strftime('%b %d').upper(), b.strftime('%b %d').upper())

def month_label():
    return S.t0.strftime('%b %Y').upper()

def day_ticks():
    """midnight UTC ticks inside the series span, labelled MM-DD"""
    from datetime import timedelta as _tdl
    t = S.t0.replace(hour=0, minute=0, second=0, microsecond=0)
    if t < S.t0:
        t += _tdl(days=1)
    out = []
    while True:
        h = (t - S.t0).total_seconds() / 3600.0
        if h > S.duration_h: break
        out.append((h, t.strftime('%m-%d')))
        t += _tdl(days=1)
    return out

def banner_head():
    return _c('banner.headline') or ('%s   %s   %s' % (_S.get('id', ''),
                                                       _S.get('title', ''),
                                                       _S.get('name_cn', '')))

def banner_line2():
    """derived by default so the figures can never drift from the data;
    set banner.line2 only to override the whole line"""
    t = _c('banner.line2')
    if t:
        return t
    pks = _D.get('peaks') or []
    best = ''
    if pks:
        # the strongest peak announces itself, not merely the last one
        p = max(pks, key=lambda x: float(np.interp(float(x['h']), S.ihours, S.iwind)))
        best = '%.0f kt / %.0f hPa' % (np.interp(float(p['h']), S.ihours, S.iwind),
                                       np.interp(float(p['h']), S.ihours, S.ipres))
    return ('PEAK %s      ACE %.2f x10^4 kt2      LOSS ~ %s      DEATHS %s'
            % (best, S.ace_total, _c('banner.loss', 'n/a'), _c('banner.deaths', 'n/a')))

def intro_title():
    """Configured copy is verbatim; only a missing title gets a default."""
    if 'intro_title' in _S:
        return _S['intro_title']
    if 'title' in _S:
        return _S['title']
    return 'hypoTC' if _S.get('hypothetical') else 'CYCLONE'

def intro_name_line():
    """The authored name line already includes any desired phase or qualifier."""
    return _S.get('intro_line', '')

def lifetime_label():
    """the end card states the tropical-cyclone stage only: the disturbance,
    remnant-vortex and extratropical stretches are not part of the lifetime"""
    tc = [i for i, ph in enumerate(S.phase) if ph == 'TC']
    if not tc:
        return ''
    h0, h1 = float(S.hours[tc[0]]), float(S.hours[tc[-1]])
    return '%s - %s ( %d d )' % (_dt(h0).strftime('%Y-%m-%d %HZ'),
                                 _dt(h1).strftime('%m-%d %HZ'),
                                 int(round((h1 - h0) / 24.0)))

def summary_rows():
    """Reserved end-card data adapter; not displayed by the current renderer."""
    """end card: derived facts on the left, per-storm facts on the right"""
    st = _c('summary', {}) or {}
    rows = [
        (_S.get('title', ''), _S.get('subtitle', ''), 'head', 110, 34),
        ('', 1700, 'rule', 110, 284),
        ('LIFETIME', '', 'lbl', 110, 320),
        (lifetime_label(), '', 'val', 110, 362),
    ]
    # left column.  one or two peaks keep the frozen two-line rhythm; a storm
    # with several maxima needs a compact one-line-per-peak block instead
    pks = _D.get('peaks') or []
    y = 436
    note = st.get('note') or _S.get('note', '')
    if len(pks) <= 2:
        for i, pk in enumerate(pks):
            rows.append(('PEAK %d' % (i + 1), '', 'lbl', 110, y))
            rows.append((pk.get('summary', ''), '', 'val', 110, y + 42))
            y += 116
        if note:
            rows.append((note, '', 'note', 110, y))
        rows.append(('ACCUMULATED CYCLONE ENERGY', '', 'lbl', 110, y + 62))
        rows.append(('%.2f x10^4 kt2' % S.ace_total, '', 'val', 110, y + 104))
        rows.append(('DATA SOURCES', '', 'lbl', 110, y + 168))
        rows.append((st.get('sources', ''), '', 'val2', 110, y + 204))
    elif len(pks) > 5:
        # a storm with many maxima needs two columns, or the list pushes ACE and
        # the source line through the rule at y = 912
        rows.append(('PEAKS', '', 'lbl', 110, y))
        y += 34
        half = (len(pks) + 1) // 2
        for i, pk in enumerate(pks):
            col, row = (0, i) if i < half else (1, i - half)
            short = pk.get('summary', '').replace(' kt / ', '/').replace(' hPa', '')
            rows.append(('%d  %s' % (i + 1, short), '', 'val3', 110 + col * 400, y + row * 30))
        y += half * 30
        if note:
            rows.append((note, '', 'note', 110, y))
            y += 30
        rows.append(('ACCUMULATED CYCLONE ENERGY', '', 'lbl', 110, y + 22))
        rows.append(('%.2f x10^4 kt2' % S.ace_total, '', 'val', 110, y + 64))
        rows.append(('DATA SOURCES', '', 'lbl', 110, y + 128))
        rows.append((st.get('sources', ''), '', 'val2', 110, y + 164))
    else:
        # tighten the rhythm as the peak list grows, so ACE and the source line
        # still land above the rule at y = 912
        step = 42 if len(pks) <= 4 else 34
        rows.append(('PEAKS', '', 'lbl', 110, y))
        y += step
        for i, pk in enumerate(pks):
            rows.append(('%d    %s' % (i + 1, pk.get('summary', '')), '', 'val2', 110, y))
            y += step
        if note:
            rows.append((note, '', 'note', 110, y))
            y += 30
        rows.append(('ACCUMULATED CYCLONE ENERGY', '', 'lbl', 110, y + 22))
        rows.append(('%.2f x10^4 kt2' % S.ace_total, '', 'val', 110, y + 64))
        rows.append(('DATA SOURCES', '', 'lbl', 110, y + 128))
        rows.append((st.get('sources', ''), '', 'val2', 110, y + 164))

    # right column - frozen vertical rhythm
    lf = LANDFALLS

    def _cat(l):
        cat = l.get('cat')
        if cat in (None, ''):
            wv = float(np.interp(l['h'], S.ihours, S.iwind))
            cat = level_of(wv, 'TC').replace('C', '')
            if cat.startswith('5'):
                cat = '5'
        return cat

    rows.append(('LANDFALL  ( %d )' % len(lf), '', 'lbl', 1020, 320))
    if len(lf) <= 4:
        for i, l in enumerate(lf):
            rows.append((l.get('place', ''), '', 'val2', 1020, 358 + 78 * i))
            rows.append(('%s   -   Category %s' % (l.get('stamp', ''), _cat(l)),
                         '', 'val3', 1020, 392 + 78 * i))
        y2 = 320 + 78 * len(lf) + 48
    else:
        # a storm can come ashore many times; two compact columns keep the
        # damage block on the card
        per = (len(lf) + 1) // 2
        for i, l in enumerate(lf):
            rows.append(('%s  -  C%s' % (l.get('place', ''), _cat(l)),
                         '', 'val3', 1020 + (i // per) * 470, 360 + 40 * (i % per)))
        y2 = 360 + 40 * per + 34
    rows.append((st.get('phase2_label', 'EXTRATROPICAL'), '', 'lbl', 1020, y2))
    rows.append((st.get('phase2_value', ''), '', 'val2', 1020, y2 + 38))
    y2 += 98
    rows.append((st.get('damage_label', 'DAMAGE'), '', 'lbl', 1020, y2))
    for i, line in enumerate(st.get('damage_lines', []) or []):
        rows.append((line, '', 'cn', 1020, y2 + 36 + 46 * i))
    rows.append(('', 1700, 'rule', 110, 912))
    creds = _c('credits', []) or []
    cstep = 54 if len(creds) <= 2 else 48      # 3 lines must clear the bottom edge
    for i, line in enumerate(creds):
        rows.append((line, '', 'cred', 110, 930 + cstep * i))
    return rows

# ----------------------------------------------------------------------------
# audio (sound effects only - no BGM)
# ----------------------------------------------------------------------------
def rd_wav(path, sr=44100):
    with wave.open(path, 'rb') as w:
        ch, sw, fr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2: return np.zeros(1, np.float32)
    a = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    if ch > 1: a = a.reshape(-1, ch).mean(axis=1)
    if fr != sr:
        idx = np.linspace(0, len(a) - 1, int(len(a) * sr / fr))
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    return a

def intensity_intervals(threshold):
    """All above-threshold runs, including starts/ends already above the limit.

    The wind interpolator is monotone within each knot interval. Solve each
    crossing separately so even a short dip between two peaks remains silent.
    """
    knots = getattr(S.WF, 'x', S.ihours)
    knots = np.unique(np.clip(np.r_[0.0, knots, S.duration_h], 0.0, S.duration_h))
    cuts = list(knots)
    values = np.asarray(S.WF(knots), dtype=float)
    for left, right, wl, wr in zip(knots[:-1], knots[1:], values[:-1], values[1:]):
        if not (np.isfinite(wl) and np.isfinite(wr)):
            continue
        if (wl >= threshold) == (wr >= threshold):
            continue
        rising = wr >= threshold
        lo, hi = float(left), float(right)
        for _ in range(48):
            mid = (lo + hi) / 2.0
            if (float(S.WF(mid)) >= threshold) == rising:
                hi = mid
            else:
                lo = mid
        cuts.append((lo + hi) / 2.0)
    cuts = sorted(set(cuts))
    runs = []
    for left, right in zip(cuts[:-1], cuts[1:]):
        wind = float(S.WF((left + right) / 2.0))
        if not np.isfinite(wind) or wind < threshold:
            continue
        if runs and runs[-1][1] == left:
            runs[-1] = (runs[-1][0], right)
        else:
            runs.append((left, right))
    return runs


def build_audio():
    os.makedirs(TMP, exist_ok=True)          # sfx() stages converted clips here
    sr = 44100
    n = int(TOTAL * sr)
    mix = np.zeros((n, 2), dtype=np.float32)
    def add(t0, a, gain=1.0, fade=0.15):
        i0 = int(t0 * sr)
        if i0 >= n or i0 < 0: return
        seg = a[:n - i0] * gain
        fl = min(len(seg), int(fade * sr))
        if fl > 0:
            seg[:fl] *= np.linspace(0, 1, fl)
            seg[-fl:] *= np.linspace(1, 0, fl)
        mix[i0:i0 + len(seg), 0] += seg
        mix[i0:i0 + len(seg), 1] += seg
    def tile(t0, t1, a, gain):
        if t1 <= t0: return
        L = int((t1 - t0) * sr)
        loop = np.tile(a, int(L / max(1, len(a))) + 2)[:L].copy()
        add(t0, loop, gain, fade=0.4)
    cache = {}
    def sfx(rel, norm=False):
        key = (rel, norm)
        if key not in cache:
            wv = os.path.join(TMP, os.path.basename(rel) + '.wav')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i',
                            os.path.join(ASSETS, rel.replace('/', os.sep)),
                            '-ac', '1', '-ar', str(sr), wv], check=True)
            a = rd_wav(wv, sr)
            if norm:                       # peak-normalise the landfall hits
                a = a / (float(np.max(np.abs(a))) or 1.0)
            cache[key] = a
        return cache[key]
    # TD -> TS upgrade: one hit per crossing
    for hx in _ts_fx_hours():
        add(t_of_hours(hx), sfx('sound/random/note_ts.ogg'), 0.70 * 2 / 3, 0.1)
    # Each qualifying run gets its own bed; never bridge a weaker interval.
    for start, end in intensity_intervals(113.0):
        tile(t_of_hours(start), t_of_hours(end),
             sfx('sound/random/noice_category4.ogg'), 0.34 * 2 / 3)
    # above 170 kt sustained (lowered)
    for start, end in intensity_intervals(170.0):
        tile(t_of_hours(start), t_of_hours(end),
             sfx('sound/random/noice_170.ogg'), 0.42 * 2 / 3)
    # rapid intensification
    for e in RI_EVENTS:
        if e[4]:
            add(t_of_hours((e[0] + e[1]) / 2.0) - RI_FX_DUR / 2.0,
                sfx('sound/random/Rapid Intensification.ogg'), 0.70, 0.05)
    # landfall hits: the clip is chosen from the category at that moment, and the
    # gain falls off with category so a C5 strike does not bury a C1 one
    LF_GAIN = {'TD': 0.90, 'TS': 1.00, 'C1': 0.95, 'C2': 0.95, 'C3': 0.70,
               'C4': 0.50, 'C5': 0.35, 'C5+': 0.35, 'C5++': 0.32}
    # every category has its own hit; only a non-tropical phase brings none
    LF_FILE = {'TD': 'TD', 'TS': 'TS', 'C1': 'C1', 'C2': 'C2', 'C3': 'C3',
               'C4': 'C4', 'C5': 'C5', 'C5+': 'C6', 'C5++': 'C6'}
    for lf in LANDFALLS:
        if not lf.get('fx'):            # depression / remnant / extratropical:
            continue                    # no landfall event, so no sound either
        wv = float(np.interp(lf['h'], S.ihours, S.iwind))
        lvl = lf.get('lvl') or level_of(wv, _phase_at(lf['h']))
        snd = LF_FILE.get(lvl, 'C1')
        if snd:
            add(t_of_hours(lf['h']),
                sfx('landfall/sound.landfall.%s.ogg' % snd, norm=True),
                LF_GAIN.get(lvl, 0.6), 0.02)
    if _c('audio.weaken', True):
        add(t_of_hours(KEY['landfall']) + 0.35, sfx('sound/random/weaken.ogg'),
            0.55 * 2 / 3, 0.2)
    # damage events (lowered)
    for e in DAMAGE:
        add(e['t'], sfx('sound/damages/sweep1.ogg'), 0.65 * 2 / 3, 0.02)
    # soft limiter instead of hard peak normalisation, so the quieter beds
    # are not crushed by the landfall hit
    a = np.abs(mix)
    over = a > 0.82
    mix[over] = np.sign(mix[over]) * (0.82 + 0.1 * np.tanh((a[over] - 0.82) / 0.1))
    mix *= 0.88
    pk = float(np.max(np.abs(mix)))
    with wave.open(WAV, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((mix * 32767).astype('<i2').tobytes())
    print('audio ->', WAV, 'peak %.2f' % pk)
    for e in DAMAGE:
        print('   damage %-14s min dist %6.0f km at h=%5.1f  (t=%5.1f s)' %
              (e['cn'], e['km'], e['h'], e['t']))

# ----------------------------------------------------------------------------
# drivers
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Still overview: copied from season pass 1's basin rules and stage 2 overview.
# Kept local so single remains self-contained; no imports of season scripts.
# ----------------------------------------------------------------------------
_preview_BASIN_PAD_N, _preview_BASIN_PAD_S, _preview_BASIN_PAD_E, _preview_BASIN_PAD_W = (5.0, 10.0, 5.0, 5.0)
_preview_BASIN_META = None

def _preview_basins():
    """{name: dict(w, h, ppd, lon0, lon1, lat0, lat1, file)} from basins.json"""
    global _preview_BASIN_META
    if _preview_BASIN_META is None:
        p = os.path.join(ASSETS, 'map', 'basins.json')
        if not os.path.isfile(p):
            raise SystemExit('map/basins.json not found: %s' % p)
        raw = json.load(open(p, encoding='utf-8'))
        out, miss = ({}, [])
        for name, m in (raw.get('maps') or {}).items():
            f = os.path.join(ASSETS, 'map', 'basins', m.get('file') or name + '.png')
            if not os.path.isfile(f):
                miss.append(name)
                continue
            w, h = (int(m['size'][0]), int(m['size'][1]))
            lon0, lon1 = (float(m['lon'][0]), float(m['lon'][1]))
            lat0, lat1 = (float(m['lat'][0]), float(m['lat'][1]))
            if abs(w / (lon1 - lon0) - h / (lat1 - lat0)) > 0.01:
                print('  basin %-6s window and image disagree - skipped' % name)
                continue
            out[name] = dict(name=name, file=f, w=w, h=h, ppd=w / (lon1 - lon0), lon0=lon0, lon1=lon1, lat0=lat0, lat1=lat1)
        if not out:
            raise SystemExit('no usable basin map under %s' % os.path.join(ASSETS, 'map', 'basins'))
        if miss:
            print('  basins listed but missing on disk: %s' % ', '.join(miss))
        _preview_BASIN_META = out
    return _preview_BASIN_META

def _preview_area(lon0, lon1, lat0, lat1):
    return max(0.0, lon1 - lon0) * max(0.0, lat1 - lat0)

def _preview_coverage(b, lon0, lon1, lat0, lat1):
    """covered area / map area for one basin"""
    i0 = max(lon0, b['lon0'])
    i1 = min(lon1, b['lon1'])
    j0 = max(lat0, b['lat0'])
    j1 = min(lat1, b['lat1'])
    return _preview_area(i0, i1, j0, j1) / _preview_area(b['lon0'], b['lon1'], b['lat0'], b['lat1'])

def _preview_pick_basin(lon_min, lon_max, lat_min, lat_max, verbose=True, fit=None, win=(-180.0, 180.0, -90.0, 90.0)):
    """the basin with the largest covered-area / map-area ratio

    The window is the basin's own rectangle UNION the track grown by the
    padding, so the basin stays the authority and the padding is the patch.
    `fit` is the frame (w, h) the stills/video will use: the window is grown
    about its own centre to that aspect.
    """
    bs = _preview_basins()
    lo0, lo1 = (lon_min - _preview_BASIN_PAD_W, lon_max + _preview_BASIN_PAD_E)
    la0, la1 = (lat_min - _preview_BASIN_PAD_S, lat_max + _preview_BASIN_PAD_N)
    rank = sorted(((_preview_coverage(b, lo0, lo1, la0, la1), b) for b in bs.values()), key=lambda r: -r[0])
    top = [r for r in rank if r[0] > 0.0]
    if top:
        if verbose:
            print('  basin %-7s %.4f (next %s %.4f)  track lon %.1f..%.1f lat %.1f..%.1f' % (top[0][1]['name'], top[0][0], top[1][1]['name'] if len(top) > 1 else '-', top[1][0] if len(top) > 1 else 0.0, lon_min, lon_max, lat_min, lat_max))
        return top[0][1]
    fb = bs.get('EARTH') or max(bs.values(), key=lambda b: b['w'] * b['h'])
    if verbose:
        print('  basin: nothing covers lon %.1f..%.1f lat %.1f..%.1f - using %s' % (lon_min, lon_max, lat_min, lat_max, fb['name']))
    return fb

def _preview_basin_window(b, lon_min, lon_max, lat_min, lat_max):
    """the basin's own window UNION the track grown by the padding"""
    return (min(b['lon0'], lon_min - _preview_BASIN_PAD_W), max(b['lon1'], lon_max + _preview_BASIN_PAD_E), min(b['lat0'], lat_min - _preview_BASIN_PAD_S), max(b['lat1'], lat_max + _preview_BASIN_PAD_N))

def _preview_fit_aspect(win, w, h):
    """grow `win` about its centre until its degree aspect matches the frame

    This only ever ENLARGES the window, so the basin and the track always stay
    inside the frame; it is what stops the map from being stretched to fill it.
    """
    lon0, lon1, lat0, lat1 = win
    want = float(w) / float(h)
    sw, sh = (lon1 - lon0, lat1 - lat0)
    cx, cy = (0.5 * (lon0 + lon1), 0.5 * (lat0 + lat1))
    if sw / sh < want:
        half = math.ceil(0.5 * sh * want * 100.0) / 100.0
        lon0, lon1 = (cx - half, cx + half)
    else:
        half = math.ceil(0.5 * sw / want * 100.0) / 100.0
        lat0, lat1 = (cy - half, cy + half)
    return (lon0, lon1, lat0, lat1)

class _preview_MapSource:
    """crops windows out of the whole-world sheet, at its native resolution"""

    def __init__(self, ps, assets, basin, ss=2):
        self.ss = max(1, int(ss))
        self.basin = basin
        self.world = ps._preview_basins().get('EARTH') or basin
        p = self.world['file']
        if not os.path.isfile(p):
            raise SystemExit('map not found: %s' % p)
        Image.MAX_IMAGE_PIXELS = None
        self.im = Image.open(p).convert('RGB')
        self.native = self.im.size
        self._cache = {}
        print('  sheet %s  %dx%d  %.1f px/deg   (basin rule -> %s)' % (os.path.basename(p), self.native[0], self.native[1], self.world['ppd'], basin['name']))

    def _crop_layer(self, lon0, lon1, lat0, lat1, W, H, allow_up):
        """the window, returned exactly WxH.

        The integer floor/ceil box around the window is cropped at the sheet's
        own resolution; PIL's float `box` then takes the sub-pixel edges; one
        final LANCZOS step lands on the exact frame size.  `allow_up` lets a wide
        overview supersample, while a narrow crop - which already has more source
        pixels than it needs - never upsamples.
        """
        key = (round(lon0, 4), round(lon1, 4), round(lat0, 4), round(lat1, 4), W, H, allow_up)
        if key in self._cache:
            return self._cache[key]
        b = self.world
        im = self.im
        nw, nh = im.size
        ppd = b['ppd']
        fx0, fx1 = ((lon0 - b['lon0']) * ppd, (lon1 - b['lon0']) * ppd)
        fy0, fy1 = ((b['lat1'] - lat1) * ppd, (b['lat1'] - lat0) * ppd)
        if fx0 < 0.0 or fx1 > nw or fy0 < 0.0 or (fy1 > nh):
            print('  ! window lon %.1f..%.1f lat %.1f..%.1f leaves the world sheet' % (lon0, lon1, lat0, lat1))
        fx0 = max(0.0, min(nw - 1.0, fx0))
        fx1 = max(1.0, min(float(nw), fx1))
        fy0 = max(0.0, min(nh - 1.0, fy0))
        fy1 = max(1.0, min(float(nh), fy1))
        ix0, ix1 = (int(math.floor(fx0)), int(math.ceil(fx1)))
        iy0, iy1 = (int(math.floor(fy0)), int(math.ceil(fy1)))
        ix0 = max(0, min(nw - 2, ix0))
        ix1 = min(nw, max(ix0 + 1, ix1))
        iy0 = max(0, min(nh - 2, iy0))
        iy1 = min(nh, max(iy0 + 1, iy1))
        cw, ch = (ix1 - ix0, iy1 - iy0)
        sub = (fx0 - ix0, fy0 - iy0, fx1 - ix0, fy1 - iy0)
        scale = 1
        if allow_up > 1:
            scale = max(1, min(int(allow_up), int(math.ceil(W / float(cw)))))
        crop = im.crop((ix0, iy0, ix1, iy1))
        if scale > 1:
            crop = crop.resize((cw * scale, ch * scale), Image.BICUBIC)
        out = crop.resize((W, H), Image.LANCZOS, box=tuple((v * scale for v in sub))).convert('RGB')
        if out.size != (W, H):
            out = out.resize((W, H), Image.LANCZOS)
        self._cache[key] = out
        return out

    def crop(self, lon0, lon1, lat0, lat1, W, H, basin=None):
        """RGB array (H,W,3) of the world sheet over the window"""
        return np.asarray(self._crop_layer(lon0, lon1, lat0, lat1, int(W), int(H), self.ss), dtype=np.uint8)

def _preview_make_proj(lon0, lon1, lat0, lat1, W, H):

    def proj(lon, lat):
        return ((lon - lon0) / (lon1 - lon0) * W, (lat1 - lat) / (lat1 - lat0) * H)
    return proj
_preview_BANDS = [('TD', 0, 33), ('TS', 34, 63), ('C1', 64, 82), ('C2', 83, 95), ('C3', 96, 112), ('C4', 113, 136), ('C5', 137, 155), ('C5+', 156, 169), ('C5++', 170, 999)]
_preview_TRANS_K = 3.5
_preview_ICON_BLEND_KT = 14.0
_preview_TRANS_H = 2.5
_preview_COL = {'DB': (206, 220, 236), 'TD': (196, 220, 255), 'TS': (58, 226, 92), 'C1': (255, 232, 40), 'C2': (255, 158, 30), 'C3': (244, 86, 32), 'C4': (232, 34, 28), 'C5': (255, 60, 226), 'C5+': (214, 106, 255), 'RV': (176, 192, 214), 'EX': (152, 172, 214)}
_preview_COL.update({k: COL[k] for k in ('MV', 'MD', 'SD', 'SS')})
_preview_C5PP_A = np.array([126, 44, 176], dtype=np.float32)
_preview_C5PP_B = np.array([40, 74, 178], dtype=np.float32)
_preview_C6_END = np.array([198, 232, 255], dtype=np.float32)

def _preview_theme_col(wind, lvl):
    """155 kt+ uses the super-cyclone ramp: pink-purple -> deep blue at 185 kt
    -> ACE fill endpoint (#C6E8FF) at 200 kt, linear in between"""
    if lvl == 'C5++' and wind > 200:
        return palette_colour(wind, HIGHWIND_BODY)
    if lvl == 'C5++':
        if wind <= 185.0:
            t = min(1.0, max(0.0, (wind - 170.0) / 15.0))
            return tuple((int(v) for v in _preview_C5PP_A * (1 - t) + _preview_C5PP_B * t))
        t = min(1.0, (wind - 185.0) / 15.0)
        return tuple((int(v) for v in _preview_C5PP_B * (1 - t) + _preview_C6_END * t))
    return _preview_COL.get(lvl, (220, 220, 220))

def _preview_intensity_weights(w):
    out = {}
    for lvl, lo, hi in _preview_BANDS:
        d = max(0.0, lo - w, w - hi)
        a = math.exp(-(d / _preview_ICON_BLEND_KT) ** 2)
        if a > 0.004:
            out[lvl] = a
    tot = sum(out.values())
    if tot <= 0.0:
        return {_preview_BANDS[-1][0]: 1.0}
    return {k: v / tot for k, v in out.items()}

def _preview_phase_side(ph, w):
    return _preview_intensity_weights(w) if ph == 'TC' else {level_of(w, ph): 1.0}

def _preview_state_weights(ps, h, w):
    for hb, pa, pb in ps.PHASE_BOUNDS:
        if abs(h - hb) <= _preview_TRANS_H:
            t = (h - (hb - _preview_TRANS_H)) / (2.0 * _preview_TRANS_H)
            out = {}
            for k, v in _preview_phase_side(pa, w).items():
                out[k] = out.get(k, 0.0) + v * (1.0 - t)
            for k, v in _preview_phase_side(pb, w).items():
                out[k] = out.get(k, 0.0) + v * t
            return out
    ph = _preview_phase_at(ps, h)
    base = _preview_intensity_weights(w) if ph == 'TC' else {level_of(w, ph): 1.0}
    for h0, h1, _l0, _l1, _fx in ps.RI_EVENTS:
        if h0 <= h <= h1 and h1 > h0:
            e = 1.0 / max(1e-06, ps.RI_BLEND_FRAC)
            out = {k: v ** e for k, v in base.items()}
            tot = sum(out.values()) or 1.0
            return {k: v / tot for k, v in out.items()}
    return base

def _preview_phase_at(ps, h):
    ph = ps.PHASE_BOUNDS[0][1] if ps.PHASE_BOUNDS else 'TC'
    for hb, pa, pb in ps.PHASE_BOUNDS:
        if h > hb:
            ph = pb
    return ph

def _preview_state_color(ps, h, w, sw):
    c = np.zeros(3, dtype=np.float32)
    tot = sum(sw.values()) or 1.0
    for lvl, wt in sw.items():
        c += wt / tot * np.array(_preview_theme_col(w, lvl), dtype=np.float32)
    return tuple((int(v) for v in np.clip(c, 0, 255)))

def _preview_sample(ps, h):
    """the pass 1 sampler, bound to the storm currently installed in `ps`"""
    S = ps.S
    h = float(max(0.0, min(S.duration_h, h)))
    i = int(np.searchsorted(S.hours, h, 'right')) - 1
    i = max(0, min(len(S.hours) - 2, i)) if len(S.hours) > 1 else 0
    span = float(S.hours[i + 1] - S.hours[i]) if len(S.hours) > 1 else 1.0
    s = 0.0 if span <= 0 else (h - S.hours[i]) / span

    def cr(arr):
        p1 = arr[i]
        p0 = arr[max(0, i - 1)]
        p2 = arr[min(len(arr) - 1, i + 1)]
        p3 = arr[min(len(arr) - 1, i + 2)]
        return 0.5 * (2 * p1 + (-p0 + p2) * s + (2 * p0 - 5 * p1 + 4 * p2 - p3) * s * s + (-p0 + 3 * p1 - 3 * p2 + p3) * s * s * s)
    lon = cr(S.lon)
    lat = cr(S.lat)
    wind = float(S.WF(h))
    pres = float(S.PF(h))
    ace = float(np.interp(h, S.hours, S.ace))
    ph = S.phase[min(len(S.phase) - 1, int(np.searchsorted(S.hours, h, 'right')) - 1)]
    return (lon, lat, wind, pres, ace, ph)

def _preview_dashed(d, pts, fill, width, dash=16, gap=11):
    on, acc = (True, 0.0)
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg <= 0.01:
            continue
        t = 0.0
        while t < seg - 0.01:
            want = dash if on else gap
            step = min(want - acc, seg - t)
            if on and step > 0.5:
                xa = x0 + (x1 - x0) * (t / seg)
                ya = y0 + (y1 - y0) * (t / seg)
                xb = x0 + (x1 - x0) * ((t + step) / seg)
                yb = y0 + (y1 - y0) * ((t + step) / seg)
                d.line([xa, ya, xb, yb], fill=fill, width=width)
            t += step
            acc += step
            if acc >= want - 1e-06:
                on = not on
                acc = 0.0

def _preview_trail(ps, ov, hours, proj, sc, trail_mul):
    """pass 1's `trail()` with the fix markers left out.

    The preview-only trail uses 30% of the original width: no outer stroke, intensity-coloured inner
    stroke whose colour is sampled continuously, and the remnant-vortex phase
    dashed.  Only the per-fix black discs are gone.
    """
    S = ps.S
    d = ImageDraw.Draw(ov)
    w_in = max(1, int(round(6 * trail_mul * sc * 0.30)))
    a_in = 255
    pts = []
    h = 0.0
    while h < hours - 1e-06:
        h = min(hours, h + 0.8)
        lo, la, w, p, a, ph = _preview_sample(ps, h)
        pts.append((h, lo, la))
    lo, la, w, p, a, ph = _preview_sample(ps, hours)
    pts.append((hours, lo, la))
    cols = []
    for hh, _, _ in pts:
        _, _, ww, _, _, _ = _preview_sample(ps, hh)
        cols.append(_preview_state_color(ps, hh, ww, _preview_state_weights(ps, hh, ww)))
    xy = [proj(p[1], p[2]) for p in pts]
    if len(xy) > 1:

        def is_rv(i):
            return _preview_phase_at(ps, pts[i][0]) == 'RV'
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
                _preview_dashed(d, rp, cols[idx[-1]] + (a_in,), w_in)
            else:
                for a, b in zip(idx[:-1], idx[1:]):
                    d.line([xy[a], xy[b]], fill=cols[b] + (a_in,), width=w_in)

def _preview_style_scale(win, W, ps):
    """the renderer's own line-weight rule:
           SC = (px per degree) / (1920 / SPAN0_LON)
    A follow camera draws 1920 px over 22.8 deg; a season still draws W px over
    the whole crop, so its line is thinner by exactly that ratio."""
    ppd = W / float(win[1] - win[0])
    return ppd / (1920.0 / 22.8)

def cmd_preview():
    """Write output/preview.png without decoding effects or encoding video."""
    ps = sys.modules[__name__]
    width, height = 1920, 1080
    extent = (float(S.lon.min()), float(S.lon.max()),
              float(S.lat.min()), float(S.lat.max()))
    basin = _preview_pick_basin(*extent, fit=(width, height))
    window = _preview_fit_aspect(_preview_basin_window(basin, *extent), width, height)
    # Keep the established window; output at the source sheet's native density.
    source = _preview_basins().get('EARTH') or basin
    width = max(1, int(round((window[1] - window[0]) * source['ppd'])))
    height = max(1, int(round((window[3] - window[2]) * source['ppd'])))
    print('  native preview %dx%d at %.1f px/deg' % (width, height, source['ppd']))
    maps = _preview_MapSource(ps, ASSETS, basin, ss=1)
    try:
        frame = Image.fromarray(maps.crop(*window, width, height)).convert('RGBA')
        projection = _preview_make_proj(*window, width, height)
        layer = Image.new('RGBA', frame.size, (0, 0, 0, 0))
        scale = _preview_style_scale(window, width, ps)
        _preview_trail(ps, layer, float(S.duration_h), projection, scale, 3.0)
        frame.alpha_composite(layer)
        path = os.path.join(OUTDIR, 'preview.png')
        temporary = os.path.join(OUTDIR, 'preview.pending.png')
        try:
            frame.convert('RGB').save(temporary, format='PNG')
            os.replace(temporary, path)
        finally:
            if os.path.isfile(temporary): os.remove(temporary)
        print('preview -> %s  basin %s  lon %.2f..%.2f lat %.2f..%.2f' %
              ((path, basin['name']) + tuple(window)))
        return path
    finally:
        maps.im.close()

def cmd_assets():
    extract_icons(); extract_fx(); extract_ex_lightning(); extract_cloud()

def cmd_test():
    os.makedirs(TMP, exist_ok=True)
    r = R()
    pk = _D.get('peaks') or [{'h': S.duration_h}]
    lf = LANDFALLS or [{'h': S.duration_h}]
    shots = [('intro', 2.4), ('start', INTRO + 1.0)]

    def ev(h, name, dt=0.3):                    # a moment shortly after a data hour
        shots.append((name, t_of_hours(h) + dt))

    ev(KEY['ts'], 'td2ts', 0.15)
    if RI_EVENTS:
        ev(RI_EVENTS[0][0], 'ri', 0.12)
        ev((RI_EVENTS[-1][0] + RI_EVENTS[-1][1]) / 2.0, 'ri_mid')
    for i, p in enumerate(pk[:4]):
        ev(p['h'], 'peak%d' % (i + 1))
    if len(pk) > 1:
        ev((pk[0]['h'] + pk[1]['h']) / 2.0, 'ph')
    if DAMAGE:
        ev(DAMAGE[0]['h'], 'dmg_1')
    for i, l in enumerate(lf):
        ev(l['h'], 'landfall%d' % (i + 1))
    if DAMAGE:
        ev(DAMAGE[-1]['h'] + 4, 'damage_last')
    ev(S.duration_h * 0.85, 'remnant')
    shots += [('cloudgap', INTRO + 35.0), ('end', T_MAIN - 0.3),
              ('pull', T_MAIN + PULL * 0.55), ('pano', T_PULL + 0.5)]
    # No end-card probes while its reserved duration is zero.
    if SUMMARY > 0:
        shots += [('summary', T_SUM + SUMMARY * 0.35),
                  ('summary_end', T_SUM + SUMMARY * 0.9)]
    for nm, t in shots:
        print('test', nm, int(t * FPS))
        r.render(int(t * FPS)).save(os.path.join(TMP, 'frame_%s.png' % nm))
    print('test frames ->', TMP)

def cmd_poster():
    r = R()
    pk = _D.get('peaks') or [{'h': S.duration_h}]
    r.render(int(t_of_hours(pk[-1]['h'] + 0.6) * FPS)).save(POSTER)
    print('poster ->', POSTER)

def cmd_render():
    output_w = int(_c('output.width', OUTPUT_W))
    output_h = int(_c('output.height', OUTPUT_H))
    output_fps = int(_c('output.fps', FPS))
    if not 1 <= output_fps <= FPS:
        raise ValueError('Output fps must be an integer from 1 to %d' % FPS)
    output_frames = int(round(TOTAL * output_fps))
    if output_w <= 0 or output_h <= 0 or output_w % 2 or output_h % 2:
        raise ValueError('Output width and height must be positive even integers')
    scale_args = (['-vf', 'scale=%d:%d:flags=lanczos' % (output_w, output_h)]
                  if (output_w, output_h) != (W, H) else [])
    # Always finish the reviewable still before any video process starts.
    cmd_preview()
    if cv2 is None:
        raise SystemExit("Video rendering requires opencv-python; preview.png is ready.")
    r = R()
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt',
                          'rgb24', '-s', '%dx%d' % (W, H), '-r', str(output_fps), '-i', '-',
                          '-an'] + scale_args + [
                          '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
                          '-pix_fmt', 'yuv420p', '-movflags', '+faststart', RAWM],
                         stdin=subprocess.PIPE)
    import time as _t
    t0 = _t.time()
    for i in range(output_frames):
        source_frame = min(NFRAMES - 1, int(round(i * FPS / float(output_fps))))
        p.stdin.write(r.render(source_frame).tobytes())
        if i % output_fps == 0:
            el = _t.time() - t0
            with open(os.path.join(BUILD, 'render_progress.json'), 'w', encoding='utf-8') as progress:
                json.dump(dict(frames=i+1, total=output_frames, elapsed=el,
                               eta=el/max(1,i+1)*(output_frames-i-1), fps=output_fps,
                               width=output_w, height=output_h), progress)
            print('  %5d/%d  %6.1fs  eta %6.1fs' % (i, output_frames, el,
                  el / max(1, i + 1) * (output_frames - i - 1)), flush=True)
    p.stdin.close()
    if p.wait() != 0: raise RuntimeError('Video encoder failed')
    print('silent ->', RAWM)

def cmd_mux():
    build_audio()
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', RAWM, '-i', WAV,
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    '-movflags', '+faststart', OUTMP4], check=True)
    print('final ->', OUTMP4)

def main(argv):
    # storm names and region labels are CJK: never let a legacy console code
    # page (GBK, cp1252 ...) abort a render
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    cfg_path, cmd = 'typhoon.yaml', 'all'
    i, positional = 0, []
    while i < len(argv):
        a = argv[i]
        if a == '--config':
            cfg_path = argv[i + 1]; i += 2; continue
        if a.startswith('--config='):
            cfg_path = a.split('=', 1)[1]; i += 1; continue
        positional.append(a); i += 1
    if positional:
        cmd = positional[0]
    _apply_config(_load_config(cfg_path))
    _bind_paths()
    _cfg_span()
    _build()
    _auto_panorama()
    print('storm %s / %s    %d points   %.0f h   ACE %.2f' %
          (_S.get('id', ''), _S.get('name_en', ''), len(S.hours),
           S.duration_h, S.ace_total))
    if cmd == 'preview':
        cmd_preview()
    elif cmd == 'assets':
        cmd_assets()
    elif cmd == 'test':
        cmd_test()
    elif cmd == 'poster':
        cmd_poster()
    elif cmd == 'render':
        cmd_render()
    elif cmd == 'audio':
        build_audio()
    elif cmd == 'mux':
        cmd_mux()
    elif cmd == 'info':
        pk = _D.get('peaks') or []
        for k, p in enumerate(pk):
            print('  peak%d  h=%6.1f  %d kt / %d hPa' %
                  (k + 1, p['h'], np.interp(p['h'], S.ihours, S.iwind),
                   np.interp(p['h'], S.ihours, S.ipres)))
        if KEY['w170a'] is None:
            print('  never reaches 170 kt')
        else:
            print('  w>170 kt from h=%.2f to h=%.2f' %
                  (KEY['w170a'], S.duration_h if KEY['w170b'] is None else KEY['w170b']))
        print('  banner art: %s   peak %.0f kt (%s)'
              % (banner_asset(), peak_wind(), level_of(peak_wind(), 'TC')))
        print('  TD->TS crossings: %s'
              % (', '.join('h=%.0f' % x for x in _ts_fx_hours()) or 'none'))
        def _hv(v):
            return 'n/a' if v is None else 'h=%.2f' % v
        print('  TD->TS %s   TS->C1 %s   C4 %s   C5end %s'
              % (_hv(KEY['ts']), _hv(KEY['c1']), _hv(KEY['c4']), _hv(KEY['c5end'])))
        for lf in LANDFALLS:
            print('  landfall %-24s h=%6.1f  %3.0f kt (%s)'
                  % (lf['place'], lf['h'], lf.get('wind', 0), lf.get('lvl', '')))
        for e in DAMAGE:
            print('  damage   %-24s h=%6.1f  %6.0f km  t=%5.1f s  dead+miss=%d  loss=%s'
                  % (e['cn'], e['h'], e['km'], e['t'], e['dead'] + e['lost'],
                     e.get('loss_text') or e['loss']))
    elif cmd == 'all':
        cmd_assets(); cmd_render(); cmd_mux()
    else:
        print(__doc__)

if __name__ == '__main__':
    main(sys.argv[1:])

