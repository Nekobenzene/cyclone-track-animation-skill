# Season style spec

The frozen look. Everything here is a contract: two seasons rendered months
apart must come out identical, so a value in this file is changed only when the
operator asks for it, and then it is changed here *and* in the code in the same
breath.

Read with `season-workflow.md` (the rules) and the table of constants at the top
of `season_pass1.py` Section B.

---

## 1. Frame

| constant | value | meaning |
|---|---|---|
| `REF_W` | 1920 | the width every size ratio is authored at |
| `W, H` | from `--size` | 1920x1080 default; even numbers only (`yuv420p`) |
| `FPS` | from `--fps` | 60 default; 120 for the top-quality master |
| window | the basin rule | see `season-workflow.md` section 4 |
| camera | **fixed** | a season has no camera move; that is stage 5 |

The frame's degree aspect always equals its pixel aspect. The map is never
stretched - see the workflow book.

## 2. The icon is the unit

Every visible size is `ratio x ICON`, where `ICON = ICON_PX * (W / REF_W)`.

| constant | value | what it sizes |
|---|---|---|
| `ICON_PX` | 140.0 | the icon glyph at 1920 wide (**70 px at 540p**) |
| `HALO_K` | 1.653 | halo outer diameter |
| `HALO_BASE` | 384.0 | the diameter that ratio was measured from |
| `ERI_K` | 1.441 | ERI burst box |
| `TSFX_K` | 1.822 | TD -> TS upgrade flash |
| `LFX_K` | 2.966 x 1.2 | landfall impact at 170 kt |
| `MARKER_K` | 0.137 | the `Landed` marker box |
| `LABEL_K` | 0.10 | map label cap height |
| `TRAIL_K` | 0.00375/2 x (1920/140) x 3/2 x 1.20 | path stroke |
| `DOT_D_K` | 0.0025/4 x (1920/140) x 2/3 x 1.15 | fix-marker diameter |

The ratios in the upper block came from the single-storm renderer, which is the
reference for the look. Measured there at `SC = 1.0` against its 236 px glyph:
halo 390, ERI 340, TS upgrade 430, landfall 700, path 12, marker 4.

`TRAIL_K` and `DOT_D_K` are written long-hand only to keep the operator's chain
of adjustments readable. They are icon ratios like the rest.

Worked example at four sizes:

| | 960 | 1920 | 4800 | 8534 |
|---|---|---|---|---|
| `ICON` | 70 | 140 | 350 | 622 |
| path | 3.24 | 6.48 | 16.20 | 28.80 |
| marker diameter | 0.46 | 0.92 | 2.30 | 4.09 |
| halo outer | 116 | 231 | 578 | 1028 |

**A bare pixel number is a bug.** If a new element is added, decide whether it is
geography (rides the icon) or screen furniture (rides the frame), then express it
as a ratio. The path and the marker are geography, like the icon, because a
storm is a thing of a certain size on the map.

## 3. The two-scale trap

`SeasonR` sets `ICON = ICON_PX * SC`. The shared helpers `trail()` and `glow()`
**also** multiply by `SC`. A multiplier handed to them must be `K * ICON / base`
with **no second `SC`**, or the element grows as `SC²`:

* once made a 1:1 render draw a path 4x fatter than a 4800 one
* once made a 1:1 render draw a path 45x fatter than a 540p one

If a size looks wrong only at one resolution, this is the first thing to check.

## 4. Time

| constant | value |
|---|---|
| `SE_ACT` | 0.5 days/s while active |
| `SE_QUIET` | 15.0 days/s when quiet |
| `SE_PAD` | 1.0 day added each side of a block |
| `SE_EASE` | 1.0 day of quadratic ease at each join |
| `SE_MERGE_D` | blocks within 1.0 day merge |
| `SE_FADE_START` | 1.0 day after death, the trail starts fading |
| `SE_FADE_LEN` | 5.0 days to fade out completely |
| `ICON_EXT_H` | 6.0 h the icon fades **in place** beyond each end of the track |
| `ICON_GROW_KT` | 155.0 kt |
| `ICON_GROW_MAX` | 1.32, the cap on that growth |

The icon fade plays outside the path animation: `h` is clamped to the ends of the
track so the icon does not creep along the first or last segment while it fades.
Every painted part of a track is therefore always shown at full icon opacity.

## 5. Intensity bands and colours

| band | wind kt | colour |
|---|---|---|
| TD | < 34 | (196, 220, 255) |
| TS | 34-63 | (58, 226, 92) |
| C1 | 64-82 | (255, 232, 40) |
| C2 | 83-95 | (255, 158, 30) |
| C3 | 96-112 | (244, 86, 32) |
| C4 | 113-136 | (232, 34, 28) |
| C5 | 137-155 | (255, 60, 226) |
| C5+ | 156-169 | (214, 106, 255) |
| C5++ | 170+ | a ramp: deep purple -> deep blue at 185 -> ACE fill endpoint #C6E8FF at 200 |

Phase colours: `DB` (206, 220, 236), `RV` (176, 192, 214), `EX` (152, 172, 214).

Level changes cross-fade **linearly in wind**, phase changes **linearly in
time** (`TRANS_H = 2.5` h). Inside a rapid-intensification window the cross-fade
is sharpened - the level always follows the wind, never the event's target.

The track is drawn as a dark outer stroke plus an intensity-coloured inner
stroke sampled continuously; the remnant-vortex phase is dashed.

## 6. The four motion effects

| effect | when | size |
|---|---|---|
| TD -> TS upgrade | once per 34 kt crossing | `TSFX_K x ICON` |
| ERI burst | over the rapid-intensification window, GIF midpoint on the event midpoint, `RI_FX_DUR = 0.3` s | `ERI_K x ICON` |
| landfall impact | 1 s at the landfall, `scale = landfall_scale(wind)` | `LFX_K x ICON x scale x fade` |
| landfall marker | from the landfall on, spinning, one turn per 1.6 s, shrink-away tail dropped | `MARKER_K x ICON` (never scaled by intensity) |

The upgrade flash is rotated by the icon's angle at the trigger, latched, so the
two line up.

### Landfall size

Two multipliers, both linear in wind, both applied:

* `landfall_scale(wind)` - above 155 kt, **+5 % of linear size per kt**
* `fade` - at or below 170 kt, **-0.5 % per kt below**, floor 0

    fade = max(0, 1 - 0.005 x (170 - min(wind, 200)))

So a 60 kt landfall draws at 0.45 of the 170 kt size and a 151 kt one at 0.91,
before `landfall_scale` is applied. The gradient is deliberately steep: a weak
landfall must read as clearly smaller than a violent one.

## 7. Labels

| constant | value |
|---|---|
| `LABEL_K` | 0.10 x ICON |
| `LABEL_SIDE` | -1 (right-aligned on the icon's left shoulder) |
| `LABEL_DX` | 0.44 of the icon width |
| `LABEL_DY` | 0.16 of the icon height |
| `LABEL_HOLD_S` | 2.0 s, then it fades (`LABEL_FADE_S`) |

The label is tucked against the icon so its right end all but touches it.
`LABEL_SIDE = +1` mirrors it to the right (left-aligned) if that ever reads
better.

Text: `DB` -> the invest number, `TC` before naming -> the depression number,
after naming -> the storm's English name.

## 8. Icon growth

Above `ICON_GROW_KT = 155` kt the icon grows **+1 % of linear size per knot**,
cumulative, capped at `ICON_GROW_MAX = 1.32`.

## 9. Sound

No BGM. The inventory is the single storm's, laid on the season's time base:

| cue | source | gain |
|---|---|---|
| TD -> TS upgrade | `sound/random/note_ts.ogg` | 0.70 x 2/3 |
| category-4 bed | `sound/random/noice_category4.ogg`, tiled C4 -> C5 end | 0.34 x 2/3 |
| 170 kt bed | `sound/random/noice_170.ogg`, tiled w170a -> w170b | 0.42 x 2/3 |
| ERI | `sound/random/Rapid Intensification.ogg` | 0.70 |
| landfall | `landfall/sound.landfall.<LEVEL>.ogg` | per level, table below |

Landfall gains: TD 0.90, TS 1.00, C1 0.95, C2 0.95, C3 0.70, C4 0.50, C5 0.35,
C5+ 0.35, C5++ 0.32. A non-tropical phase brings no landfall sound.

The whole mix is peak-normalised if it exceeds 1.0. With 26 storms it always
does, so every cue is scaled by the same factor and a lone landfall sounds
quieter than it would on its own. That is the accepted cost of one bus; it is
**not** a bug to "fix" by clipping.

## 10. Freeze discipline

* Two seasons rendered months apart must match. If a change would alter an
  already-delivered season, it is a new version, not an edit.
* The style is the contract. This file and `season-workflow.md` win over any
  local improvement in the code.
* When a constant changes, change it here in the same commit. A spec that has
  drifted from the code is worse than no spec.

---

## 11. Stage 6 — the cards

The data layer is screen furniture, so every size here is a ratio of the CARD, not
of `ICON`, in author units at 1920x1080 (multiplied by `sc`). Read with
`season-cards.md`, which carries the models and formats; this section is the
frozen geometry.

### The column

480 wide at x = 10, gaps derived from `_COL_GAP = 6`:

| card | box | height |
|---|---|---|
| identity | `(10, 10, 480, 80)` | 80 |
| damage | `(10, 96, 480, 94)` | 94 |
| ACE | `(10, 196, 480, 264)` | 264 |
| tally | `(10, 466, 480, 146)` | 146 |
| timeline | baseline y = 990, x 60 → 1860 | — |

The column is 602 tall and the timeline sits at 930, leaving 318 units of clear
map between them.

| constant | value | what it sizes |
|---|---|---|
| `_COL_GAP` | 6 | between cards |
| `BOX_*` | above | each card; the `y` is derived from the card above |
| `TALLY_INSET` | 0.021 | the tally's and the ACE ruler's shared left inset, as a fraction of the card width |
| `TALLY_ASPECT` | 260 / 16 | one tally ruler's width : height — the DAMAGE well's own ratio |
| `TALLY_BAR_W` | 370.0 | one ruler, which fixes its thickness at 22.77 |
| `TALLY_TOP` | 16.0 | card top to the first ruler |
| `TALLY_LBL_X` / `TALLY_NUM_X` | 392.1 / 432.1 | label and count, from the card's left |
| `TALLY_LBL_CAP` / `TALLY_NUM_CAP` | 14.0 | both |
| `DIGIT_CELL` | 0.85 | tabular-figure cell, as a fraction of the widest digit's advance |
| `P2_EASE_S` | 1.5 | the cubic ramp every count arrives on, in SCREEN seconds |
| `P2_BOOK_H` | 6.0 | hours after a storm dissipates before it is booked |
| `P2_ACE_MIN_KT` | 34.0 | the wind a system must reach to count towards ACE — the cumulative curve's own gate, so the rate and the total are one metric. `0.0` counts every depression for its whole life and the two curves then disagree |

| constant | value | what it sizes |
|---|---|---|
| `BAN_W` / `BAN_H` | 1400 / 70 | the summary banner's card, author units; the art is 20:1 |
| `BAN_RIGHT` / `BAN_TOP` | 24 / 20 | its home in the top-right corner |
| `BAN_GAP` | 6 | between two stacked banners |
| `BAN_SLIDE` | 460 | how far right of home it enters from |
| `BAN_IN_S` / `BAN_HOLD_S` / `BAN_OUT_S` | 0.8 / 3.0 / 0.8 | enter, hold, exit, in screen seconds |
| `BAN_RISE_DELAY` / `BAN_RISE_S` | 0.3 / 0.5 | after a departure, before the rest rise; and the rise itself |
| `BAN_RISE_STAGGER` | 0.1 | each banner one slot further down starts its rise this much later |
| `BAN_REF_W` | 1700 | single's own card width, which the type offsets are quoted at |
| `BAN_FRAMES` | 300 | 5 s of banner art extracted per level, at its 60 fps |

The tally's stacking pitch is **not** a constant: it is `height - (stroke - 1)` in
layer pixels, computed from the live `sc`, because that is what makes neighbouring
rulers share one border stroke instead of drawing two. See `season-cards.md` §5.

### Type and colour

| constant | value |
|---|---|
| `P2_C['panel']` | `(7, 11, 22, 205)` |
| `P2_C['txt']` / `['dim']` | `(232, 240, 252)` / `(150, 163, 184)` |
| `P2_C['red']` / `['loss']` | `(248, 96, 96)` / `(250, 214, 96)` |
| clock cap | 30 (date) / 32 (time), tabular figures |
| damage row pitch | 18, 42, 16 — the original's, unchanged |
| bar frame | white `(255, 255, 255, 204)`, `max(1, int(sc))` thick, drawn INSIDE |

The tally palette is read off `mainicon/tc_sshws/N-TC-*.mp4` — see
`season-cards.md` §5 for the values and the method. It is not a free choice.

### The ACE ruler's band

`RULER_BAND = 0.4` of the height the full `ace_color_1000.png` strip would take
if placed across the card at its own aspect. The art is CROPPED to that band, not
scaled down to it: scaling would shrink the bar horizontally too and the ramp would
read as compressed.

### Output size

`render_w = min(3840, max(1920, W))`. At 8534 the layer is drawn at 3840 and
upscaled 2.22x. This is a deliberate cap, not an oversight: native 8K costs
177 ms/frame against 29 ms and native 16K 1033 ms, and the sharpness difference at
8K is not visible at 1:1 or at 2-3x zoom.

## Latin and numeric typography

Use bundled Saira for all drawn English and numeric typography. Former regular
Consolas roles use Saira Regular; former bold Consolas/Arial roles use Saira
Bold; semibold UI titles and season data cards use Saira SemiBold. Fonts resolve
from the parent skill assets/SMCY1.3/font/_saira_master/Saira/fonts/ttf folder,
independent of project assets overrides. Chinese uses bundled Source Han Sans SC.
Preserve the existing season data-card tabular digit placement. Pre-rendered
text embedded in video/image source art is part of that art, not dynamic type.

## Bundled Chinese font routing

Chinese text uses Source Han Sans SC from parent-skill
`assets/SMCY1.3/font/SourceHanSansSC/`: Regular for body text, Medium for
secondary labels where provided, Bold for emphasized labels and banners.
English/digits remain Saira. Neither renderer requires Microsoft YaHei or
Windows font paths. The original Adobe SIL OFL 1.1 license is bundled as
`LICENSE.txt`; retain it and font copyright notices when distributing.
Official download URLs and SHA-256 hashes are recorded in `source.json`.
Font paths are anchored to the skill, independent of project asset overrides.

## High-wind icons

EX retains its original sprite at 30 kt and below. Above 30 kt, smoothly blend
in recolouring over 30..37 kt, preserving the neutral white core and lettering.
Sample bright chromatic pixels from four rotation frames of each actual TC
sprite, including rendered high-wind tints. Place TD through C5+ colours at
their finite band midpoints and interpolate linearly in RGB without plateaus.
Keep 170/185 kt purple/blue anchors; at 200 kt sample the rightmost column of
`gui/ace/ace_color_1000.png` (currently `#C6E8FF`). Preserve authored brightness;
do not normalize exposure from each frame's histogram. Do not add an outline.

At >=100 kt, EX carries blue-white lightning separated from
`mainicon/tc_sshws/N-TC-C6(7).mp4`. Compare matching angles across its six turns
to remove static body/ring edges, protect the centre lettering, and cache
derived layers at `fx/ex_lightning_gray_v1`. EX never triggers TD-to-TS flash
or audio, including when the tropical upgrade list is empty.

TC's 185..200 kt theme also interpolates to `#C6E8FF`; season overview tracks
use the same endpoint. Keep existing TC category transitions and tint rules.
The TC numeral 5 smoothsteps to black-red `#1E0309` over 185..200 kt through a
cached mask of the original numeral, applied after glow. Preserve the white
eye, rings and lightning. Single-only card/banner rules do not apply here.

For all 200–500 kt body/halo nodes, use [extreme intensity rules](../../references/extreme-intensity.md). Cap both landfall size multipliers at 200 kt while retaining actual wind for colour and statistics.
