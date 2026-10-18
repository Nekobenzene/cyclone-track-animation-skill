"""PASS 2 - the data layer: the season's cards and timeline, over a plate.

    python season_pass2.py info
    python season_pass2.py preview --base black --size 1920x1080 --at 2020-11-01
    python season_pass2.py preview --base map  --size 8534x4800 --at 2020-10-31T06
    python season_pass2.py render  --base black --size 960x540 --fps 30 --out x.mp4
    python season_pass2.py render  --base <edited plate>.mp4 --size 8534x4800 --fps 120

WHAT THIS IS
------------
Stage 6 of the season pipeline. It draws the season's data - five cards and a
timeline - and composites them over a base it did NOT draw. The base is either
`black` (the standalone data layer, the pure-colour-base channel) or a finished
cut. The base's TIMING IS NEVER TOUCHED: the overlay reads the frame index and
nothing else, which is why it still works after stage 5 has cut the plate about.

The original `season_pass2.py` was a copy of the whole pass 1 renderer with the
data layer appended - 317 code objects, about 200 KB. This is not that. No map,
no track, no icon, no camera, no cloud, on purpose.

THE CARDS
---------
Left column, top to bottom, all 480 wide at x=10, in 1920x1080 author units:

    identity  (10,  10, 480,  80)   WPAC <year>, then the UTC date and clock
    damage    (10,  96, 480,  94)   two bars: deaths, and direct loss
    ACE       (10, 196, 480, 264)   the rate curve, the cumulative curve, the
                                    ACE ruler and its caption, one panel
    tally     (10, 466, 480, 146)   five rulers stacked, one per category
    timeline  (60, 930, 1800, 140)  a baseline, month ticks and a pointer

plus the SUMMARY BANNER: single's panorama bar, one per storm, entering at the
top right the instant that storm dissipates. It is the one element of this layer
that is not a read-out of the season as a whole - it announces a single system -
and it stacks when two storms end close together.

The column is DERIVED - each card starts `_COL_GAP` below the one above it - so
the stack cannot come apart when one card is resized. Everything is author units
multiplied by `sc = W / 1920`; a bare pixel count anywhere is a bug.

Each card's panel, wells, grid, month names and static labels are rasterised ONCE
into `self._static` and blitted. Only what carries a value is drawn per frame. The
one exception is the bars' WHITE FRAMES: those go into `self._frame_rects` and are
drawn at the very END of `frame()`, after every fill, because a frame baked under
its own bar is painted over by it.

WHAT THE NUMBERS MEAN
---------------------
* **ACE rate** is REAL TIME, not a difference: at each instant it is the sum over
  the systems on the field of `4/1e4 * v^2`, i.e. what the season is producing
  right now, in ACE units per day. Same 34 kt gate as the cumulative curve beside
  it. The curve is sampled on the hourly grid `rate` lives on - not once per
  pixel column - and then decimated once. See `_build_rate_curve` for why both
  halves of that matter, and `p2_curves` for why the rate is not a difference.
* **Deaths and loss** are cumulative and booked 6 h after each storm dissipates.
  Both print THREE SIGNIFICANT FIGURES; deaths keep the exact count below ten
  thousand and switch to 万人 above it, because three figures are a big-number
  rule there and not a general one.
* **The tally** is five INDEPENDENT criteria - C5/MH/HU on the peak reached so
  far, TS on the JMA name, TD on the JTWC number - each counted cumulatively. A
  system joins a ruler when it gets there and never leaves, which is free because
  a running maximum never falls. The five do not have to nest, and when they do
  not it is not a bug.

MEASURED
--------
Drawing the data layer costs, per frame, and is independent of the OUTPUT size
because it is drawn on a bounded canvas:

    render_w  1920    11.8 ms/frame
    render_w  3840    28.8 ms/frame   <- the default, `min(3840, max(1920, W))`
    render_w  8534   177.5 ms/frame   <- native 8K
    render_w 17068  1032.7 ms/frame   <- native 16K, over any sane budget

`render_w` is capped at 3840, so at an 8534-wide output the layer is drawn at 3840
and upscaled 2.22x. Rendering it natively at 8K was compared at 1:1 and 2-3x zoom
and is not visibly better, so the cap stays: it is what keeps 16K possible at all.

A separate pass costs what decode and re-encode cost: 358 ms/frame at 8K for the
2020 season. 120 fps is unreachable on this machine at 8K - x264 alone needs
166 ms/frame there - so the goal met here is "does not slow the plate down".
"""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

# Shared skill runtime; each renderer remains self-contained.
_SKILL_SHARED = os.environ.get('TYPHOON_SKILL_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SKILL_DEPS = os.path.join(_SKILL_SHARED, 'runtime', 'python')
if not getattr(sys, 'frozen', False) and os.path.isdir(_SKILL_DEPS):
    sys.path.insert(0, _SKILL_DEPS)
    os.environ['PYTHONPATH'] = _SKILL_DEPS + os.pathsep + os.environ.get('PYTHONPATH', '')
os.environ['PATH'] = os.path.join(_SKILL_SHARED, 'runtime', 'bin') + os.pathsep + os.environ.get('PATH', '')
_SKILL_ASSETS = os.path.join(_SKILL_SHARED, 'assets', 'SMCY1.3')

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

# ---------------------------------------------------------------------------
# the ACE-rate colour ramp
# ---------------------------------------------------------------------------
# `resources/acerate.png` is 14 FIXED colour nodes with RGB interpolated linearly
# between them, so this table is the exact description of the asset rather than a
# resampling of it - and sampling the bitmap would tie the ramp to its 776-row
# length and to PNG quantisation. The nodes were recovered from the strip once,
# by a fitter that is not shipped; this table is the result and is what the
# renderer uses.
#
# `u` runs 0 -> 1 from ZERO RATE to the top of the scale, i.e. cold to hot, which
# is the direction the left axis is labelled. The strip itself runs hot at the
# top, so the u values ascend as the strip's rows descend. ASCENDING order is
# required by the scalar lookup below AND by the vectorised form in `_heat_arr`.
ACERATE_NODES = (
    (0.000000, 213, 241, 255),   # strip row 775
    (0.107097,  72, 193, 252),   # strip row 692
    (0.233548,  68, 250,  20),   # strip row 594
    (0.242581,  69, 255,   1),   # strip row 587
    (0.245161,  71, 255,   0),   # strip row 585
    (0.250323,  83, 255,   0),   # strip row 581
    (0.313548, 238, 255,   0),   # strip row 532
    (0.450323, 255, 247,   0),   # strip row 426
    (0.656774, 255, 125,   0),   # strip row 266
    (0.794839, 255,   1,   0),   # strip row 159
    (0.914839, 152,   0, 147),   # strip row 66
    (0.934194, 135,   0, 171),   # strip row 51
    (0.993548,  83,   0, 245),   # strip row 5
    (1.000000,  79,   0, 251),   # strip row 0
)


def acerate_lookup(u, nodes=ACERATE_NODES):
    """Colour at `u` in 0..1, RGB linear between the two nearest nodes."""
    if u <= nodes[0][0]:
        return nodes[0][1], nodes[0][2], nodes[0][3]
    if u >= nodes[-1][0]:
        return nodes[-1][1], nodes[-1][2], nodes[-1][3]
    for i in range(len(nodes) - 1):
        u0, r0, g0, b0 = nodes[i]
        u1, r1, g1, b1 = nodes[i + 1]
        if u <= u1:
            t = (u - u0) / (u1 - u0) if u1 > u0 else 0.0
            return (r0 + (r1 - r0) * t,
                    g0 + (g1 - g0) * t,
                    b0 + (b1 - b0) * t)
    return nodes[-1][1], nodes[-1][2], nodes[-1][3]

_dtm = datetime

# ---------------------------------------------------------------------------
# frozen constants, verbatim from the original
# ---------------------------------------------------------------------------

# season_pass2.py 3905-3907
P2_LAY = dict(title=(60, 34), stats=(60, 140, 620, 232), ace=(1240, 140, 620, 232),
              bot=(700, 620, 232), timeline=(60, 1860, 990))

# season_pass2.py 3907-3909
P2_C = dict(panel=(7, 11, 22, 205), edge=(255, 255, 255, 92), txt=(232, 240, 252),
            dim=(150, 163, 184), grey=(168, 176, 190), green=(92, 220, 130),
            yellow=(250, 205, 80), red=(248, 96, 96), loss=(250, 214, 96))

# season_pass2.py 3898-3901
P2_EASE_S = 1.5
P2_BOOK_H = 6.0
P2_HEAT_MAX = 10.0

# The wind a system must reach to count towards ACE - the 34 kt gate `Series.ace`
# already applies to the cumulative curve, so the rate above it and the cumulative
# line beside it are the same metric. Setting this to 0.0 counts every depression
# for the whole of its life: the 2020 season then integrates to 167.4 against the
# 153.3 it books, and two curves on one plot disagree about what ACE is.
P2_ACE_MIN_KT = 34.0

# ---- the summary banner ----------------------------------------------------
#
# Single's panorama banner brought into the season layer: one bar per storm,
# entering the instant that storm dissipates. Same art
# (`summary/Summary-N-TC-<peak level>.mp4`), same two printed lines, same
# slide-and-fade - but smaller, parked in the TOP-RIGHT corner, and STACKED,
# because a season has storms ending within a day of each other while single
# only ever has one on screen.
#
# Everything here is author units at 1920x1080 times `sc`, like the cards: the
# banner is screen furniture, so it rides the FRAME and never the icon.
BAN_W = 1400.0                 # the card's width; its art is 20:1, as single's is
BAN_H = 70.0
BAN_RIGHT = 24.0               # right margin
BAN_TOP = 20.0                 # top margin
BAN_GAP = 6.0                  # between stacked banners
BAN_SLIDE = 460.0              # how far right of home a banner enters from
BAN_IN_S = 0.8                 # slide in + fade in
BAN_HOLD_S = 3.0               # fully in, then the exit starts
BAN_OUT_S = 0.8                # slide out + fade out
BAN_RISE_DELAY = 0.3           # after an exit starts, before the rest rise
BAN_RISE_S = 0.5               # the rise itself
BAN_RISE_STAGGER = 0.1         # each banner further down starts this much later
BAN_REF_W = 1700.0             # single's card width; its type is quoted at that
BAN_FRAMES = 300               # 5 s of banner art at its own 60 fps

F_SAIRA = os.path.join(_SKILL_ASSETS, 'font', '_saira_master', 'Saira', 'fonts', 'ttf')
F_BAN_EN = os.path.join(F_SAIRA, 'Saira-Bold.ttf')
F_BAN_MONO = os.path.join(F_SAIRA, 'Saira-Bold.ttf')
F_SOURCE_HAN = os.path.join(_SKILL_ASSETS, 'font', 'SourceHanSansSC')
F_BAN_CJK = os.path.join(F_SOURCE_HAN, 'SourceHanSansSC-Bold.otf')

# season_pass2.py 4488: the tally's own colours, which are NOT P2_C.
#
# FIVE categories, listed in DESCENDING intensity - which is the order the rulers
# are STACKED in (C5 on top) and the order their labels read.
#
# THE FIVE ARE INDEPENDENT FLAGS, not rungs of one ladder, and each is counted on
# its own:
#
#   C5   peak reaches 137 kt       Saffir-Simpson 5
#   MH   peak reaches  96 kt       3-4
#   HU   peak reaches  64 kt       1-2
#   TS   NAMED                     (JMA)
#   TD   OFFICIALLY NUMBERED       (JTWC, 01W 02W ...)
#
# 96 and 64 are the original's own two thresholds and they are the Saffir-Simpson
# 3 and 1 boundaries, so the intensity half of this is one scale. 137 is the only
# new number.
#
# TD and TS are AGENCY decisions and the other three are wind speeds, which is why
# the five counts need not nest. JTWC numbers and JMA names independently, so a
# system can be named before it is numbered, or reach hurricane force without ever
# being named; when that happens a LOWER ruler can be shorter than a higher one
# and it is not a bug. Normally C5 <= MH <= HU <= TS <= TD.
#
# A count is CUMULATIVE up the stack: the number beside MH is every system that has
# reached MH, not only those whose current category is MH. With the normal nesting
# that is the same as summing the categories from the top, which is how a tally of
# this shape is normally read.
#
# The three colours that come from the icons are READ OFF THE ICON VIDEOS, not
# eyeballed: `assets/mainicon/tc_sshws/N-TC-C{1,3,5}.mp4`, the dominant colour of
# the disc across the whole clip (28 frames, pixels with chroma > 110, mode of the
# 4-quantised histogram - hundreds of thousands of pixels each, so the read is
# solid):
#
#     N-TC-C1.mp4   #FCFC34  (252, 252,  52)  hue  60 deg   bright yellow
#     N-TC-C3.mp4   #FC8000  (252, 128,   0)  hue  30 deg   orange
#     N-TC-C5.mp4   #FC14FC  (252,  20, 252)  hue 300 deg   magenta
#
# The floors come from the same place, same method:
#
#     N-TC-TS.mp4   #08FC00  (  8, 252,   0)  hue 118 deg   green
#     N-TD-D.mp4    #4064C8  ( 64, 100, 200)  hue 224 deg   blue
#
# TD is the one read with a caveat: the icon is dark and only 35k of its pixels
# clear the chroma gate, and its own value is 0.78 rather than 0.99 (the other
# four are all full-value). It is still the clear mode by 8x, and on the panel it
# reads as blue rather than as a shade of the panel - which pure grey did not.
#
# The `Cx-.mp4` / `Cx+.mp4` / `C6(n).mp4` variants are deliberately NOT used -
# only the plain `Cx.mp4`, and TS/TD have no variants at all. Note these are the
# VIDEO icons' values and not the flat PNGs in `gui/simpleicon`: those are the same
# design but a different render (their C3 is #FF6000, hue 23 deg, against the
# video's #FC8000), and the videos are the ones that actually appear on the map.
SYS_LEGEND = ('C5', 'MH', 'HU', 'TS', 'TD')
SYS_PAINT = ((252, 20, 252),       # C5  - N-TC-C5.mp4
             (252, 128, 0),        # MH  - N-TC-C3.mp4
             (252, 252, 52),       # HU  - N-TC-C1.mp4
             (8, 252, 0),          # TS  - N-TC-TS.mp4
             (64, 100, 200))       # TD  - N-TD-D.mp4
SYS_N = len(SYS_LEGEND)
SYS_C5_KT, SYS_MH_KT, SYS_HU_KT = 137.0, 96.0, 64.0
# the data order, spelled out: 0 is the floor and 4 the ceiling
SYS_TD_K, SYS_TS_K, SYS_HU_K, SYS_MH_K, SYS_C5_K = 0, 1, 2, 3, 4
# which of the five are wind tests, and at what speed
SYS_KT = {SYS_HU_K: SYS_HU_KT, SYS_MH_K: SYS_MH_KT, SYS_C5_K: SYS_C5_KT}


def sys_reach(S, t0, named):
    """When a system FIRST satisfies each of the five criteria.

    Returns {category index: datetime}, simply omitting whatever it never meets.
    Each wind test is checked against the peak reached SO FAR, never the lifetime
    peak: the rulers are meant to show the basin as it stands, so a system joins
    MH when it actually gets to 96 kt, not retroactively once it is over.

    It cannot drop back out, and that is the ratchet: it comes for free because a
    running maximum never decreases, so "has reached X so far" is monotone in time
    by construction. A category-3 typhoon that weakens to a tropical storm stays
    counted in MH, and in HU, TS and TD below it.

    TD is taken as the FIRST FIX. The source carries no numbering timestamp -
    `Num.txt` holds an invest id, the xxW number and the JMA name, nothing else -
    and every folder in the season has a number, so a system is numbered for its
    whole tracked life. If a season ever carries an unnumbered system, this is the
    line that has to learn about it.
    """
    out = {SYS_TD_K: t0}
    if named:
        out[SYS_TS_K] = named
    for k, thr in SYS_KT.items():
        hit = np.nonzero(S.iwind >= thr)[0]
        if len(hit):
            out[k] = t0 + timedelta(hours=float(S.ihours[hit[0]]))
    return out


# season_pass2.py 4453, 4475, 4443, 4517, 4627, 4669
#
# The column is DERIVED, not four hand-written y values. It was four literals and
# they drifted the moment one card was shortened: the damage card lost six units
# and the ACE card kept its old y, opening a twelve-unit hole where a six-unit gap
# belongs. Each card now starts one gap below the one above it, so the column can
# only be compacted as a whole.
_COL_GAP = 6
BOX_IDENTITY = (10, 10, 480, 80)
BOX_DAMAGE = (10, BOX_IDENTITY[1] + BOX_IDENTITY[3] + _COL_GAP, 480, 94)
# The chart sits in the LEFT column, between the damage card and the tally. Its
# PANEL now encloses the ruler and the label too - the card is the whole block, not
# just the plot - so nothing floats on the map under it.
BOX_ACE = (10, BOX_DAMAGE[1] + BOX_DAMAGE[3] + _COL_GAP, 480, 264)


def _block_h(w):
    """Height of the ruler's coloured band at card width `w`, in design units."""
    return w * 124.0 / 1500.0 * 0.4


BOX_RULER = (10, 0, 480, int(round(_block_h(480))))     # y comes from BOX_ACE

# ---- the tally: FIVE rulers, stacked flush, sharing their edges -------------
#
# One bar per category instead of one bar split five ways, stacked with no gap so
# that two neighbours OVERLAP by exactly one frame thickness and their shared
# edge is drawn as a single line. That is what "public frame" means here: not one
# big box around the group, but each bar framed and the frames overlapping.
#
# The overlap is what makes the stack read as one object; without it the shared
# edge would be two lines deep and the group would look like five separate bars.
#
# The left edge is the ACE ruler's own inset (0.021 of the card width), so the two
# rulers start at the same x. Each bar's own width:height is the DAMAGE well's,
# 260:16, which is why the thickness comes out at 22.8 rather than the old 26.
#
# THE STACKING PITCH IS NOT `height - 1`, and getting it wrong is the whole
# difficulty. `ImageDraw.rectangle` with `width=w` draws its outline INSIDE the
# box, so for two neighbours' strokes to land on the same pixels the second box
# has to start `w` pixels above the first one's bottom edge - that is,
# `pitch = height - (w - 1)`, in LAYER pixels. At a 1 px stroke the pitch is the
# height exactly; at 2 px it is one short. Measured, not reasoned: at pitch
# `height - 1` with a 1 px stroke the shared edge came out 2 px thick, i.e. twice
# the outer edge, because the two strokes sat on ADJACENT rows instead of the same
# one. The card is sized for the widest case (1 px stroke, pitch = height).
TALLY_INSET = 0.021                  # fraction of the card width, as the ACE ruler
TALLY_ASPECT = 260.0 / 16.0          # the damage well's width : height
TALLY_BAR_W = 370.0                  # design units
TALLY_BAR_H = TALLY_BAR_W / TALLY_ASPECT
TALLY_TOP = 16.0                     # card top to the first bar
TALLY_STACK_H = SYS_N * TALLY_BAR_H  # widest case: pitch == height
TALLY_LBL_X = TALLY_INSET * 480.0 + TALLY_BAR_W + 12.0   # from the card's left
TALLY_LBL_CAP = 14.0
TALLY_NUM_X = TALLY_LBL_X + 40.0
TALLY_NUM_CAP = 14.0

BOX_TALLY = (10, BOX_ACE[1] + BOX_ACE[3] + _COL_GAP, 480,
             int(round(2 * TALLY_TOP + TALLY_STACK_H)))

# The ACE ruler's thickness, as a fraction of the height the artwork would have if
# its full 12.1:1 strip were placed across the card width. The art is CROPPED to
# this band rather than scaled down to it, so the width stays the card's and the
# ramp keeps its proportions - scaling would have shrunk the bar horizontally too.
RULER_BAND = 0.4
BOX_TIMELINE = (60, 930, 1800, 140)

# the five rectangles the original composites, 4702-4703
COMPOSITE_BOXES = (BOX_IDENTITY, BOX_DAMAGE, BOX_TALLY, BOX_ACE,
                   (60, 930, 1800, 140))

# season_pass2.py 3491-3493
SE_ACT, SE_QUIET, SE_PAD, SE_EASE = 0.5, 15.0, 1.0, 1.0
SE_MERGE_D = 1.0

Y0 = datetime(2020, 1, 1)
Y1 = datetime(2021, 1, 1)

REF_W = 1920.0
CJK_LO = 0x2e80              # season_pass2.py 4319: ord(ch) > 0x2e80 -> CJK face

MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
          'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')

TRACK_DEFAULT = 0.12         # season_pass2.py 4313

# Tabular figures: the width every digit gets, as a fraction of the widest
# digit's advance. Saira has no `tnum` feature and its digits do not fill their
# own advance, so this is a measured compromise - see _digit_w.
DIGIT_CELL = 0.85

# How long, in SCREEN seconds, the clock's HH:MM takes to fade in and out across
# each end of each active block. Measured in screen time on purpose: one world day
# of quiet is 1/15 s of screen time, which is no transition at all.
P2_TIME_FADE = 1.2
CJK_TTC = os.path.join(F_SOURCE_HAN, 'SourceHanSansSC-Regular.otf')


def _ramp(t, a, b):
    """season_pass2.py 463: the cubic ramp used for every fade and count."""
    if t <= a:
        return 0.0
    if t >= b:
        return 1.0
    x = (t - a) / (b - a)
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------------------
# the two numbers on the damage card
# ---------------------------------------------------------------------------
# Both are cumulative and both span four orders of magnitude over a season - a
# toll runs from 0 to thousands of people, a loss from a few 万元 to a couple of
# hundred 亿元 - so a fixed number of decimals shows noise at one end of the
# season and nothing at the other. The card prints THREE SIGNIFICANT FIGURES
# instead, which is a property of the number rather than of the unit.
#
# `%.3g` would be the one-liner, and it is unusable here: it flips to exponent
# notation the moment the exponent reaches the precision, so a four-digit toll
# prints as '1.23e+04' inside a Chinese label. These two helpers round to n
# significant figures and then print plain decimal, always.

def _round_sig(v, n=3):
    """`v` rounded to `n` significant figures, as a float."""
    v = float(v)
    if not np.isfinite(v) or v == 0.0:
        return 0.0
    e = int(math.floor(math.log10(abs(v))))
    return float(round(v, -(e - (n - 1))))


def _sig(v, n=3):
    """`v` at `n` significant figures, never in exponent notation.

    Rounding is done BEFORE the decimal count is chosen, so a value that carries
    into a new decade keeps its precision: 9.999 at three figures is '10.0', not
    '10.00'.
    """
    r = _round_sig(v, n)
    if r == 0.0:
        return '0'
    e = int(math.floor(math.log10(abs(r))))
    return '%.*f' % (max(0, n - 1 - e), r)


def _dead_label(d):
    """'死亡：242人', or '死亡：1.23万人' once the toll passes ten thousand.

    Three significant figures are a BIG-NUMBER rule here, not a general one: they
    exist so a large toll does not turn into a six-character string, and below ten
    thousand the exact count is both shorter and true, so it is printed as it is.
    1234 people read '1234人', not '1230人'.

    The cutoff is on the count itself, not on the rounded form, because nothing is
    rounded on the `人` side. The 万人 side is, so 99999 at three figures is '10.0'
    and not '9.99'.
    """
    if d >= 10000.0:
        return '死亡：%s万人' % _sig(d / 1e4)
    return '死亡：%d人' % int(d)


def _loss_label(lo):
    """'损失：209亿元' / '损失：5680万元' - the original's unit split (4456),
    with three significant figures instead of '%.1f'.

    The split is decided on the 万元 form AFTER rounding, for the same reason the
    death threshold is: 0.9999亿元 is 9999万元, which at three significant figures
    is 10000万元, and '损失：10000万元' is both the wrong unit and a wider label
    than the 亿元 form it rounds into.
    """
    if lo >= 1.0 or _round_sig(lo * 1e4) >= 10000.0:
        return '损失：%s亿元' % _sig(lo)
    return '损失：%s万元' % _sig(lo * 1e4)


# ---------------------------------------------------------------------------
# storm data
# ---------------------------------------------------------------------------

# Legacy 12-digit years are retained for existing season data only.
TIME_COMPACT = re.compile(r'^(?:\d{14}|\d{12})$')
TIME_LONG = re.compile(r'^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$')


def parse_fix_time(tok):
    tok = tok.strip()
    if TIME_COMPACT.fullmatch(tok) and len(tok) == 14:
        return datetime(int(tok[:4]), int(tok[4:6]), int(tok[6:8]),
                        int(tok[8:10]), int(tok[10:12]), int(tok[12:14]))
    if TIME_COMPACT.match(tok):
        yy = int(tok[:2])
        year = 1900 + yy if yy >= 50 else 2000 + yy
        return datetime(year, int(tok[2:4]), int(tok[4:6]),
                        int(tok[6:8]), int(tok[8:10]), int(tok[10:12]))
    if TIME_LONG.match(tok):
        return datetime.strptime(tok, '%Y-%m-%d-%H-%M-%S')
    raise ValueError(tok)


def normalize_phase(value):
    value = value.upper()
    aliases = {'DB-LO': 'DB', 'DB-AL': 'DB', 'DB-WV': 'WV', 'DB-MD': 'MD',
               'ST': 'SD', 'TD': 'TC', 'TS': 'TC',
               **{k: 'TC' for k in ('C1', 'C2', 'C3', 'C4', 'C5', 'C5+', 'C5++')}}
    value = aliases.get(value, value)
    if value not in ('DB', 'WV', 'MD', 'TC', 'RV', 'EX', 'SD', 'SS'):
        raise ValueError('Unknown cyclone type: %s' % value)
    return value


def segment_phase(filename, fallback='TC'):
    stem = os.path.splitext(os.path.basename(filename))[0].upper()
    return {'DB': 'DB', 'DB-LO': 'DB', 'DB-AL': 'DB',
            'DB-WV': 'WV', 'DB-MD': 'MD', 'WV': 'WV', 'MD': 'MD', 'SD': 'SD', 'SS': 'SS'}.get(stem, fallback)


def read_rows(path):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return []
    unified = os.path.basename(path).lower() == 'track.txt'
    stem = os.path.splitext(os.path.basename(path))[0].upper()
    current = None if unified else normalize_phase(segment_phase(path, stem))
    out = []
    with open(path, encoding='utf-8-sig') as fh:
        for line_no, line in enumerate(fh, 1):
            t = line.split('#', 1)[0].split()
            if not t:
                continue
            if len(t) not in (5, 6):
                raise ValueError('%s:%d: expected 5 or 6 columns' % (path, line_no))
            if len(t) == 6:
                current = normalize_phase(t[5])
            if current is None:
                raise ValueError('%s:%d: first track fix must specify its type' % (path, line_no))
            def num(value):
                return float('nan') if value.upper() in ('N/A', 'NA', '-') else float(value)
            out.append((parse_fix_time(t[0]), float(t[1]), float(t[2]),
                        num(t[3]), num(t[4]), current))
    return out


def read_stamp(path):
    """The JMA stamp, found by SHAPE, never by line number."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            for tok in re.split(r'[^0-9-]+', raw.strip()):
                if TIME_COMPACT.match(tok) or TIME_LONG.match(tok):
                    return parse_fix_time(tok)
    return None


def read_jtwc(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            m = re.search(r'\b(\d{2})W\b', raw)
            if m:
                return int(m.group(1))
    return None


def read_damage(path):
    """lon lat place dead+missing loss(wan CNY). The empty file is skipped.

    The file carries loss in 万 CNY and the original works in 亿 CNY throughout:
    pass 1 converts with `_yi = _loss * 1e-4` for `damage_loss_unit: 'wan'`
    (season_pass2.py 1313, 3417), `DAMAGE[i]['loss']` is stored as a 亿 string,
    `p2_curves` accumulates it as a float (3947), and the card prints
    '损失：%.1f亿元' above 1.0 and '%.0f万元' below (4456). So the conversion
    belongs here, once, where the unit enters the program.
    """
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return []
    out = []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.rsplit(None, 2)
            if len(parts) < 3:
                continue
            head = parts[0].split()
            if len(head) < 3:
                continue
            try:
                out.append(dict(lon=float(head[0]), lat=float(head[1]),
                                place=head[2], dead=float(parts[1]),
                                lost=0.0, loss=float(parts[2]) * 1e-4))
            except ValueError:
                continue
    return out


class Series:
    """A storm's fixes, with the ACE the original builds on a 6-hour grid.

    season_pass2.py 727-743: `off = (-t0.hour) % 6`, the synoptic grid is
    `arange(off, duration, 6)`, and `ace` is the cumulative `w^2 >= 34` sum read
    back onto the fix grid. Reproduced exactly - the numbers must stay
    reproducible and must not come off a display curve.
    """

    __slots__ = ('hours', 'lon', 'lat', 'wind', 'pres', 'ihours', 'iwind',
                 'ace', 'duration_h')

    def __init__(self, rows, t0):
        self.hours = np.array([(r[0] - t0).total_seconds() / 3600.0 for r in rows])
        self.lon = np.array([r[1] for r in rows], dtype=float)
        self.lat = np.array([r[2] for r in rows], dtype=float)
        self.wind = np.array([r[3] for r in rows], dtype=float)
        self.pres = np.array([r[4] for r in rows], dtype=float)
        ok = ~np.isnan(self.wind)
        self.ihours = self.hours[ok]
        self.iwind = self.wind[ok]
        if not len(self.ihours):
            raise SystemExit('no fix carries a wind value')
        self.duration_h = float(self.hours[-1])
        off = (-t0.hour) % 6
        syn = np.arange(float(off), self.duration_h + 1e-6, 6.0)
        w = np.interp(syn, self.ihours, self.iwind)
        indices = np.clip(np.searchsorted(self.hours, syn, side='right') - 1, 0, len(rows) - 1)
        tc = np.array([(rows[i][5] if len(rows[i]) > 5 else 'TC') == 'TC' for i in indices])
        a = np.where(tc & (w >= 34.0), w * w, 0.0) / 1e4
        cum = np.concatenate(([0.0], np.cumsum(a)))
        self.ace = np.interp(self.hours,
                             np.concatenate(([syn[0]], syn)) if len(syn) else [0.0],
                             cum)

    def sample_ace(self, h):
        return float(np.interp(min(max(h, 0.0), self.duration_h), self.hours, self.ace))


def min_dist_hours(S, lon, lat):
    """Hour of closest approach, and the distance in km. [season_pass2.py 1398-1406]

    The overlay needs it because `p2_curves` books deaths and loss at
    `DAMAGE[i]['h']`, which the original computed here from the track, not from
    anything in damage.txt. Without it the damage curve lands at the wrong hour.
    """
    hs = np.arange(0.0, S.duration_h, 0.05)
    lo = np.interp(hs, S.hours, S.lon)
    la = np.interp(hs, S.hours, S.lat)
    d = np.hypot((la - lat) * 111.0, (lo - lon) * 111.0 * np.cos(np.radians(lat)))
    k = int(np.argmin(d))
    return float(hs[k]), float(d[k])


def load_season(season_root):
    src = os.path.join(season_root, 'sourcedata')
    if not os.path.isdir(src):
        raise SystemExit('no sourcedata/ under %s' % season_root)
    storms = []
    for entry in sorted(os.listdir(src)):
        d = os.path.join(src, entry)
        if not os.path.isdir(d):
            continue
        m = re.match(r'^WP(\d{2})', entry)
        if not m:
            continue
        num = int(m.group(1))
        rows = []
        files = ('track.txt',) if os.path.isfile(os.path.join(d, 'track.txt')) else (
            'DB.txt', 'DB-LO.txt', 'DB-aL.txt', 'DB-WV.txt', 'DB-MD.txt', 'WV.txt', 'MD.txt',
            'SD.txt', 'SS.txt', 'TC.txt', 'RV.txt', 'EX.txt')
        for fn in files:
            rows.extend(read_rows(os.path.join(d, fn)))
        if not rows:
            continue
        rows.sort(key=lambda r: r[0])
        t0 = rows[0][0]
        S = Series(rows, t0)
        named = read_stamp(os.path.join(d, 'Num.txt'))
        dmg = read_damage(os.path.join(d, 'damage.txt'))
        for e in dmg:
            e['h'], e['km'] = min_dist_hours(S, e['lon'], e['lat'])
        jtwc = read_jtwc(os.path.join(d, 'Num.txt'))
        storms.append(dict(num=num, folder=entry, S=S, t0=t0,
                           t1=t0 + timedelta(hours=S.duration_h),
                           named=named, DAMAGE=dmg, jtwc=jtwc))
    storms.sort(key=lambda s: s['num'])
    return storms


class SeasonTime:
    """Date <-> screen second. season_pass2.py 3440-3488, reproduced."""

    def __init__(self, storms, y0=Y0, y1=Y1):
        spans = sorted([st['t0'], st['t1']] for st in storms)
        mg = []
        for a, b in spans:
            if mg and a <= mg[-1][1] + timedelta(days=SE_MERGE_D):
                mg[-1][1] = max(mg[-1][1], b)
            else:
                mg.append([a, b])
        pad = timedelta(days=SE_PAD)
        self.blocks = [[a - pad, b + pad] for a, b in mg]
        self.y0, self.y1 = y0, y1
        step = timedelta(hours=1)
        grid, taus, tm, tau = [], [], y0, 0.0
        while tm <= y1:
            grid.append((tm - y0).total_seconds() / 86400.0)
            taus.append(tau)
            tau += (step.total_seconds() / 86400.0) / self.rate(tm)
            tm += step
        self.grid = np.array(grid)
        self.taus = np.array(taus)

    def rate(self, tm):
        E = timedelta(days=SE_EASE)
        for a, b in self.blocks:
            if tm < a - E or tm > b + E:
                continue
            if a <= tm <= b:
                return SE_ACT
            if tm < a:
                u = (tm - (a - E)).total_seconds() / (SE_EASE * 86400.0)
                return SE_QUIET + (SE_ACT - SE_QUIET) * (1.0 - (1.0 - u) ** 2)
            u = (tm - b).total_seconds() / (SE_EASE * 86400.0)
            return SE_ACT + (SE_QUIET - SE_ACT) * u * u
        return SE_QUIET

    def s_of(self, tm):
        return float(np.interp((tm - self.y0).total_seconds() / 86400.0,
                               self.grid, self.taus))

    def dt_of(self, s):
        return self.y0 + timedelta(days=float(np.interp(s, self.taus, self.grid)))

    @property
    def total(self):
        return float(self.taus[-1])


# ---------------------------------------------------------------------------
# curves
# ---------------------------------------------------------------------------

def p2_curves(storms, T):
    """season_pass2.py 3916 ff, reproduced.

    One sample per hour plus a quarter-hourly grid for the curve. The ACE total
    is the running sum of `w^2` at the strict 00/06/12/18Z points, read off each
    storm's OWN fix grid, and only then interpolated - never accumulated off a
    display curve, so the numbers stay reproducible. The rate is the REAL-TIME
    sum over the systems on the field; see the block below.
    """
    n = int((T.y1 - T.y0).total_seconds() / 3600.0) + 2
    grid = [T.y0 + timedelta(hours=i) for i in range(n)]
    dead = np.zeros(n)
    loss = np.zeros(n)

    syn_h = np.arange(0.0, (T.y1 - T.y0).total_seconds() / 3600.0 + 1e-6, 6.0)
    ace_syn = np.zeros(len(syn_h))
    for k in range(len(syn_h)):
        s6 = 0.0
        for st in storms:
            S = st['S']
            h = (T.y0 + timedelta(hours=float(syn_h[k])) - st['t0']).total_seconds() / 3600.0
            if h < 0 or h > S.duration_h:
                continue
            w = float(np.interp(h, S.ihours, S.iwind))
            s6 += (w * w if w >= 34.0 else 0.0) / 1e4
        ace_syn[k] = s6
    ace_cum = np.concatenate(([0.0], np.cumsum(ace_syn)))
    ace = np.interp(np.arange(n), np.concatenate(([syn_h[0]], syn_h)), ace_cum)

    # The tally is NOT built here. It is a per-criterion event list - see
    # `Overlay._tally_book` - because its five counts come from five independent
    # tests, three of them on a running wind maximum and two of them agency
    # decisions, and none of that is a function of the hourly grid. A per-hour
    # (n, 5) array used to be built here and nothing ever read it.
    for st in storms:
        S, t0 = st['S'], st['t0']
        for e in st['DAMAGE']:
            j = int(max(0, min(n - 1, ((t0 + timedelta(hours=e.get('h', 0.0)))
                                       - T.y0).total_seconds() / 3600.0)))
            dead[j] += e['dead'] + e['lost']
            loss[j] += float(e['loss'] or 0.0)
    dead = np.cumsum(dead)
    loss = np.cumsum(loss)

    # ---- the rate: REAL TIME, not a difference ------------------------------
    #
    # The rate is what the systems ON THE FIELD are producing at this instant:
    #
    #     rate(t) = 4/1e4 * SUM over storms on the field of v(t)^2
    #
    # `4` is the number of synoptic points in a day, so the unit is ACE units per
    # day and the curve integrates to the season's ACE. It is NOT a 24 h centred
    # difference of the cumulative curve any more. A difference is a 24-hour
    # AVERAGE - it answers "how fast has ACE been accumulating", which lags the
    # events by half a day; this answers "how fast is it accumulating NOW", which
    # is what a rate curve and its heat-coloured cursor are read for. Measured on
    # 2020: the difference peaked at 10.73 on 2020-10-31 06:00, an instant at
    # which Goni was still intensifying; the real-time rate peaks at 11.56 on
    # 2020-10-31 18:00, Goni's own 170 kt fix, the deepest moment of the season.
    #
    # A system is ON THE FIELD for the whole span of its own track - the same
    # eligibility the cumulative sum uses, phase labels and all - and what it
    # contributes is its wind AT THAT INSTANT, interpolated on its own fixes.
    # The `P2_ACE_MIN_KT` gate is the cumulative curve's own 34 kt gate, so the
    # two curves on this one plot cannot disagree about what ACE counts.
    rate = np.zeros(n)
    rgrid_h = np.arange(n, dtype=float)
    for st in storms:
        S = st['S']
        h = rgrid_h - (st['t0'] - T.y0).total_seconds() / 3600.0
        v = np.interp(np.clip(h, 0.0, S.duration_h), S.ihours, S.iwind)
        on = (h >= 0.0) & (h <= S.duration_h) & (v >= P2_ACE_MIN_KT)
        rate += np.where(on, v * v, 0.0)
    rate *= 4.0 / 1e4

    n15 = int((T.y1 - T.y0).total_seconds() / 900.0) + 2
    h15 = np.arange(n15) * 0.25
    ace15 = np.interp(h15 * 3600.0, np.arange(n) * 3600.0, ace)
    r15 = np.interp(h15, np.arange(n, dtype=float), rate)

    return dict(grid=grid, ace=ace, rate=rate, dead=dead, loss=loss,
                h15=h15, ace15=ace15, r15=r15, ace_end=float(ace[-1]))


# ---------------------------------------------------------------------------
# the summary banner
# ---------------------------------------------------------------------------

_BANF = {}


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


def banner_peak_colour(wind):
    """Single's super-cyclone theme; ordinary C5 and below keep their art."""
    if wind > 200.0:
        return palette_colour(wind, HIGHWIND_BODY)
    if wind <= 155.0:
        return None
    if wind < 170.0:
        return (214, 106, 255)
    a = np.array([126, 44, 176], dtype=np.float32)
    b = np.array([40, 74, 178], dtype=np.float32)
    if wind <= 185.0:
        t = min(1.0, max(0.0, (wind - 170.0) / 15.0))
        return tuple(int(v) for v in (a * (1 - t) + b * t))
    t = min(1.0, (wind - 185.0) / 15.0)
    return tuple(int(v) for v in (b * (1 - t) + np.array([198,232,255]) * t))


def tint_banner(im, col):
    """Single's HSV replacement, preserving the white core and neutral art."""
    hsv = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2HSV).astype(np.float32)
    sat, val = hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
    sel = sat > 0.28
    tc = np.array(col, dtype=np.float32) / 255.0
    mx, mn = float(tc.max()), float(tc.min())
    s_t = 0.0 if mx <= 0 else (mx - mn) / mx
    if sel.any():
        sv = float(np.median(val[sel])) or 1.0
        ss = float(np.median(sat[sel])) or 1.0
        hue = int(cv2.cvtColor(np.uint8([[col]]), cv2.COLOR_RGB2HSV)[0, 0, 0])
        hsv[..., 0][sel] = hue
        hsv[..., 1][sel] = np.clip(sat[sel] / max(ss, 0.15) * s_t * 255.0, 0, 255)
        hsv[..., 2][sel] = np.clip(val[sel] / max(sv, 0.15) * mx * 255.0, 0, 255)
    return Image.fromarray(cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8),
                                        cv2.COLOR_HSV2RGB))


def _bfont(path, size):
    """Truetype cache for the banner's three faces, which are single's."""
    key = (path, size)
    f = _BANF.get(key)
    if f is None:
        f = ImageFont.truetype(path, size)
        _BANF[key] = f
    return f


def _ease01(u):
    """0..1 smoothstep: the cubic `single` uses for every one of its ramps.

    Cubic on purpose - the banner's rise is specified as a cubic ease, and the
    same curve runs the slide and the fade, so one helper cannot drift from the
    other.
    """
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    return u * u * (3.0 - 2.0 * u)


def _banner_text(d, xy, s, f_ascii, f_cjk, fill):
    """single's `mixed_base`: character by character, on a shared baseline.

    Drawn per character because the two faces have different metrics - a CJK
    glyph in a Latin-only line renders as a tofu box, and setting them on one
    baseline is what keeps 'LOSS ~ 209亿元' level.
    """
    x, y = xy
    for ch in s:
        f = f_cjk if ord(ch) > CJK_LO else f_ascii
        d.text((x, y), ch, font=f, fill=fill, anchor='ls')
        x += d.textlength(ch, font=f)
    return x


BAN_ART = {
    'TD': 'Summary-N-TC-TD.mp4', 'TS': 'Summary-N-TC-TS.mp4',
    'C1': 'Summary-N-TC-C1.mp4', 'C2': 'Summary-N-TC-C2.mp4',
    'C3': 'Summary-N-TC-C3.mp4', 'C4': 'Summary-N-TC-C4.mp4',
    'C5': 'Summary-N-TC-C5.mp4',
}


def banner_level(w):
    """The SSHWS level a peak wind belongs to, as the banner art is named.

    Single's `BANNER_BY_LEVEL` maps C5+ and C5++ down onto the C5 art, so the
    top three bands collapse to one file here too.
    """
    for kt, lvl in ((137.0, 'C5'), (113.0, 'C4'), (96.0, 'C3'),
                    (83.0, 'C2'), (64.0, 'C1'), (34.0, 'TS')):
        if w >= kt:
            return lvl
    return 'TD'


def _ban_money(lo):
    """'209亿元' / '5680万元' - the card's own unit split, without its label."""
    if lo >= 1.0 or _round_sig(lo * 1e4) >= 10000.0:
        return '%s亿元' % _sig(lo)
    return '%s万元' % _sig(lo * 1e4)


def _ban_deaths(d):
    """'242人', or '1.23万人' from ten thousand up - the card's rule again."""
    if d >= 10000.0:
        return '%s万人' % _sig(d / 1e4)
    return '%d人' % int(d)


def banner_book(storms, T):
    """One entry per storm, preformatted, at the screen second it dissipates.

    The head and the two figure lines are built ONCE here rather than per frame:
    nothing in them changes while the banner is on screen, and they are the same
    strings the cards would print - same three significant figures, same 亿元 /
    万元 split, same 万人 rule - so a banner and the card behind it cannot
    disagree about what a storm cost.

    A storm with no damage row gets single's `n/a` for both figures, which is
    what an empty `damage.txt` means.
    """
    out = []
    for st in storms:
        S = st['S']
        k = int(np.argmax(S.iwind))
        peak_w = float(S.iwind[k])
        peak_p = float(S.pres[~np.isnan(S.wind)][k])
        dead = float(sum(e['dead'] + e['lost'] for e in st['DAMAGE']))
        loss = float(sum(float(e['loss'] or 0.0) for e in st['DAMAGE']))
        named = st['named'] is not None
        head = '%02dW   %s' % (st['num'], st['folder'].split('_', 1)[1].upper()) \
            if named else '%02dW' % st['num']
        line2 = ('PEAK %.0f kt / %.0f hPa      ACE %.2f x10^4 kt2      '
                 'LOSS ~ %s      DEATHS %s'
                 % (peak_w, peak_p, float(S.ace[-1]),
                    _ban_money(loss) if st['DAMAGE'] else 'n/a',
                    _ban_deaths(dead) if st['DAMAGE'] else 'n/a'))
        out.append(dict(num=st['num'], folder=st['folder'],
                        t_in=T.s_of(st['t1']), level=banner_level(peak_w),
                        head=head, line2=line2, tint=banner_peak_colour(peak_w)))
    out.sort(key=lambda e: (e['t_in'], e['num']))
    return out


# ---------------------------------------------------------------------------
# the overlay
# ---------------------------------------------------------------------------

def _rdp(xs, ys, tol):
    """Ramer-Douglas-Peucker on a polyline with monotone x, VERTICAL distance.

    Returns the indices to keep. Iterative, because the recursion depth on an
    8762-point series with a spike in it is not something to leave to CPython's
    stack limit.

    The distance is vertical rather than perpendicular on purpose: the curve is a
    graph y(x) and the plot reads heights, so a perpendicular metric would spend
    its tolerance on the horizontal error, which no one can see, and none of it
    on the height, which is the whole chart.
    """
    n = len(xs)
    if n < 3:
        return np.arange(n)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        x0, y0 = float(xs[i]), float(ys[i])
        dx, dy = float(xs[j]) - x0, float(ys[j]) - y0
        seg = ys[i + 1:j]
        if abs(dx) < 1e-9:
            dev = np.abs(seg - y0)
        else:
            dev = np.abs(seg - (y0 + dy * (xs[i + 1:j] - x0) / dx))
        m = int(np.argmax(dev))
        if dev[m] > tol:
            k = i + 1 + m
            keep[k] = True
            stack.append((i, k))
            stack.append((k, j))
    return np.nonzero(keep)[0]


class Overlay:
    def __init__(self, season_root, assets, size=(1920, 1080), fps=60.0,
                 log=print, render_w=None, intro=2.5):
        self.root, self.assets = season_root, assets
        self.W, self.H = int(size[0]), int(size[1])
        self.FPS = float(fps)
        self.intro = None if intro is None else float(intro)
        self.log = log

        # Bounded render canvas. The original drew at output resolution, which is
        # affordable at 1080p and impossible at 8K: a full-frame RGBA pass there
        # measured 38-108 ms against an 8.33 ms budget for 120 fps. The data layer
        # is screen furniture, so its detail need not be frame-exact.
        self.render_w = int(render_w) if render_w else int(min(3840, max(1920, self.W)))
        self.sc = self.render_w / REF_W
        self.RH = int(round(self.render_w * self.H / float(self.W)))

        self.storms = load_season(season_root)
        if not self.storms:
            raise SystemExit('no storms')
        self.T = SeasonTime(self.storms)
        self.C = p2_curves(self.storms, self.T)

        # season_pass2.py 4103-4109, 4195-4207
        self.dead_full = max(1.0, float(np.ceil(self.C['dead'].max() / 50.0) * 50.0))
        self.loss_full = max(1.0, float(np.ceil(self.C['loss'].max() / 50.0) * 50.0))
        self.sys_full = max(5.0, math.ceil(len(self.storms) / 5.0) * 5.0)
        self.axis_max = max(5.0, math.ceil(float(self.C['rate'].max()) / 5.0) * 5.0)
        _end = float(self.C['ace_end'])
        self.ace_axis = (math.ceil(_end / 100.0) * 100.0
                         if (int(_end) // 10) % 10 >= 7
                         else math.ceil(_end / 10.0) * 10.0)
        self.ace_full = math.ceil(_end / 50.0) * 50.0
        _first = min(st['t0'] for st in self.storms)
        self.cx0 = datetime(_first.year, _first.month, 1)
        self.cx1 = self.T.y1

        # season_pass2.py 4110-4151, the three ramps
        self.ruler = Image.open(os.path.join(
            assets, 'gui', 'ace', 'ace_color_1000.png')).convert('RGB')
        self.ruler_n = ImageOps.grayscale(self.ruler).convert('RGB')
        h = np.asarray(Image.open(os.path.join(
            assets, 'resources', 'ace-heat.png')).convert('RGB'))
        col = h[:, h.shape[1] // 2, :] if h.shape[0] >= h.shape[1] else h[h.shape[0] // 2, :, :]
        ok = [int(col[k].sum()) > 30 for k in range(len(col))]
        best, cur = (0, 0), None
        for k, v in enumerate(ok + [False]):
            if v and cur is None:
                cur = k
            elif not v and cur is not None:
                if k - cur > best[1] - best[0]:
                    best = (cur, k)
                cur = None
        self.heat_ramp = np.array([list(col[k]) for k in
                                   range(best[1] - 1, best[0] - 1, -1)],
                                  dtype=np.uint8)
        # acerate.png is NOT loaded: the ramp is read from the fitted node list in
        # the table at the top of this file instead, because the asset is a few
        # linear interpolation and sampling the bitmap only approximates that.
        cm = np.asarray(Image.open(os.path.join(
            assets, 'resources', 'colormap.png')).convert('RGB'))
        line = cm[:, cm.shape[1] // 2, :] if cm.shape[0] >= cm.shape[1] else cm[cm.shape[0] // 2, :, :]
        self.cmap = np.array([list(line[k]) for k in range(len(line))], dtype=np.uint8)

        self.saira = os.path.join(F_SAIRA, 'Saira-SemiBold.ttf')
        self._lfc, self._tc = {}, {}
        self._dw = {}                      # widest-digit advance per cap size
        self._static = None
        self.book = self._book(self.storms, self.T)
        self.tally_book = self._tally_book(self.storms, self.T)

        # the summary banners, and the per-level art extraction they need. The
        # extraction is lazy: a season that never reaches C5 never pays for the
        # C5 clip, and every level's frames are reused by every banner wearing it.
        self.banners = banner_book(self.storms, self.T)
        self.banner_peak = self._banner_peak()
        self._banner_dirs, self._banner_n, self._banner_im = {}, {}, {}
        self._banner_used = set()

        # The active blocks, in screen seconds, for the clock's time fade. The
        # edges are cached because time_alpha runs every frame and the season has
        # 24 of them.
        self.blk0 = np.array([self.T.s_of(a) for a, b in self.T.blocks])
        self.blk1 = np.array([self.T.s_of(b) for a, b in self.T.blocks])
        self.blk_edge = np.concatenate((self.blk0, self.blk1)) \
            if len(self.blk0) else np.zeros(0)

        self.log('  curves: rate 0-%.0f, ACE 0-%.0f (year end %.1f), tally 0-%.0f'
                 % (self.axis_max, self.ace_axis, _end, self.sys_full))
        self.log('  season %.2f s | canvas %dx%d -> %dx%d | scale %.3f'
                 % (self.T.total, self.render_w, self.RH, self.W, self.H, self.sc))
        self.log('  banners: %d, at most %d on screen at once'
                 % (len(self.banners), self.banner_peak))

    def _book(self, storms, T):
        """season_pass2.py 4212-4240: one entry per storm, at its book second.

        This drives the DAMAGE and ACE ramps only - deaths, loss and the booked
        ACE all land when a storm is over. It used to drive the tally as well, by
        carrying a `cat`; the tally now has its own event list, because it counts
        five independent things and most of them happen in the middle of a storm's
        life rather than after it.
        """
        out = []
        for st in storms:
            S = st['S']
            out.append(dict(t=T.s_of(st['t1'] + timedelta(hours=P2_BOOK_H)),
                            dead=float(sum(e['dead'] + e['lost'] for e in st['DAMAGE'])),
                            loss=float(sum(float(e['loss'] or 0.0) for e in st['DAMAGE'])),
                            ace=float(S.ace[-1])))
        return out

    def _tally_book(self, storms, T):
        """One event per (system, criterion met), at the screen second it was met.

        Same shape as `_book` so `_tally_counts` and `_tally_number` are unchanged
        - a list of dicts with a screen second and a category - but the times are
        when each criterion was reached, not when the storm died.
        """
        out = []
        for st in storms:
            for k, tm in sys_reach(st['S'], st['t0'], st['named']).items():
                out.append(dict(t=T.s_of(tm), cat=k))
        return out

    # ------------------------------------------------------------ ramps
    def _heat(self, v):
        """ACE rate -> colour off acerate.png, 0 .. axis_max.

        Reads the fitted node list rather than the bitmap. The asset is a few
        fixed colour nodes interpolated linearly between them, so the nodes ARE
        the design; sampling the strip would tie the ramp to its 776-row length
        and to PNG quantisation. fit_acerate.py recovers the nodes and
        fixed nodes with the table at the top of this file holds them.

        Returns ints: PIL's `fill` rejects floats.
        """
        c = acerate_lookup(min(1.0, max(0.0, float(v) / max(1.0, self.axis_max))))
        return (int(round(c[0])), int(round(c[1])), int(round(c[2])))

    def _heat_arr(self, vals):
        """The same ramp for a whole array, as float RGB.

        Vectorised because this runs once per plot column per frame; the node
        list is short, so the loop is over 14 nodes, not over 592 columns.
        """
        u = np.clip(np.asarray(vals, dtype=float) / max(1.0, self.axis_max),
                    0.0, 1.0)
        out = np.empty((len(u), 3), dtype=float)
        nu = np.array([nd[0] for nd in ACERATE_NODES])
        ncol = np.array([nd[1:] for nd in ACERATE_NODES], dtype=float)
        idx = np.clip(np.searchsorted(nu, u, side='right') - 1, 0, len(nu) - 2)
        u0, u1 = nu[idx], nu[idx + 1]
        t = np.where(u1 > u0, (u - u0) / np.maximum(u1 - u0, 1e-12), 0.0)[:, None]
        out[:] = ncol[idx] * (1.0 - t) + ncol[idx + 1] * t
        return out

    def _heat_lut(self, vals):
        """Integer RGB rows, for callers that want the array form."""
        return self._heat_arr(vals).round().astype(np.uint8)

    def _cmapex(self, v):
        u = min(1.0, max(0.0, float(v) / max(1e-6, self.ace_axis)))
        return tuple(int(c) for c in self.cmap[int(round(u * (len(self.cmap) - 1)))])

    def _lf(self, cap):
        sz = max(5, int(round(cap * 1.43)))
        f = self._lfc.get(sz)
        if f is None:
            f = ImageFont.truetype(self.saira, sz)
            self._lfc[sz] = f
        return f

    def _cf(self, cap):
        sz = max(6, int(round(cap * 1.36)))
        f = self._lfc.get(('cjk', sz))
        if f is None:
            f = ImageFont.truetype(CJK_TTC, sz)
            self._lfc[('cjk', sz)] = f
        return f

    def _digit_w(self, cap):
        """The cell every digit gets when tabular figures are asked for.

        Saira's digits are proportional and the spread is brutal: at cap 34 the
        '1' advances 9.0 while '0' advances 16.0, so a running clock is 44%
        narrower on a string of ones than on a string of zeros. Measured on this
        file, '2020-10-31' is 139.2 wide and '2020-11-01' is 133.2 - a 12 px jump
        at 1080p - and '23:55' against '11:11' differs by 24 px. Anything that
        ticks therefore shuffles sideways every time a digit changes.

        The cell is the widest digit's INK, not its advance. A '1' has a nine
        pixel advance but a twelve pixel stem, and setting the cell from advances
        both underestimates what has to fit and leaves a wider hole beside the
        '1' than the stroke needs. Taking the widest ink and centring each glyph
        in the cell keeps the string length a function of its character count
        alone, which is the whole point, while looking less like a gap.

        Saira-SemiBold carries no `tnum` feature to ask for, and Pillow's layout
        engine would not apply one, so the cell is imposed here: every digit is
        drawn left-aligned in a cell of DIGIT_CELL x the widest digit's advance,
        which is how a tabular-figure font behaves.

        The factor is a compromise that had to be measured. Saira's digits do not
        fill their own advance - at cap 32 a '0' advances 31 but inks 21 - so a
        full-width cell leaves every digit pair 10 px apart and a '1', whose ink
        is 18, opens a 20 px hole that reads as a space ('2020-1 0-31'). Shrinking
        the cell closes that hole but can collide a '0' with the next digit, since
        a '0' inks 21 of its 31. 0.85 leaves every pair at least 8 px, which is
        the same rhythm the wide digits already have, and cuts the '1' hole to 15.
        """
        w = self._dw.get(cap)
        if w is None:
            f = self._lf(cap)
            w = max(f.getlength(d) for d in '0123456789') * DIGIT_CELL
            self._dw[cap] = w
        return w

    def _mw(self, s, cap, track=TRACK_DEFAULT, digits=False):
        """season_pass2.py 4313, plus the tabular-figure option."""
        w = 0.0
        dw = self._digit_w(cap) if digits else 0.0
        for ch in s:
            if ch == ' ':
                w += cap * 0.42
            elif ch.isdigit() and digits:
                w += dw + cap * track * 0.5
            elif ord(ch) > CJK_LO:
                w += self._cf(cap).getlength(ch)
            else:
                w += self._lf(cap).getlength(ch) + cap * track * 0.5
        return w

    def _mtext(self, ov, x, y, s, cap, col, aa=255, track=TRACK_DEFAULT,
               digits=False):
        """season_pass2.py 4325, the cached-sprite path only.

        The original also had an inline path for filling the cache; here the
        sprite is built with its own Draw and always composited. `digits` asks
        for tabular figures, so a ticking clock does not change width.
        """
        aa = int(max(0, min(255, aa)))
        if aa <= 2:
            return self._mw(s, cap, track, digits)
        key = (s, int(round(cap)), tuple(col), round(track, 3), aa // 16,
               bool(digits))
        sp = self._tc.get(key)
        if sp is None:
            # The sprite is built a little wider than the measured advance when
            # centring digits, because a digit's ink may then reach past its own
            # advance - a '1' drawn centred in a cell as wide as a '0' starts
            # eight pixels into a nine-pixel advance.
            pad = cap * 1.2 + (self._dw.get(cap, 0.0) if digits else 0.0)
            w = int(math.ceil(self._mw(s, cap, track, digits) + pad))
            h = int(math.ceil(cap * 2.2))
            im = Image.new('RGBA', (max(1, w), max(1, h)), (0, 0, 0, 0))
            dy = cap * 0.45
            d2 = ImageDraw.Draw(im, 'RGBA')
            xx = 0.0
            dw = self._digit_w(cap) if digits else 0.0
            # the widest digit advance at this size, so tabular glyphs can be
            # shifted by one constant instead of by their own side bearing
            cell_adv = 0.0
            if digits:
                f0 = self._lf(cap)
                cell_adv = max(f0.getlength(d) for d in '0123456789')
            for ch in s:
                if ch == ' ':
                    xx += cap * 0.42
                    continue
                if ch.isdigit() and digits:
                    f = self._lf(cap)
                    d2.text((xx, dy + cap * 0.52), ch, font=f,
                            fill=tuple(col) + (255,), anchor='lm')
                    xx += dw + cap * track * 0.5
                    continue
                if ord(ch) > CJK_LO:
                    f = self._cf(cap)
                    d2.text((xx, dy + cap * 0.52), ch, font=f, fill=tuple(col) + (255,),
                            anchor='lm')
                    xx += f.getlength(ch)
                else:
                    f = self._lf(cap)
                    d2.text((xx, dy + cap * 0.52), ch, font=f, fill=tuple(col) + (255,),
                            anchor='lm')
                    xx += f.getlength(ch) + cap * track * 0.5
            if aa < 250:
                im.putalpha(im.getchannel('A').point(lambda v: int(v * aa / 255.0)))
            if len(self._tc) > 4000:
                self._tc.clear()
            self._tc[key] = (im, dy)
        im, dy = self._tc[key]
        ov.alpha_composite(im, (int(round(x)), int(round(y - dy))))
        return self._mw(s, cap, track)

    def _panel(self, d, box):
        x, y, w, h = [v * self.sc for v in box]
        d.rounded_rectangle([x, y, x + w, y + h], radius=5 * self.sc,
                            fill=P2_C['panel'])

    def _ease(self, t):
        """season_pass2.py 4373: cubic book-keeping, the rounds summed."""
        D = max(1e-6, P2_EASE_S)
        u = np.clip((t - np.array([b['t'] for b in self.book])) / D, 0.0, 1.0)
        f = u * u * (3.0 - 2.0 * u)
        dead = float(np.dot(np.array([b['dead'] for b in self.book]), f))
        loss = float(np.dot(np.array([b['loss'] for b in self.book]), f))
        ace = float(np.dot(np.array([b['ace'] for b in self.book]), f))
        return dead, loss, ace

    def time_alpha(self, t):
        """How visible the clock's HH:MM is at screen second `t`, 0 .. 1.

        The date always shows; the time only means something while the basin is
        active. During a quiet stretch the clock is already passing at 15 days per
        second, so a minute display is noise, and it is hidden. It comes back over
        P2_TIME_FADE across each end of each active block.

        The ramp is measured in SCREEN seconds, not world days: one world day of
        quiet is 1/15 s of screen time, so a one-day ramp would be invisible, and
        the transition the eye needs is the one it can see.

        The distance is taken to the nearest block edge, so a gap shorter than two
        fades never lets the time reach full opacity - the honest reading of a gap
        that short.
        """
        if not len(self.blk0):
            return 1.0
        if np.any((t >= self.blk0) & (t <= self.blk1)):
            return 1.0
        d = float(np.min(np.abs(t - self.blk_edge)))
        return float(np.clip(1.0 - d / P2_TIME_FADE, 0.0, 1.0))

    # ------------------------------------------------------- the static bake
    def build_static(self):
        """Everything that does not change per frame, rasterised once.

        The original redrew all of this every frame. Measured, that is what makes
        8K impossible; baked, the per-frame cost stops depending on the output
        size at all. The baked layer is drawn at aa=255 and the per-frame fade is
        applied by scaling the whole layer, which is exact for the staggered
        intro because every card's alpha is a single scalar draw.
        """
        ov = Image.new('RGBA', (self.render_w, self.RH), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov, 'RGBA')
        P = self.px

        # The wells and bars are baked here, but their WHITE FRAMES are not: they
        # are collected into `_frame_rects` and drawn at the very end of `frame`,
        # after every fill. See that block for why.
        self._frame_rects = []

        for box in (BOX_IDENTITY, BOX_DAMAGE, BOX_TALLY, BOX_ACE):
            self._panel(d, box)

        # ---- identity: the two lines that matter. [4443-4448]
        x, y, w, h = [v * self.sc for v in BOX_IDENTITY]
        self._mtext(ov, 26 * self.sc, 20 * self.sc, 'WPAC 2020', 18 * self.sc,
                    P2_C['txt'], 255, 0.14)

        # ---- damage card: the two empty wells. [4457-4470]
        #
        # ROLLED BACK to the original's own numbers. Four attempts at "improving"
        # this card - solving the rows from the sprite height, from the ink height,
        # from ratios of the card, from a fixed bar x - each traded one problem for
        # a worse one, and the last made the bars twice the height of the text.
        #
        # The original's design is:
        #
        #     row k top   = dy + 18 + k*42        (42 = row pitch)
        #     bar height  = 16
        #     bar x       = dx + 182, width 260   (leaves the label 182 units)
        #
        # In a 96-tall card that is a top margin of 18, a row gap of 26 and a bottom
        # margin of 14. The only change here is that the whole block is shifted down
        # by half the extra height so it stays centred in the taller card; the
        # internal spacing is untouched.
        dx, dy, dw, dh = [v * self.sc for v in BOX_DAMAGE]
        _shift = (BOX_DAMAGE[3] - 96.0) / 2.0
        drowtop = [BOX_DAMAGE[1] + _shift + 18.0 + k * 42.0 for k in range(2)]
        dbar_top = [t + 1.0 for t in drowtop]     # the original's +1 nudge
        dbar_h = 16.0
        bar_x0, bar_w = dx + 182.0 * self.sc, 260.0 * self.sc

        # The wells only. Both rows' TEXT is the live block's job - it prints
        # '死亡：242人' / '损失：209亿元' - and a second, bare label baked here is
        # what produced two overlapping texts in this card earlier.
        #
        # Everything in this block is already in LAYER pixels: bar_x0/bar_w were
        # scaled above. Multiplying by sc again here is the double-scale that has
        # bitten this file more than once.
        for k in range(2):
            yy = dbar_top[k] * self.sc
            hh = dbar_h * self.sc
            rect = (bar_x0, yy, bar_x0 + bar_w, yy + hh)
            d.rectangle(rect, fill=(0, 0, 0, 255))
            # the white frame is NOT drawn here - see `_frame_rects` below
            self._frame_rects.append(rect)
        self._dmg_rowtop = drowtop
        self._dmg_bar_top = dbar_top
        self._dmg_bar_h = dbar_h

        # ---- tally card: five stacked wells, and their labels. [4475-4513]
        #
        # The wells are black and framed; the FRAMES are not drawn here. They go
        # into `_frame_rects` and are drawn at the end of `frame`, after the
        # coloured fills - a frame baked here would be painted over by its own
        # bar. That is the same rule as the damage wells and the ACE ruler.
        #
        # The five rects share their edges: bar i+1 starts `pitch` below bar i,
        # and the pitch is short of the height by one stroke, so the two outlines
        # land on the SAME rows and the shared edge is a single line. Both the
        # pitch and the height are already in LAYER pixels here, and the box's
        # bottom is derived from the pitch so the two agree to the last bit.
        sx, sy, sw, sh = [v * self.sc for v in BOX_TALLY]
        bar_x = (BOX_TALLY[0] + TALLY_INSET * BOX_TALLY[2]) * self.sc
        bar_w = TALLY_BAR_W * self.sc
        stroke = max(1, int(self.sc))
        bar_h = TALLY_BAR_H * self.sc
        pitch = bar_h - (stroke - 1)
        top = (BOX_TALLY[1] + TALLY_TOP) * self.sc
        self._tally_geom = (bar_x, top, bar_w, bar_h, pitch)
        for i, lab in enumerate(SYS_LEGEND):
            y0 = top + i * pitch
            y1 = top + (i + 1) * pitch + (stroke - 1)
            rect = (bar_x, y0, bar_x + bar_w, y1)
            d.rectangle(rect, fill=(0, 0, 0, 255))
            self._frame_rects.append(rect)
            # The live pass owns the COUNT; the label is baked here. Both use the
            # same named offsets, and a disagreement between the two shows through
            # as ghosted text - which a 12-unit drift did once, on the old legend.
            self._mtext(ov, (BOX_TALLY[0] + TALLY_LBL_X) * self.sc,
                        y0 + (bar_h - TALLY_LBL_CAP * self.sc) * 0.5, lab,
                        TALLY_LBL_CAP * self.sc, P2_C['dim'], 255)

        # ---- ACE card: grid, both axes, month names. [4517-4565]
        #
        # Every offset here is a FRACTION of the card's height or width, not a
        # constant. With the original's fixed paddings the plot only fitted a
        # 232-tall card: narrow it or shorten it and the axis labels, the plot and
        # the right-hand scale run into each other. The card has to be placeable
        # anywhere, including between two other cards.
        bx, by, bw, bh = [v * self.sc for v in BOX_ACE]
        sc = self.sc
        cap = max(11.0, 16.0 * sc)
        # The title row and the plot share 264 units of card. Every offset is a
        # fraction of the card, and the three that matter were measured against
        # each other rather than guessed: the title's ink is 16 units, the plot
        # needs its top 10 units below that ink and its bottom 13 above the month
        # names, the month names are 11, the ruler band 15.5, and the ruler's
        # caption 13 including the descenders in 'Cyclone Energy'.
        _ty = by + 0.042 * bh
        self._ace_title_y = _ty / self.sc            # design units, for the audit
        self._mtext(ov, bx + 0.052 * bw, _ty, 'ACE rate/天', cap,
                    P2_C['txt'], 255, 0.10)
        self._mtext(ov, bx + 0.052 * bw + self._mw('ACE rate/天', cap, 0.10)
                    + 2 * self.sc, _ty - 0.020 * bh, '-1', 10 * self.sc,
                    P2_C['txt'], 255, 0.06)
        # The right padding has to hold the three-digit axis labels AND the 'ACE'
        # title, so it is wider than the left one. At 0.075 the title's own width
        # pushed its right edge past the card: measured, its right edge came to
        # 1005 against a panel that ends at 980.
        px0, px1 = bx + 0.100 * bw, bx + bw - 0.145 * bw
        # The plot takes everything between the title and the month names.
        py0, py1 = by + 0.140 * bh, by + 0.666 * bh
        self.ace_plot = (px0, py0, px1, py1)
        t0s = (self.cx0 - self.T.y0).total_seconds()
        t1s = (self.cx1 - self.T.y0).total_seconds()
        self._cxp = lambda tm: px0 + (px1 - px0) * (
            ((tm - self.T.y0).total_seconds() - t0s) / (t1s - t0s))
        self._build_rate_curve(px0, px1, py0, py1)
        for gv in [5.0 * k for k in range(int(self.axis_max / 5.0) + 1)]:
            gy = py1 - (py1 - py0) * (gv / self.axis_max)
            d.line([px0, gy, px1, gy], fill=(255, 255, 255, 26),
                   width=max(1, int(self.sc)))
            self._mtext(ov, px0 - 6 * self.sc - self._mw('%.0f' % gv, 12 * self.sc, 0.12),
                        gy - 6 * self.sc, '%.0f' % gv, 12 * self.sc, P2_C['dim'], 255, 0.12)
        for q in range(5):
            gy = py1 - (py1 - py0) * (q / 4.0)
            self._mtext(ov, px1 + 3 * self.sc, gy - 6 * self.sc,
                        '%.0f' % (self.ace_axis * q / 4.0), 12 * self.sc,
                        P2_C['dim'], 255, 0.12)
        # 'ACE' labels the RIGHT axis, so it is right-aligned to the card's inner
        # margin, on the same row as the left-hand title. Placed relative to the
        # plot it drifted off the card edge whenever the padding changed.
        _acew = self._mw('ACE', cap, 0.10)
        self._mtext(ov, bx + bw - 0.045 * bw - _acew, _ty, 'ACE', cap,
                    (226, 236, 250), 255, 0.10)
        d.line([px1, py0, px1, py1], fill=(255, 255, 255, 41), width=max(1, int(self.sc)))
        mo = self.cx0.month
        while mo <= 12:
            md = datetime(2020, mo, 1)
            mx = self._cxp(md)
            if md > self.cx0:
                d.line([mx, py0, mx, py1], fill=(255, 255, 255, 18),
                       width=max(1, int(self.sc)))
            lab = MONTHS[mo - 1]
            mxx = self._cxp(md + timedelta(days=15))
            wm = self._mw(lab, 11 * self.sc, 0.14)
            if mxx < px1 - 6 * self.sc:
                self._mtext(ov, mxx - wm / 2.0, py1 + 13 * self.sc, lab, 11 * self.sc,
                            P2_C['dim'], 255, 0.14)
            mo += 1

        # ---- the ACE ruler: the coloured band, inside the card's own panel.
        #
        # It is part of the card now, not a strip below it: its y comes from
        # BOX_ACE's bottom edge and the panel was made tall enough to hold it. The
        # band's y and height are fractions of the card so nothing spills when the
        # card is resized.
        #
        # 0.810, not 0.872. At 0.872 the ruler sat 32 units below the month names
        # and its caption ended one and a half units above the panel's own edge -
        # measured, the card's lowest ink row was the caption's, 0.5 units from the
        # border. Pulling the block up is what the panel enlargement was for: the
        # plot gets the difference and the caption gets 14 units of air.
        bx_, by_, bw_, bh_ = [v * self.sc for v in BOX_ACE]
        rx = bx_ + 0.021 * bw_
        rw = bw_ - 0.042 * bw_
        rh = rw * self.ruler.height / float(self.ruler.width) * RULER_BAND
        ry = by_ + 0.810 * bh_
        self.ruler_geom = (rx, ry, rw, rh)
        self._frame_rects.append((rx, ry, rx + rw, ry + rh))
        v = 10.0
        while v < self.ace_full - 1e-6:
            xx = rx + rw * (v / self.ace_full)
            major = abs(v % 50.0) < 1e-6
            d.line([xx, ry + rh, xx, ry + rh - rh * (0.5 if major else 0.25)],
                   fill=(255, 255, 255, 102), width=max(1, int((2 if major else 1) * self.sc)))
            v += 10.0
        # the label line, tucked close under the band and still inside the panel.
        # The gap is deliberately small: the label's sprite is cap*2.2 tall, and a
        # generous gap is what pushed it under the next card last time.
        self._ace_txt_pos = (rx, ry + rh + 0.40 * rh)

        # ---- timeline: baseline, month ticks, centred names. [4666-4690]
        tx0, tx1, ty = 60 * self.sc, 1860 * self.sc, 990 * self.sc
        self.tl_geom = (tx0, tx1, ty)
        span = (self.T.y1 - self.T.y0).total_seconds()
        self._tx = lambda tm: tx0 + (tm - self.T.y0).total_seconds() / span * (tx1 - tx0)
        d.line([tx0, ty, tx1, ty], fill=(255, 255, 255, 140), width=max(2, int(4 * self.sc)))
        for mo, lab in enumerate(MONTHS):
            mx = self._tx(datetime(2020, mo + 1, 1))
            d.line([mx, ty - 18 * self.sc, mx, ty + 18 * self.sc],
                   fill=(255, 255, 255, 140), width=max(1, int(2 * self.sc)))
            midx = self._tx(datetime(2020, mo + 1, 16))
            wm = self._mw(lab, 15 * self.sc, 0.14)
            self._mtext(ov, midx - wm / 2.0 + 2 * self.sc, ty + 34 * self.sc + 2 * self.sc,
                        lab, 15 * self.sc, (0, 0, 0), 178, 0.14)
            self._mtext(ov, midx - wm / 2.0, ty + 34 * self.sc, lab, 15 * self.sc,
                        P2_C['txt'], 255, 0.14)
        d.line([tx1, ty - 18 * self.sc, tx1, ty + 18 * self.sc],
               fill=(255, 255, 255, 140), width=max(1, int(2 * self.sc)))

        self._static = ov
        return ov

    def px(self, v):
        return v * self.sc

    # -------------------------------------------------- the rate curve, baked
    def _build_rate_curve(self, px0, px1, py0, py1):
        """The rate polyline, at its own resolution, decimated once.

        Two decisions live here, and both were made by measurement.

        THE SAMPLING GRID IS THE DATA'S, NOT THE PLOT'S. `rate` is one sample per
        hour and is piecewise linear between hourly knots, so hourly samples
        reproduce it exactly. Sampling once per pixel COLUMN instead - which is
        what this did - means one sample per 12.1 hours of season at the 8K
        layer, and the October spike is about half a day wide and eleven rate
        units tall: drawn as a single linear step it lost 0.85 of its height and
        the peak marker read 9.88. That pair was measured while the rate was
        still a 24 h difference and the true peak was 10.73; the argument is
        about the sampling grid, not about the rate model, and it is unchanged
        now that the rate is real-time and the peak is 11.56.

        THE POINTS ARE THEN DECIMATED, because 8762 of them is twelve times what
        a 724-column plot can show and the draw loop pays per segment: measured,
        baking all of them cost 40 ms a frame (12 -> 52 ms). The simplification is
        bounded by half a layer pixel of VERTICAL error, so nothing visible is
        lost; the spike keeps its apex because RDP always retains the extreme
        point of a run, and the cursor's true value is inserted into the polyline
        at draw time, so the marker is exact regardless.
        """
        RA = np.asarray(self.C['rate'], dtype=float)
        self._rhours = np.arange(len(RA), dtype=float)
        n = len(RA)
        h_a = (self.cx0 - self.T.y0).total_seconds() / 3600.0
        h_b = (self.cx1 - self.T.y0).total_seconds() / 3600.0
        k0 = int(max(0, math.ceil(h_a)))
        k1 = int(min(n - 1, math.floor(h_b)))
        if k1 <= k0:
            k1 = min(k0 + 1, n - 1)
        rv = RA[k0:k1 + 1]
        rxs = px0 + (np.arange(k0, k1 + 1, dtype=float) - h_a) / (h_b - h_a) * (px1 - px0)
        rys = py1 - (py1 - py0) * np.clip(rv / self.axis_max, 0.0, 1.0)
        keep = _rdp(rxs, rys, max(0.5, 0.5 * self.sc))
        self._rate_pts = (rxs[keep], rys[keep], rv[keep])
        self.log('    rate curve: %d hourly points -> %d after decimation (%.0f%% kept)'
                 % (len(rxs), len(keep), 100.0 * len(keep) / max(1, len(rxs))))

    # --------------------------------------------------------------- frame
    def frame(self, si, intro_t=None):
        """One overlay frame as RGBA, laid out exactly like the original's."""
        if self._static is None:
            self.build_static()

        t = si / float(self.FPS)
        now = self.T.dt_of(t)
        C = self.C
        i = int(max(0, min(len(C['grid']) - 1,
                           (now - self.T.y0).total_seconds() / 3600.0)))
        sc = self.sc

        ov = Image.new('RGBA', (self.render_w, self.RH), (0, 0, 0, 0))
        # the baked layer carries the panels, wells, grid and month names; the
        # live pass draws only what moves. [the file header's rule 2]
        ov.alpha_composite(self._static)
        d = ImageDraw.Draw(ov, 'RGBA')

        tt = t if intro_t is None else intro_t

        def A(k):
            return int(255 * _ramp(tt, 0.4 + 0.45 * k, 1.3 + 0.45 * k))

        def T_(x, y, s, cap, col, aa, track=TRACK_DEFAULT, right=None,
               shadow=False, digits=False):
            c = cap * sc
            w = self._mw(s, c, track, digits)
            xa = (x * sc - w) if right is not None else x * sc
            if shadow and aa > 4:
                self._mtext(ov, xa + 2 * sc, y * sc + 2 * sc, s, c, (0, 0, 0),
                            int(aa * 0.7), track, digits)
            self._mtext(ov, xa, y * sc, s, c, col, aa, track, digits)
            return w

        # ---- identity: the exact UTC clock. [4444-4448]
        # Tabular figures throughout: this is the one string on screen that
        # changes every frame, and Saira's '1' is 44% narrower than its '0', so
        # without this the clock - and the time after it - shuffles sideways on
        # every digit change.
        #
        # The cap heights are NOT the original's 34. Saira's digits are wide to
        # begin with, and equalising them to the widest one makes the clock
        # measurably wider than the original's proportional setting: at cap 34
        # the date and time together end at x=518 in a card that stops at 490.
        # 30 and 32 are the largest sizes that fit with a margin, and they are
        # what keeps the identity block inside its panel at every date.
        #
        # The TIME fades with the basin: while nothing is active it is hidden and
        # only the date shows, because there is nothing for a minute of clock to
        # say during a fortnight that passes in a hundredth of a second. It
        # returns over P2_TIME_FADE on each side of every active block, so the
        # hand-off is a fade and not a pop.
        aa = A(0)
        if aa > 4:
            # NOTE the y values. The column was compacted by shortening the
            # CARDS, not by pushing these two lines up into the title: at y=30
            # the date's ink (30..60) runs straight through 'WPAC 2020' (20..38).
            # They are two rows and they stay two rows; the saving came from the
            # card being 80 tall instead of 84.
            w = T_(26, 48, now.strftime('%Y-%m-%d'), 30, P2_C['txt'], aa, 0.10,
                   shadow=True, digits=True)
            tf = self.time_alpha(t)
            if tf > 0.01:
                T_(26 + w / sc + 22, 47, now.strftime('%H:%M'), 32, P2_C['txt'],
                   int(aa * tf), 0.10, shadow=True, digits=True)

        # ---- damage: two bars, deaths and loss. [4450-4470]
        aa = A(1)
        if aa > 4:
            dx, dy, dw, dh = BOX_DAMAGE
            dl, lo, _a = self._ease(t)
            lotxt = _loss_label(lo)
            # BOTH terms are design units, and the sum is then scaled - not
            # `dx + 182.0 * sc`, which is what this said. `dx` is the card's left
            # edge in DESIGN units (10) while `182.0 * sc` is already in LAYER
            # pixels, so the fill started `(sc - 1) * dx` pixels left of the well
            # its own frame is drawn around: 10 layer px at 8K, a strip of colour
            # poking out past the white frame on the left.
            #
            # It never showed at 540p because `render_w` floors at 1920, so
            # sc = 1 and the two units coincide. Any output above 1920 has it.
            bar_x0 = (dx + 182.0) * sc
            bar_w = 260.0 * sc
            bar_hh = self._dmg_bar_h * sc
            for k, (lab, frac, col) in enumerate((
                    (_dead_label(dl), dl / max(1.0, self.dead_full), P2_C['red']),
                    (lotxt, lo / max(1.0, self.loss_full), P2_C['loss']))):
                # T_ takes the text's TOP in DESIGN units - the offset arg is not
                # pre-scaled - while the stored tops are design units too.
                T_(dx + 18.0, self._dmg_rowtop[k], lab, 15, P2_C['txt'],
                   aa, 0.05, digits=True)
                yy = self._dmg_bar_top[k] * sc
                fx = bar_w * min(1.0, max(0.0, frac))
                if fx > 0:
                    d.rectangle([bar_x0, yy, bar_x0 + fx, yy + bar_hh],
                                fill=col + (aa,))

        # ---- tally: five rulers, one per category. [4472-4513]
        aa = A(5)
        if aa > 4:
            bar_x, top, bar_w, bar_h, pitch = self._tally_geom
            cbx = BOX_TALLY[0]
            full = max(1.0, self.sys_full)
            for i, lab in enumerate(SYS_LEGEND):
                # i is the DISPLAY row, counted from the top = C5. The data index
                # runs the other way, TD at 0, so the top row is SYS_N-1.
                k = SYS_N - 1 - i
                y0 = top + i * pitch
                # the length comes off the continuous count, the digits off the
                # rounded one - the digits flip at the midpoint of their own ramp
                seg = bar_w * min(1.0, self._tally_counts(t, k) / full)
                if seg > 0:
                    d.rectangle([bar_x, y0, bar_x + seg, y0 + bar_h],
                                fill=SYS_PAINT[i] + (aa,))
                val, al = self._tally_number(t, k)
                yt = y0 + (bar_h - TALLY_NUM_CAP * sc) * 0.5
                T_((cbx + TALLY_NUM_X), yt / sc, '%d' % val,
                   TALLY_NUM_CAP, P2_C['txt'], int(aa * al),
                   digits=True)

        # ---- ACE card: increment envelope, cumulative step, cursor. [4515-4618]
        aa = A(3)
        if aa > 4:
            bx, by, bw, bh = BOX_ACE
            # read the plot box the bake settled on, rather than recomputing it
            # from constants - the card's internals are proportional now, and two
            # copies of that arithmetic would drift
            px0, py0, px1, py1 = self.ace_plot
            t0s = (self.cx0 - self.T.y0).total_seconds()
            t1s = (self.cx1 - self.T.y0).total_seconds()
            H15, A15, R15 = C['h15'], C['ace15'], C['r15']
            j0 = int(max(0, t0s / 3600.0 / 0.25))
            j1 = int(min(len(H15) - 1, t1s / 3600.0 / 0.25))
            jnow = int(min(len(H15) - 1,
                           (now - self.T.y0).total_seconds() / 3600.0 / 0.25))
            ncol = max(1, int(px1 - px0))

            # ---- the rate curve's sample grid, computed ONCE -------------------
            #
            # The marker's number and the curve's height have to come from the
            # same array or they disagree wherever the rate is steep. They used to
            # be built separately - the marker from `np.interp(h_now, h15, r15)`
            # and the curve from an index lookup into the same array - and on a
            # spike, where one pixel column is a tenth of a rate unit, the two
            # grids diverged by 0.34 units: 4.9 px, enough to read as the marker
            # leaving the line. Every position below is sampled from `rxs`/`rys`.
            # Sampled on the grid `rate` LIVES on - one point per hour - and not
            # once per pixel column. `rate` is piecewise linear between hourly
            # knots, so hourly samples reproduce it EXACTLY: the polyline passes
            # through the season's true maximum and `rate_at_x` reads it back
            # without error.
            #
            # One sample per column looked harmless and was not. The plot is 724
            # columns for 8760 hours, so a column is 12.1 hours of season, and the
            # October spike is about half a day wide and eleven rate units tall.
            # Drawn as a single linear step it lost 0.85 of its height: the marker
            # read 9.88, on the one number the peak stills exist to show. (That
            # 0.85 was measured under the 24 h-difference rate; the sampling
            # argument does not depend on the rate model, and under the real-time
            # rate the peak is 11.56 at 2020-10-31 18:00.) The cost is twelve
            # times the segments, which the sub-step budget absorbs (the sub-steps
            # follow vertical travel, and travel does not change when the same
            # line is cut finer).
            # The geometry itself is BAKED, the same polyline on every frame, so it
            # is built and decimated once in `build_static`; this loop only reads
            # it. `rv` is the rate each baked point carries.
            rxs_all, rys_all, rv_all = self._rate_pts
            RA = C['rate']
            rgrid = self._rhours
            # ---- where the cursor sits, and what it says ------------------
            #
            # ONE value drives both, and it is the SAME value the cumulative
            # line ends on: `ace15` interpolated at the current instant. Two
            # bugs came from not doing this. The crosshair used to be placed
            # from `rate[i]` - the HOURLY grid - while the line ends on
            # `ace15[jnow]` - the QUARTER-HOURLY grid - so the marker sat up to
            # 17.6 px off its own line (measured; at the season's opening a 0.4
            # ACE-unit difference is 10 px), which is the white line that
            # appeared to flicker as the two grids drifted apart and back.
            #
            # The cursor is drawn from the first month on the x-axis, not from
            # the first storm: the plot opens with the season, so the reading is
            # live from the month the axis starts, even while the basin is bare.
            h_now = (now - self.T.y0).total_seconds() / 3600.0
            jj_now = min(len(C['ace15']) - 1, h_now / 0.25)
            lo = int(math.floor(jj_now))
            hi = min(len(C['ace15']) - 1, lo + 1)
            fr = jj_now - lo
            ace_now = float(C['ace15'][lo]) * (1.0 - fr) + float(C['ace15'][hi]) * fr

            show_cursor = now >= self.cx0
            xnow = self._cxp(now)
            ynow = py1 - (py1 - py0) * min(1.0, ace_now / self.ace_axis)
            # The rate itself is read off `rate` - the same hourly array the
            # baked curve was built from, so this is exact - and the point is
            # then INSERTED into the drawn polyline below. Marker and curve
            # therefore agree by construction AND the printed number is the true
            # one: reading it back off the decimated polyline instead would have
            # made the number follow the simplification's own tolerance, which is
            # the 0.85-unit error this whole change exists to remove.
            vn = float(np.interp(h_now, rgrid, RA))
            yrate = py1 - (py1 - py0) * min(1.0, vn / self.axis_max)

            # the cumulative curve, on the right-hand scale; drawn first so the
            # increment envelope stays readable over it [4601-4607]
            kk = np.arange(0, ncol + 1)
            jj = j0 + ((j1 - j0) * kk / float(ncol)).astype(int)
            keep = jj <= jnow
            kk, jj = kk[keep], jj[keep]
            if len(jj):
                cxs = px0 + kk
                cys = py1 - (py1 - py0) * np.clip(A15[jj] / self.ace_axis, 0.0, 1.0)
                # land the line exactly on the cursor: the samples are
                # quarter-hourly but the cursor is continuous, so without this
                # the curve visibly stops short of its own marker
                if show_cursor and xnow > cxs[-1] + 0.5:
                    cxs = np.append(cxs, xnow)
                    cys = np.append(cys, ynow)
                if len(cxs) > 1:
                    d.line(list(zip(cxs.tolist(), cys.tolist())),
                           fill=(226, 236, 250, aa), width=max(1, int(2 * sc)),
                           joint='curve')

            # ---- the RATE curve: a solid heat-coloured line ---------------
            #
            # This replaces the original's per-column min/max envelope with its
            # wash to the baseline. The envelope needed a Python loop over every
            # plot column - 680 of them at 1080p and it grows with the frame - and
            # it read as spikes rather than as a curve.
            #
            # The colour is sampled ONCE PER PIXEL COLUMN, not once per
            # quarter-hour sample. acerate.png is a continuous gradient (776 rows,
            # largest step between neighbouring rows 6/255), so a stepped look can
            # only come from the sampling: taking each segment's colour from its
            # end sample paints an eight-hour segment one flat colour, and the
            # next segment can be four units of rate away - which reads as a jump.
            # This file had exactly that bug. The plot is 592 columns at 1080p, so
            # the draw-call count is still bounded and independent of the output
            # size.
            #
            # Colour comes off resources/acerate.png, keyed to the SAME scale the
            # left axis is labelled in (0..axis_max), so a colour and a height
            # always mean the same rate.
            if ncol > 0:
                # the baked polyline is what gets painted; the cursor's own point
                # is INSERTED into it below
                #
                # The cursor point is INSERTED at its place in x and everything
                # after it is dropped. Appending it instead - which is what this
                # did - puts the cursor after samples that lie LATER in time than
                # the cursor itself, so the closing segment ran from the last
                # pre-cursor column (x=3434, rate lower) to the cursor, drawing a
                # line to the right of the marker and below it. That is the dot
                # that appeared not to sit on the curve end.
                #
                # The truncation happens even when the cursor is OFF-PLOT. The
                # plot's x window opens with the season's first month, so for the
                # first four months of screen time - and through the intro - `now`
                # is earlier than cx0 and the cursor lies to the LEFT of px0. The
                # old `else` branch drew the whole baked polyline in that case,
                # which put the entire season's rate curve on screen before the
                # season had begun. Off-plot the searchsorted index is 0 and
                # nothing is drawn, which is what an empty plot should look like.
                k = int(np.searchsorted(rxs_all, xnow, side='right'))
                if show_cursor:
                    px_ = np.insert(rxs_all[:k], k, xnow)
                    py_ = np.insert(rys_all[:k], k, yrate)
                    pv_ = np.insert(rv_all[:k], k, vn)
                else:
                    px_, py_, pv_ = rxs_all[:k], rys_all[:k], rv_all[:k]
                cols = self._heat_arr(pv_)
                rxs, rys, rv = px_, py_, pv_
                # Colour is interpolated ALONG each segment, and the number of
                # sub-steps comes from how far the line travels VERTICALLY, not
                # from how much the rate changed. Sub-stepping on the rate
                # difference looked reasonable and did nothing: at axis_max 15 the
                # plot is ~10 px per rate unit, so a nine-unit change inside one
                # pixel column is a 90 px climb, and six sub-steps still leave the
                # colour jumping 1.5 units per step. Two pixels per sub-step is
                # what makes the gradient continuous.
                width = max(1, int(2 * sc))
                for k in range(0, len(rxs) - 1):
                    x0, y0 = float(rxs[k]), float(rys[k])
                    x1, y1 = float(rxs[k + 1]), float(rys[k + 1])
                    c0, c1 = cols[k], cols[k + 1]
                    sub = int(min(24, max(1, abs(y1 - y0) / (2.0 * self.sc) + 1)))
                    for j in range(sub):
                        f0 = j / float(sub)
                        f1 = (j + 1) / float(sub)
                        c = c0 * (1.0 - f0) + c1 * f0
                        d.line([(x0 + (x1 - x0) * f0, y0 + (y1 - y0) * f0),
                                (x0 + (x1 - x0) * f1, y0 + (y1 - y0) * f1)],
                               fill=(int(round(c[0])), int(round(c[1])),
                                     int(round(c[2])), 255),
                               width=width)

            # The cursor is drawn from the first month on the x-axis, not from
            # the first storm: the plot opens with the season, so the reading is
            # live from the month the axis starts, even while the basin is bare.
            # Its number flips sides near the plot's left edge so it cannot hang
            # outside the card.
            if show_cursor:
                # the rate marker: on the rate curve, at the rate's own height
                r = 2.5 * sc
                d.ellipse([xnow - r, yrate - r, xnow + r, yrate + r],
                          fill=self._heat(vn) + (aa,))
                # the cumulative line gets its own small end-cap, so the two
                # curves are told apart by where they end, not by colour alone
                d.ellipse([xnow - 1.8 * sc, ynow - 1.8 * sc,
                           xnow + 1.8 * sc, ynow + 1.8 * sc],
                          fill=(226, 236, 250, aa))
                # The number is written WITHOUT a leading sign. It used to read
                # '+5.53', and at small sizes the plus sits above the digits'
                # baseline like a marker stroke, so the label read as a detached
                # crosshair and the arrangement looked like the marker had come
                # off its curve. A plain '5.53' cannot be misread that way.
                txt = '%.2f' % vn
                # tabular digits: this number changes constantly and is placed
                # against the plot edge, so a proportional '1' would make it
                # shiver every time a digit changes
                wtxt = self._mw(txt, 14 * sc, 0.10, True)
                # Sit up-and-right by default, but pulled closer than before and
                # dropped slightly, so the label groups with its dot instead of
                # floating above the line. Near the right edge it flips inward.
                if xnow + 6 * sc + wtxt > px1:
                    tx = xnow - 6 * sc - wtxt          # flip to the left
                else:
                    tx = xnow + 6 * sc
                ty = yrate - 22 * sc
                self._mtext(ov, tx + 2 * sc, ty + 2 * sc, txt, 14 * sc,
                            (0, 0, 0), int(aa * 0.7), 0.10, True)
                self._mtext(ov, tx, ty, txt, 14 * sc, P2_C['txt'], aa, 0.10, True)

        # ---- the ACE ruler: the true value washed, the booked value solid
        #      [4620-4664]
        aa = A(4)
        if aa > 4:
            _j15 = int(max(0, min(len(C['ace15']) - 1,
                                  (now - self.T.y0).total_seconds() / 900.0)))
            val = float(C['ace15'][_j15])
            _d3, _l3, booked = self._ease(t)
            rx, ry, rw, rh = self.ruler_geom
            # ---- the reveal: the art is cropped, never resized
            #
            # Two layers share the scale, both cropped from the same full-width
            # art. Underneath, the true growth washed to 25% so it reads as the
            # background; on top, the booked growth that eases in as each storm
            # dissipates. With nothing active and every ramp finished the two
            # coincide, and the crop then covers the whole bar.
            frac = min(1.0, val / self.ace_full)
            if frac > 0:
                full, n = self._ruler_piece(frac, rh)
                piece = full.crop((0, 0, n, full.height))
                piece.putalpha(int(aa * 0.25))
                ov.alpha_composite(piece, (int(rx), int(ry)))
                d.line([rx + n, ry, rx + n, ry + rh],
                       fill=(255, 255, 255, int(aa * 0.55)), width=1)
            fracb = min(1.0, booked / self.ace_full)
            if fracb > 0:
                full, nb = self._ruler_piece(fracb, rh)
                ov.alpha_composite(full.crop((0, 0, nb, full.height)),
                                   (int(rx), int(ry)))
            v = 10.0
            while v < self.ace_full - 1e-6:
                xx = rx + rw * (v / self.ace_full)
                if v <= val + 1e-6:
                    major = abs(v % 50.0) < 1e-6
                    d.line([xx, ry + rh, xx, ry + rh - rh * (0.5 if major else 0.25)],
                           fill=(255, 255, 255, int(aa * 0.90)),
                           width=max(1, int((2 if major else 1) * sc)))
                v += 10.0
            # one string, label and number together, as the original prints it
            # [4663]: 'Accumulated Cyclone Energy (ACE) : %.1f'
            # tabular digits on the number only; the label is fixed text
            tx_, ty_ = self._ace_txt_pos
            txt = 'Accumulated Cyclone Energy (ACE) : %.1f' % val
            self._mtext(ov, tx_, ty_, txt, 11 * sc, P2_C['txt'], aa, 0.06, True)

        # ---- timeline: the pointer. [4691-4698]
        aa = A(6)
        if aa > 4:
            px = self._tx(now)
            ty = self.tl_geom[2]
            hc = self._heat(float(C['rate'][i]))
            d.line([px, ty - 34 * sc, px, ty + 26 * sc], fill=hc + (int(aa * 0.30),),
                   width=max(2, int(11 * sc)))
            d.line([px, ty - 32 * sc, px, ty + 24 * sc], fill=hc + (aa,),
                   width=max(1, int(4 * sc)))
            d.ellipse([px - 8 * sc, ty - 42 * sc, px + 8 * sc, ty - 26 * sc],
                      fill=hc + (aa,))

        # ---- the summary banners ---------------------------------------------
        # Over the cards, under the white frames: the banner is the topmost thing
        # on the layer except the frames, which are drawn last by their own rule.
        self._draw_banners(ov, t)

        # ---- the white frames, LAST -------------------------------------------
        #
        # The damage wells, the tally bar and the ACE ruler are all "a coloured
        # length inside a white rectangle", and the rectangle has to stay on top
        # of the length. Baked with the wells it did not: PIL draws a rectangle's
        # outline INSIDE its box, so the fill - which spans the same box - covered
        # it completely along the edge it started from. On the two horizontal bars
        # that is the leading edge; on the ACE ruler it was the TOP edge, because
        # the artwork is placed at the band's own y.
        #
        # Drawing them here rather than baking them costs three rectangle calls a
        # frame - the rule this file actually keeps is that nothing per-frame is a
        # loop over pixels, and this is not one. It also means no later block can
        # be added that accidentally paints over a frame.
        #
        # Full alpha, not `aa`: the frames are furniture like the panels they sit
        # in, and the panels do not fade in either.
        for rect in self._frame_rects:
            d.rectangle(list(rect), outline=(255, 255, 255, 204),
                        width=max(1, int(sc)))

        return ov

    def _ruler_piece(self, frac, h):
        """The ACE art, CROPPED in both directions, never stretched.

        The original resized the artwork to (frac*width, height), which squeezes
        the whole image into a shorter bar: ace_color_1000.png is 1500x124, a
        12.1:1 strip, and it was being drawn into a 26:1 box - a 2.15x horizontal
        stretch. That is why the ramp read as squeezed rather than as a scale.

        The reveal is a crop instead, and the two axes are cropped differently:

          * width  = the card's 680 units, always. The art is scaled to that width
            at its own aspect ratio and then whatever thickness is wanted is cut
            from the MIDDLE of it, so the bar spans the card and the colours are
            never compressed along the ramp.
          * height = RULER_BAND of the full strip. Cutting the band (rather than
            scaling the strip down) is what keeps the width at 680: scaling would
            have shrunk the bar to 40% of the card in BOTH directions.

        Each frame then takes the left `frac` of that band.
        """
        h = max(1, int(h))
        key = ('ruler_band', h)
        band = self._tc.get(key)
        if band is None:
            # Place the whole strip across the card width at its OWN ratio, then
            # cut a centred band of the wanted thickness out of it. Placing it at
            # the band's thickness instead would keep the ratio but leave the bar
            # at 39% of the card - "span the card" and "a band of the strip" cannot
            # both hold at once, and spanning the card is what a scale needs.
            placed_h = max(h, int(round(self.ruler_geom[2] * self.ruler.height
                                        / float(self.ruler.width))))
            w = max(1, int(round(placed_h * self.ruler.width
                                 / float(self.ruler.height))))
            full = self.ruler.resize((w, placed_h), Image.LANCZOS).convert('RGBA')
            y0 = placed_h // 2 - h // 2
            band = full.crop((0, max(0, y0), w, max(0, y0) + h))
            self._tc[key] = band
        n = max(1, int(round(band.width * min(1.0, max(0.0, float(frac))))))
        return band, n

    # ---------------------------------------------------------- summary banner
    #
    # Six rules, all of them the operator's, and all of them structural:
    #
    #   1. smaller than single's and parked in the TOP-RIGHT corner;
    #   2. right-to-left on the way in WHILE fading in, left-to-right on the way
    #      out WHILE fading out;
    #   3. the entrance starts the instant the storm dissipates;
    #   4. three seconds on screen, then the exit;
    #   5. two or more live banners stack DOWNWARD from the corner, and when one
    #      starts leaving, the ones below wait 0.3 s and then rise one slot over
    #      0.5 s on a cubic ease - and when several leave close together the
    #      rises ADD, so the speed is the algebraic sum of the eases. When ONE
    #      departure lifts several banners at once, their starts are staggered
    #      from top to bottom by 0.1 s each, so the stack closes as a wave
    #      travelling downward instead of all of it lurching on one frame;
    #   6. the vertical and the horizontal motions are fully independent, so a
    #      banner can be moving up and fading out at the same time.
    #
    # Rule 5 is why the position is not an index that snaps: each banner carries
    # a slot plus one eased DISPLACEMENT per departure that lifted it. Summing
    # displacements is exactly what makes overlapping rises add their velocities,
    # and it is also why this is a pure function of `t` - the state can be
    # reconstructed at any second, which a still and a render must agree on.
    # The stagger is a per-departure DELAY, so it rides the same structure: banner
    # `k` slots below the one leaving starts at 0.3 + k x 0.1.
    def _banner_peak(self):
        """How deep the stack ever gets; `info` prints it before a long run."""
        ev = []
        for e in self.banners:
            ev.append((e['t_in'], 1))
            ev.append((e['t_in'] + BAN_IN_S + BAN_HOLD_S + BAN_OUT_S, -1))
        ev.sort()
        n = best = 0
        for _, step in ev:
            n += step
            best = max(best, n)
        return best

    def _banner_exit(self, e):
        """The screen second a banner starts its exit animation."""
        return e['t_in'] + BAN_IN_S + BAN_HOLD_S

    def _banner_dir(self, level):
        """Extract one level's clip into the shared cache, once per level.

        `_cache/fx/` beside the asset pack is the pack's own convention: SMCY1.3
        is read-only and must not accumulate derived frames. Five seconds at the
        clip's own 60 fps is all a banner ever needs - one is on screen for
        4.6 s - and single extracts its banner the same way.
        """
        d = os.path.join(os.path.dirname(self.assets), '_cache', 'fx',
                         'sumban_' + level)
        n = len(os.listdir(d)) if os.path.isdir(d) else 0
        if n < BAN_FRAMES:
            os.makedirs(d, exist_ok=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i',
                            os.path.join(self.assets, 'summary', BAN_ART[level]),
                            '-t', '5', '-vf', 'fps=60', '-start_number', '0',
                            os.path.join(d, '%03d.png')], check=True)
            self.log('    banner art %s: %d frames' % (level, len(os.listdir(d))))
        if level not in self._banner_n:
            self._banner_n[level] = len([f for f in os.listdir(d)
                                         if f.endswith('.png')])
        return d

    def _banner_art(self, level, fi, w, h, tint=None):
        """One art frame, at the card's size. 20:1 in, 20:1 out - never squashed."""
        key = (level, int(fi), w, h, tint)
        im = self._banner_im.get(key)
        if im is not None:
            return im
        d = self._banner_dirs.get(level)
        if d is None:
            d = self._banner_dirs[level] = self._banner_dir(level)
        n = max(1, self._banner_n.get(level, BAN_FRAMES))
        p = os.path.join(d, '%03d.png' % (int(fi) % n))
        if not os.path.isfile(p):
            p = os.path.join(d, '000.png')
        im = Image.open(p).convert('RGB')
        if tint is not None:
            im = tint_banner(im, tint)
        im = im.resize((w, h), Image.LANCZOS)
        if len(self._banner_im) > 32:
            self._banner_im.clear()
        self._banner_im[key] = im
        return im

    def _banner_state(self, t):
        """Every banner alive at screen second `t`: its slot, offset and alpha.

        Deterministic in `t` alone. Nothing is accumulated frame to frame, so a
        still at any second is the same picture as the render of that second.
        """
        out = []
        B = self.banners
        for e in B:
            tin = e['t_in']
            if t < tin or t >= tin + BAN_IN_S + BAN_HOLD_S + BAN_OUT_S:
                continue
            tau = self._banner_exit(e)
            # everything above it: only what entered BEFORE this one can be, since
            # a banner always joins at the bottom of the stack. Collected first,
            # because the stagger depends on how far down the stack this one is.
            above = []
            for f in B:
                if f is e or (f['t_in'], f['num']) >= (tin, e['num']):
                    continue
                ftau = self._banner_exit(f)
                if f['t_in'] <= tin < ftau + BAN_OUT_S:
                    above.append(f)
            idx = 0.0
            for j, f in enumerate(above):
                idx += 1.0
                ftau = self._banner_exit(f)
                # its departure lifts this one a slot, 0.3 s later, over 0.5 s -
                # and one slot later for every banner between the two of them, so
                # the whole stack closes top-down, 0.1 s apart
                delay = BAN_RISE_DELAY + (len(above) - 1 - j) * BAN_RISE_STAGGER
                idx -= _ease01((t - ftau - delay) / BAN_RISE_S)
            p = _ease01((t - tin) / BAN_IN_S)
            q = _ease01((t - tau) / BAN_OUT_S)
            out.append(dict(e=e, idx=idx, alpha=p * (1.0 - q), off=(1.0 - p) + q))
        return out

    def _draw_banners(self, ov, t):
        """The live banners, over the cards.

        The art is resized to the card, the facts are printed on it exactly where
        single prints them (quoted at single's own 1700-wide card and scaled to
        this one), and the whole card is composited with a true ALPHA fade.
        Single darkens its card instead and pastes it opaque, which is invisible
        on the panorama's dark backdrop but would show as a black rectangle
        sliding over a map - the season's base is a real plate.
        """
        st = self._banner_state(t)
        if not st:
            return
        sc = self.sc
        w = max(1, int(round(BAN_W * sc)))
        h = max(1, int(round(BAN_H * sc)))
        bs = sc * (BAN_W / BAN_REF_W)          # single's card pixels -> layer px
        f_head = _bfont(F_BAN_EN, max(8, int(round(32 * bs))))
        f_head_c = _bfont(F_BAN_CJK, max(8, int(round(27 * bs))))
        f_l2 = _bfont(F_BAN_MONO, max(8, int(round(23 * bs))))
        f_l2_c = _bfont(F_BAN_CJK, max(8, int(round(23 * bs))))
        base = 14.0 * bs + f_head.getmetrics()[0]
        b2 = 52.0 * bs + f_l2_c.getmetrics()[0]
        x0 = 444.0 * bs
        sh = (12, 12, 12, 190)
        for s in st:
            e = s['e']
            card = self._banner_art(e['level'], (t - e['t_in']) * 60.0,
                                    w, h, e['tint']).convert('RGBA').copy()
            d2 = ImageDraw.Draw(card, 'RGBA')
            _banner_text(d2, (x0 + 2 * bs, base + 2 * bs), e['head'],
                         f_head, f_head_c, sh)
            _banner_text(d2, (x0, base), e['head'], f_head, f_head_c,
                         (255, 255, 255, 255))
            _banner_text(d2, (x0 + 2 * bs, b2 + 2 * bs), e['line2'],
                         f_l2, f_l2_c, sh)
            _banner_text(d2, (x0, b2), e['line2'], f_l2, f_l2_c,
                         (255, 245, 252, 255))
            aa = s['alpha']
            if aa < 0.999:
                card.putalpha(card.getchannel('A').point(lambda v: int(v * aa)))
            px = (REF_W - BAN_RIGHT - BAN_W + s['off'] * BAN_SLIDE) * sc
            py = (BAN_TOP + s['idx'] * (BAN_H + BAN_GAP)) * sc
            ov.alpha_composite(card, (int(round(px)), int(round(py))))

    # ---------------------------------------------------------- tally state
    def _tally_counts(self, t, k):
        """Continuous height of ruler `k` at screen second t. [SysTally.counts]

        One event per (system, criterion met) in `tally_book`, each ramping in
        over `P2_EASE_S` screen seconds from the moment it was met. Because the
        criteria are monotone - a running maximum never falls, and a name or a
        number is never withdrawn - a ruler can only ever grow, which is the
        ratchet: nothing has to be un-counted.
        """
        c = 0.0
        for b in self.tally_book:
            u = (t - b['t']) / max(1e-6, P2_EASE_S)
            if u <= 0.0:
                continue
            if u > 1.0:
                u = 1.0
            if b['cat'] == k:
                c += u * u * (3.0 - 2.0 * u)
        return c

    def _tally_number(self, t, k):
        """(value, alpha) for the printed count.

        [SysTally.numbers] The original flips the printed value at the halfway
        point of the ease and crossfades the outgoing digit into the incoming one.
        The flip is exact here; the crossfade's two half-alphas are what the
        original's `numbers()` returned, and at these sizes the flip alone is
        indistinguishable, so one value at full alpha is returned.
        """
        c = self._tally_counts(t, k)
        lo = int(math.floor(c + 1e-9))
        return (lo + (1 if (c - lo) >= 0.5 else 0)), 1.0

    # --------------------------------------------------------------- output
    def composite_rects(self, base, ov):
        """Paste only the five card rectangles. [4700-4710]

        The original's own optimisation, and the reason its file is 228 KB of
        carefully bounded work: a full-frame alpha pass at 8K is 100+ ms.
        """
        sc = self.sc
        for b in COMPOSITE_BOXES:
            x0, y0 = int(b[0] * sc), int(b[1] * sc)
            x1 = min(self.render_w, int((b[0] + b[2]) * sc))
            y1 = min(self.RH, int((b[1] + b[3]) * sc))
            if x1 <= x0 or y1 <= y0:
                continue
            p = ov.crop((x0, y0, x1, y1))
            base.paste(p, (x0, y0), p)
        return base

    def render_still(self, out_path, base='black', at=None, intro_t=None):
        """One still: the overlay over a plate, at output resolution.

        `intro_t` defaults to the still's own screen second, NOT to zero: at t=0
        the staggered fade `A(k) = 255 * ramp(t, 0.4+0.45k, 1.3+0.45k)` is still
        zero for every card, so a still taken at t=0 is legitimately blank. Pass
        an explicit small value to preview the fade-in itself.
        """
        if base in ('black', 'none'):
            plate = Image.new('RGB', (self.W, self.H), (0, 0, 0))
        elif base == 'map':
            plate = self._wpac_crop()
        else:
            plate = Image.open(base).convert('RGB')
        if plate.size != (self.W, self.H):
            plate = plate.resize((self.W, self.H), Image.LANCZOS)

        target = at if at is not None else datetime(2020, 11, 1)
        si = int(round(self.T.s_of(target) * self.FPS))
        ov = self.frame(si, intro_t=intro_t)
        if ov.size != (self.W, self.H):
            ov = ov.resize((self.W, self.H), Image.BICUBIC)
        out = plate.convert('RGBA')
        out.alpha_composite(ov)
        out = out.convert('RGB')
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
        out.save(out_path)
        return out_path

    def _wpac_crop(self):
        """A 16:9 band of the WPAC sheet, over as much of the track as fits."""
        im = Image.open(os.path.join(self.assets, 'map', 'basins', 'WPAC.png'))
        w, h = im.size
        ch = int(round(w * 9.0 / 16.0))
        lats = np.concatenate([st['S'].lat for st in self.storms])
        px_deg = w / 100.0
        best, bn = 0, -1
        for y0 in range(0, h - ch + 1, 5):
            n = int(((lats <= 70.0 - y0 / px_deg)
                     & (lats >= 70.0 - (y0 + ch) / px_deg)).sum())
            if n > bn:
                best, bn = y0, n
        return im.crop((0, best, w, best + ch)).convert('RGB')


# ---------------------------------------------------------------------------
# the encode chain (decode the plate, overlay, re-encode)
# ---------------------------------------------------------------------------

class Renderer:
    """One pass-2 render. Bounded queue, producer thread, ffmpeg in C.

    Measured at 8K for the 2020 season: decode + re-encode is 358 ms/frame
    (207 min), of which the data layer is under 1 ms. The solid-colour channel
    skips the decode and costs 121 ms/frame (70 min).
    """

    def __init__(self, overlay, out_path, crf=16, preset='medium',
                 queue_frames=8, log=print):
        self.ov, self.out = overlay, out_path
        self.crf, self.preset = crf, preset
        self.queue_frames, self.log = queue_frames, log

    def args(self, base, w, h, fps, n=0):
        ovw, ovh = self.ov.render_w, self.ov.RH
        enc = ['-c:v', 'libx264', '-preset', self.preset, '-crf', str(self.crf),
               '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
        if n:
            # a hard bound on the output, so an endless image source or an
            # unexpected stream length cannot run away
            enc += ['-frames:v', str(int(n))]
        ov_in = ['-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', '%dx%d' % (ovw, ovh),
                 '-r', '%g' % fps, '-i', 'pipe:0']
        if base in ('black', 'none'):
            return ([self.FF, '-hide_banner', '-loglevel', 'error', '-y'] + ov_in
                    + ['-f', 'lavfi', '-i', 'color=c=black:s=%dx%d:r=%g' % (w, h, fps),
                       '-filter_complex',
                       '[0:v]scale=%d:%d:flags=bilinear[o];'
                       '[1:v][o]overlay=0:0:shortest=1,format=yuv420p[v]' % (w, h),
                       '-map', '[v]'] + enc + [self.out])
        # A STILL plate is not a one-frame source: ffmpeg reads an image exactly
        # once, so without -loop 1 the overlay pipe is cut off after the first
        # frame and the write dies with EINVAL. Videos need no such flag.
        lead = (['-loop', '1', '-framerate', '%g' % fps]
                if _is_image(base) else [])
        return ([self.FF, '-hide_banner', '-loglevel', 'error', '-y'] + lead
                + ['-i', base] + ov_in
                + ['-filter_complex',
                   '[0:v]scale=%d:%d:flags=bicubic[p];'
                   '[1:v]scale=%d:%d:flags=bilinear[o];'
                   '[p][o]overlay=0:0:shortest=1,format=yuv420p[v]' % (w, h, w, h),
                   '-map', '[v]'] + enc + [self.out])

    FF = 'ffmpeg'

    def run(self, base='black', from_dt=None, to_dt=None, limit=0, quiet=0):
        import queue as _q
        import threading
        T, fps = self.ov.T, self.ov.FPS
        s0 = 0.0 if from_dt is None else T.s_of(from_dt)
        s1 = T.total if to_dt is None else T.s_of(to_dt)
        i0, n = int(round(s0 * fps)), int(round((s1 - s0) * fps))
        if limit:
            n = min(n, int(limit))
        if n <= 0:
            raise SystemExit('nothing to render')
        w, h = self.ov.W, self.ov.H
        self.log('  base %s | %d frames @ %g fps | %dx%d | crf %d %s'
                 % ('solid black' if base in ('black', 'none') else base,
                    n, fps, w, h, self.crf, self.preset))
        os.makedirs(os.path.dirname(os.path.abspath(self.out)) or '.', exist_ok=True)
        proc = subprocess.Popen(self.args(base, w, h, fps, n),
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        q = _q.Queue(maxsize=self.queue_frames)
        stop = threading.Event()
        err = []

        def produce():
            try:
                for k in range(n):
                    if stop.is_set():
                        break
                    q.put(self.ov.frame(i0 + k).tobytes())
            except Exception as exc:                               # noqa: BLE001
                err.append(exc)
            finally:
                q.put(None)

        th = threading.Thread(target=produce, daemon=True)
        th.start()
        t0, sent, tick = time.perf_counter(), 0, time.perf_counter()
        try:
            while True:
                item = q.get()
                if item is None:
                    break
                proc.stdin.write(item)
                sent += 1
                if not quiet and time.perf_counter() >= tick:
                    tick = time.perf_counter() + 5.0
                    el = time.perf_counter() - t0
                    r = sent / el if el else 0
                    self.log('    %6d/%d %5.1f%% %5.2f fps eta %s'
                             % (sent, n, 100.0 * sent / n, r,
                                _hms((n - sent) / r if r else 0)))
                if proc.poll() is not None:
                    break
        except BrokenPipeError:
            stop.set()
        finally:
            stop.set()
            th.join()
            try:
                proc.stdin.close()
            except Exception:                                      # noqa: BLE001
                pass
            perr = proc.stderr.read().decode('utf-8', 'replace')
            proc.wait()
        if err:
            raise SystemExit('overlay producer failed: %r' % (err[0],))
        if proc.returncode != 0:
            self.log(perr.strip()[-1200:])
            raise SystemExit('ffmpeg failed: %d' % proc.returncode)
        dt = time.perf_counter() - t0
        self.log('  wrote %s (%.1f MB, %d frames, %.1f min, %.2f fps)'
                 % (self.out, os.path.getsize(self.out) / 1e6, n, dt / 60, n / dt))
        return self.out


def _is_image(path):
    """True when the plate is a still rather than a video."""
    return os.path.splitext(path)[1].lower() in (
        '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp')


def _hms(sec):
    sec = int(max(0, sec))
    hh, rem = divmod(sec, 3600)
    mm, ss = divmod(rem, 60)
    return '%d:%02d:%02d' % (hh, mm, ss)


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def parse_at(txt):
    for f in ('%Y-%m-%dT%H:%M', '%Y-%m-%dT%H', '%Y-%m-%d %H', '%Y-%m-%d'):
        try:
            return datetime.strptime(txt, f)
        except ValueError:
            continue
    raise SystemExit('bad date %r' % txt)


def main(argv=None):
    ap = argparse.ArgumentParser(description='pass 2 data layer (rebuilt)')
    ap.add_argument('cmd', nargs='?', default='preview',
                    choices=('preview', 'info', 'render', 'map'))
    ap.add_argument('--season', default='.')
    ap.add_argument('--assets', default=_SKILL_ASSETS)
    ap.add_argument('--base', default='black',
                    help="black | map | a plate file")
    ap.add_argument('--size', default='1920x1080')
    ap.add_argument('--fps', type=float, default=60.0)
    ap.add_argument('--at', default='2020-11-01')
    ap.add_argument('--intro', type=float, default=None,
                    help='override the fade clock (defaults to the frame time)')
    ap.add_argument('--from', dest='from_', default=None)
    ap.add_argument('--to', dest='to_', default=None)
    ap.add_argument('--out', default=None)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--crf', type=int, default=16)
    ap.add_argument('--preset', default='medium')
    ap.add_argument('--render-w', type=int, default=None)
    ap.add_argument('--quiet', type=int, default=0)
    a = ap.parse_args(argv)
    a.season = os.path.abspath(a.season)
    a.assets = os.path.abspath(os.path.join(a.season, a.assets))
    if a.out:
        a.out = os.path.abspath(os.path.join(a.season, a.out))
    if a.base not in ('black', 'map'):
        a.base = os.path.abspath(os.path.join(a.season, a.base))

    size = tuple(int(v) for v in a.size.lower().split('x'))
    log = (lambda *x: None) if a.quiet else print
    ov = Overlay(a.season, a.assets, size=size, fps=a.fps, log=log,
                 render_w=a.render_w, intro=a.intro)

    if a.cmd == 'info':
        print('storms     : %d' % len(ov.storms))
        print('season     : %.2f s @ %g fps = %d frames'
              % (ov.T.total, ov.FPS, round(ov.T.total * ov.FPS)))
        print('rate axis  : 0 - %.0f' % ov.axis_max)
        print('ACE axis   : 0 - %.0f (year end %.1f, ruler 0 - %.0f)'
              % (ov.ace_axis, ov.C['ace_end'], ov.ace_full))
        print('death/loss : 0 - %.0f / 0 - %.0f   tally 0 - %.0f'
              % (ov.dead_full, ov.loss_full, ov.sys_full))
        print('banners    : %d, at most %d on screen at once'
              % (len(ov.banners), ov.banner_peak))
        print('blocks     : %d' % len(ov.T.blocks))
        return 0

    if a.cmd == 'map':
        # export the WPAC 16:9 band as a still, so it can be handed to the plate
        # channel as an ordinary image: the decode path then treats it exactly
        # like a video frame, and no special case is needed in the renderer
        out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'build_map_%s.png' % a.size)
        img = ov._wpac_crop()
        if img.size != (ov.W, ov.H):
            img = img.resize((ov.W, ov.H), Image.LANCZOS)
        os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
        img.save(out)
        print('  wrote %s  %s' % (out, img.size))
        for tag in (a.size,):
            pass
        return 0

    if a.cmd == 'render':
        t = time.perf_counter()
        ov.build_static()
        print('  static bake %.2f s' % (time.perf_counter() - t))
        out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'out', 'season_pass2_%s_%s_%gfps.mp4'
                                    % ('black' if a.base in ('black', 'none') else 'plate',
                                       a.size, a.fps))
        Renderer(ov, out, crf=a.crf, preset=a.preset, log=log).run(
            base=a.base, from_dt=parse_at(a.from_) if a.from_ else None,
            to_dt=parse_at(a.to_) if a.to_ else None, limit=a.limit, quiet=a.quiet)
        return 0

    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'preview', 'pass2_%s_%s.png'
                                % (a.base if a.base in ('black', 'map') else 'plate',
                                   a.at.replace(':', '')))
    ov.render_still(out, base=a.base, at=parse_at(a.at), intro_t=a.intro)
    print('  wrote %s' % out)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    raise SystemExit(main())
