# Pipeline reference - inputs, config schema, asset map, pitfalls

## 1. Input data

### 1.0 Folder layout

```
<work root>\
  res\SMCY1.3\                 shared asset pack
  res\_cache\                  shared extracted media
  single\<Storm>\
    sourcedata\                *.txt, landfall.txt, damage notes, satellite loop
    build\                     config + intermediates
    output\                    finished MP4 + poster
    旧版（无用）\               superseded cuts
```

All track/satellite paths in the config are **relative to `sourcedata`**;
intermediates go to `build\`, deliverables to `output\`.

### 1.1 The standard files

Every input lives in `sourcedata\` and is **found by name** - a config does not
have to name any of them.

| file | columns |
|---|---|
| `DB.txt` `TC.txt` `RV.txt` `EX.txt` | `time  lon  lat  wind  pres` - one segment per file, only the ones the storm has |
| `Num.txt` | three lines: disturbance number, depression number, UTC naming timestamp (`90W` / `24W` / `20260916120000`); preserve blank lines, no JMA-number row |
| `hypo.txt` | `True` (fictional) or `False` (real) - overrides `storm.hypothetical` |
| `landfall.txt` | `name  UTC time  lon  lat` |
| `damage.txt` | `lon  lat  name  dead+missing  loss` |

The long names (`2016_Typhoon_Meranti_BestTrack.txt`) still work: the short
`TC.txt` wins when both are present, so a folder can be migrated one file at a
time. An **empty** segment file is skipped rather than counted as a zero-point
segment, so placeholders can be created ahead of the data.

### 1.1a Timestamps

Two spellings are accepted everywhere:

```
YYYYMMDDHHmmSS         20260915120000      <- current
YYYY-MM-DD-HH-MM-SS  2026-09-15-12-00-00   <- legacy
```

The compact form is **14 digits** with an explicit four-digit year, including
historical years such as `16280813000000`. Two-digit years are rejected by the
single-storm renderer; no century pivot is used.

### 1.2 Landfall list (`landfall.txt`)

One landfall per line, whitespace separated:

```
<Name>   <UTC time>   <lon>   <lat>        <- current
Chiba    20260921090000 140.12  35.60
Izu Peninsula  2026-09-21-12-00-00  138.90  34.60

<Name>   <M.D> <HHz>   <lat>   <lon>       <- legacy
Itbayat  9.13 17z      20.79   121.84
```

* **Current layout is lon-first**, like the track files; the legacy layout is
  lat-first. The parser tells them apart by the token three from the right - a
  legacy month carries a dot, a timestamp never does.
* `<M.D>` is month.day, `<HHz>` is the UTC hour (`17z`); `HH:MMz` also parses.
* The name may contain spaces (`Izu Peninsula`) - the parser reads the four
  fixed columns off the right-hand end.
* The name is only a key: the config's `data.landfalls` block is matched to it
  case-insensitively and supplies `place`, `cat`, colours and label offsets.
* The year comes from the series start, rolling over at new year.
* A landfall whose config entry is missing still renders, with defaults.

### 1.3 Track text format

Every track file used by the renderer is plain text, one point per line,
whitespace separated, UTC. The interval is **read from the data**, so 3-hourly
and 6-hourly tracks both work - but keep it uniform inside one storm:

```
20260908180000    143.8    13.2    20    1005
2016-09-08-18-00-00    143.8    13.2    20    1005
   timestamp            lonE     latN   wind_kt  pressure_hpa
```

The segment files are concatenated into one continuous life cycle. **Naming them
`DB.txt` / `TC.txt` / `RV.txt` / `EX.txt` is enough** - `data.series` is optional
and only needed to override the discovery, reorder phases or apply skips:

| phase key | meaning | icon source |
|---|---|---|
| `DB` | tropical disturbance | `mainicon/disturbance/N-DB-aL.mp4` |
| `TC` | tropical cyclone (the best track itself) | `mainicon/tc_sshws/N-TD-D / N-TC-*` |
| `RV` | remnant vortex (post-analysis) | `mainicon/N-TC-X.mp4` |
| `EX` | extratropical | `mainicon/extratropicals/N-EX-EX.mp4` |

Tips
* Discovery runs in life-cycle order DB -> TC -> RV -> EX, preferring the short
  name and falling back to `*_Disturbance.txt` / `*_BestTrack.txt` /
  `*_Remnant_Vortex.txt` / `*_Extratropical.txt`.
* `skip_first` / `skip_last` are **counts**, and only exist on an explicit
  `data.series` entry. Two layouts are common:
  * *mutually exclusive segments* (Meranti, Dujuan): each file already holds only
    its own stretch, so nothing is skipped;
  * *master table + subset views* (Hagibis): the best-track file contains the
    disturbance and remnant segments too, so they are carved out with
    `skip_first: 2, skip_last: 2`.
  The segments must join into one continuous series - check the printed point
  count against the source document.
* The phase boundaries are blended automatically over ±2.5 h, so the icons
  cross-fade instead of snapping.
* The **wind column may be a placeholder** for the post-analysis stages (some
  agencies publish no wind there). Use ~15 kt and say so in the summary.

### 1.4 Reference storm (Meranti 2016) point budget

36 points / 210 h = disturbance (1) + best track minus its first point (27)
+ remnant vortex (5) + extratropical (3).

---

## 2. Config schema

```yaml
paths:
  storm:      ..                     # relative to YAML in <storm>/build/ (alias: workdir)
  assets:     ../../../res/SMCY1.3    # relative to the YAML file directory
  sourcedata: sourcedata              # default "sourcedata"; falls back to paths.storm
  build:      build                   # default "build"
  output:     output                  # default "output"
  tag:        v8                      # intermediate dirs icons_<tag>, fx_<tag>

output:
  mp4:    my_storm_animation.mp4      # written into paths.output
  poster: my_storm_poster.png

storm:
  id:          WP172016              # JTWC id, shown in HUD + banner
  name_en:     MERANTI
  name_cn:     莫兰蒂                # short form, used on the banner
  name_cn_long: 台风莫兰蒂           # HUD subtitle + intro
  hypothetical: true                 # fictional scenario: the intro card says
                                     # hypoTY / 假想台风 instead of TYPHOON / 台风
  title:       TYPHOON MERANTI       # HUD top-right + intro + summary header
  subtitle:    2016 - WESTERN NORTH PACIFIC - WP172016
  source_line: JTWC BEST TRACK + JMA POST-ANALYSIS     # under the HUD title
  intro_line:  台风莫兰蒂  -  2016  -  WESTERN NORTH PACIFIC
  intro_footer: JTWC BEST TRACK + JMA POST-ANALYSIS   |   HIMAWARI-8 B13   |   SMCY1.3
  credit_line: DATA  JTWC best track - ...             # bottom centre

data:
  series:                            # order matters
    - {file: disturb.txt, phase: DB}
    - {file: besttrack.txt, phase: TC, skip_first: true}
    - {file: remnant.txt,  phase: RV}
    - {file: extratrop.txt, phase: EX}
  reanalysis:                        # calibrated intensity, applied on top
    set:    [{h: 108, pres: 890}, {h: 114, wind: 175, pres: 880}]
    insert: [{h: 111, wind: 162, pres: 886}]     # sub-6h detail (e.g. a dip)
  ace_end_h: 162                     # ACE stops here (end of the TC stage)
  rapid_intensification: true        # >=2 band jump -> direct band-to-band blend
  ri_no_fx_bands: ['C1', 'C5+', 'C5++']   # jumps landing here blend WITHOUT the
                                          # ERI particle + sound
  ri_blend_frac: 0.45                # the blend finishes in this share of the
                                     # interval, then holds the new level
  plateau_ease: true                 # runs of equal values ease through their
                                     # midpoint instead of drawing flat treads
  ts_fx_skip_phases: ['EX']          # a gale recovering after extratropical
                                     # transition is NOT a TS upgrade

  # every local maximum counts, not just the strongest two: a storm with four
  # intensification episodes gets four entries. 1-2 peaks keep the frozen
  # two-line summary rhythm; 3+ switch to a compact one-line-per-peak block.
  peaks:
    - {h: 108.0, lon: 124.1, lat: 20.2, label: 'PEAK 1   165 kt / 890 hPa',
       color: [255,214,130], summary: '165 kt / 890 hPa - 09-13 06Z',
       graph: 'peak1 165/890', pano_dx: 152, pano_dy: -44, strong: '175 kt / 880 hPa'}
    - {h: 114.0, lon: 122.9, lat: 20.4, label: 'PEAK 2   175 kt / 880 hPa',
       color: [255,158,226], summary: '175 kt / 880 hPa - 09-13 12Z'}

  landfall_file: landfall.txt        # time + position come from here
  landfalls:                         # presentation only, keyed by that name
    Itbayat: {fx: landing5, landed: landed5, place: Itbayat, Batanes, PH,
              cat: 5, off_y: 62, simple_dx: -52, simple_dy: 6, color: [255,150,220]}
    # fx/landed: landing|landed (C1) or landing5|landed5 (C5)
    # off_y:     label y offset in the follow-cam view
    # simple_dx/simple_dy: panorama tag offset (dx<0 -> text to the left)
    # stamp is derived from the file; override it only if you must
    # without landfall_file, inline h/lon/lat per entry (old form) still works

  damage:                            # one per affected place
    - {cn: 福建, en: Fujian, CN, lon: 118.08, lat: 24.48, dead: 18, lost: 11, loss: '74.9'}
    # loss is in 亿 CNY; dead+lost == 0 -> no red pop-up
    # entries sharing a `group` are summed into ONE pop-up and the event sits on
    # the hardest-hit member - use it for places that are close together, or
    # their numbers play back to back and swamp each other
    - {cn: 福島県, lon: 140.47, lat: 37.75, dead: 38, group: 東北 3 県}
    - {cn: 宮城県, lon: 140.87, lat: 38.27, dead: 22, group: 東北 3 県}

view:
  tracking_span_lon: 22.8            # follow-cam field of view (deg lon)
  landfall_tag_hold: 0               # seconds a landfall name tag stays before it
                                     # fades; 0 = keep it.  Set a few seconds for
                                     # a storm that comes ashore many times.
  panorama: auto                     # fit the track below the banner ...
  warp: auto                         # pause at the real peak / landfall instead
                                     # of the default tau = 0.53 / 0.71
  wind_axis_max: 0                   # 0 = auto (>=185 kt, rounds up past the peak)
  ace_max: 0                         # 0 = auto (>=40)
  # ... or frame it by hand instead:
  panorama_span_lon: 52.0
  panorama_center:   [130.9, 25.6]

cloud:
  file: Meranti_2016_Himawari8_Infrared_B13.mp4
  extract_every: 4
  h0:     25.3333                    # data hour of source frame 0
  step_h: 0.0416667                  # data hours per source frame
  segment1: [0, 2721]
  segment2: [2724, 3342]
  resume_h: 184.25
  extract_every: 4                   # keep every Nth source frame
  crop: 0                            # centre crop of the source, px (0 = full);
                                     # a wide product only needs its centre
  banner: Summary-N-TC-C5.mp4        # optional override; by default the
                                     # banner art is picked from the PEAK level

banner:                              # text printed on that asset, 2 lines, right 3/4
  headline: 'WP172016   TYPHOON MERANTI   莫兰蒂'
  loss: CNY 11.91 bn
  deaths: '30'
  # line2 is DERIVED by default - peak / ACE / loss / deaths come straight from
  # the data, so they cannot drift. Set it only to override the whole line.
  # line2: 'PEAK 175 kt / 880 hPa      ACE 29.06 x10^4 kt2  ...'

audio:
  landfall_h: 0                      # 0 = last entry in landfall.txt -> weaken.ogg
  xt_h: 198.0
  weaken: true                       # false = no mainland weakening bed

# pacing for the floating damage numbers (top level, not under data:)
damage:
  min_gap: 0.50                      # queue the numbers this far apart, seconds
  popup_duration: 1.0                # how long each number lives (2.9 = default)
  spread: 135                        # fan neighbours apart, px (0 = off)

summary:                             # reserved end-card data; no displayed page
  sources: JTWC - JMA (Digital Typhoon) - Himawari-8 B13
  phase2_label: EXTRATROPICAL
  phase2_value: Yellow Sea - 09-17 00Z
  damage_label: DAMAGE  死亡+失踪 / 经济损失
  damage_lines: ['中国大陆  29 死 15 失踪 - CNY117.1 亿', ...]

credits:                             # bottom of the end card, one line each
  - 素材包   SMCY1.3   -   麦块姚是屑
  - 视频制作   Nekobenzene & DeepSeek V4.1 Flash
```

Anything omitted falls back to a sane default; `banner.line2` and
`summary.note` may be dropped entirely. `summary.*` and `credits` are retained
for a future redesign; the current end-card hook has zero duration and shows
no statistics/credits page. Panorama cards and the banner remain active.

---

## 3. Measuring the satellite-loop time mapping

The Digital Typhoon loops run at a **uniform** rate with one or more **jumps**,
so measure it instead of assuming.

```powershell
$sel = (0..16 | ForEach-Object { "eq(n\,$($_*200))" }) -join '+'
ffmpeg -v error -y -i cloud.mp4 -vf "select='$sel',crop=300:18:2:2,scale=440:26,tile=1x17" -frames:v 1 stamps.png
```

Read the burned-in timestamps off that strip. Worked example (Meranti):

| source frame | timestamp | delta |
|---|---|---|
| 0 | 2016-09-09 19:20 | – |
| 200 | 2016-09-10 03:40 | 100 frames = 4.1667 h |
| 1000 | 2016-09-11 13:00 | uniform |
| 2700 | 2016-09-14 11:50 | uniform |
| **2724** | **2016-09-16 10:15** | **jump of ≈46 h** |
| 3300 | 2016-09-17 10:15 | uniform again |

→ `step_h = 4.1667 h / 100 frames = 2.5 min = 0.0416667 h`,
`h0 = 25.3333` (data hours from the series t0), `segment1 = [0, 2721]`,
`segment2 = [2724, 3342]`, `resume_h = 184.25`.
The inset fades out across the gap and back in at `resume_h`.

`extract_every` = 4 keeps every 4th source frame (25 fps → 6.25 fps), which is
plenty because the cloud inset advances ~5× slower than the track.

---

## 4. Asset map (SMCY1.3)

| Config / feature | Asset |
|---|---|
| map base | `map/sources/Blue_Marble_2002_bg21600_05.png` + `Graticule.png` + `RegionLine.png` |
| TC icons | `mainicon/tc_sshws/N-TD-D, N-TC-TS, N-TC-C1..C5.mp4` |
| disturbance / remnant / extratropical | `mainicon/disturbance/N-DB-aL.mp4`, `mainicon/N-TC-X.mp4`, `mainicon/extratropicals/N-EX-EX.mp4` |
| intro logo | `gui/TY-LOGO-N.mp4` |
| landfall impact / marker | `landfall/[Landing]C1.mp4` / `Landed-C1.mp4` (also the `…C5` pair) |
| TD→TS flash | `particle/note_ts.mp4` |
| damage particles | `particle/sweep.gif` |
| ACE colour ruler | `gui/ace/ace_color_1000.png` |
| panorama banner | `summary/Summary-N-TC-<PEAK LEVEL>.mp4` - chosen from the storm's peak category |
| credit for third-party imagery | whatever the client asks for - dapiya.cn supplied the BW loop for Dolphin and had to be named in the end card |
| SFX | `sound/random/note_ts.ogg`, `noice_category4.ogg`, `noice_170.ogg`, `weaken.ogg`; `landfall/sound.landfall.C1.ogg` / `…C5.ogg`; `sound/damages/sweep1.ogg` |

`extract_icons` decimates the 60 fps icon loops to 20 fps; the landfall impact
stays at 60 fps (never slow it down).

---

## 5. Pitfalls

0. **A hypothetical storm declares itself.** Set `storm.hypothetical: true` and
   the intro card's big title reads `hypoTY ...` instead of `TYPHOON ...` and its
   second line reads `假想台风...`. Everything else is unchanged, so a real and a
   fictional storm can sit side by side without being mistaken for each other.
1. **Map projection.** The base map is **Pacific-centred**: `x = lonE/360*10800`,
   `y = (90-lat)/180*5400`. Assuming `-180..180` shifts everything by 180° and the
   track lands in open ocean. Verify with a known city before trusting a frame.
2. **Non-ASCII glyphs.** Consolas/Microsoft YaHei render a tofu box for many
   symbols. Keep on-screen text ASCII (plus Chinese) and route Chinese through
   `mixed()` so both fonts share a baseline.
3. **Camera shake.** Integer-pixel crops of a 2-3× upscaled map produce 2-3 px
   steps. Use the fractional `warpAffine` offset and a ~1.7 s smoothing window.
4. **Cloud inset.** Crop the burned-in watermark (centre 500×500 of a 650×650
   frame), feather it radially and screen-blend so no square edge shows.
5. **Panorama framing.** All annotations must clear the summary banner
   (top 235 px). Keep the track below `lat_top - 0.2315*span_lat`.
6. **Label collisions.** Closely spaced landfalls (Kinmen/Xiamen are ~10 px
   apart in the panorama) need explicit `simple_dy` offsets; merging them makes
   the count look wrong.
7. **Zero casualties.** `dead+lost == 0` must not produce a red "0人" pop-up.
8. **ACE samples the 00/06/12/18 UTC synoptic grid.** The intensity is resampled
   onto those hours and `v^2` summed there - the WMO convention, valid whatever
   the spacing of the fixes, and identical to the plain discrete sum for a track
   that already sits on the grid. Count up to `ace_end_h`; the bar is *revealed*,
   never stretched, and ramps continuously so it cannot advance in bursts.
9. **A dense track needs a smooth curve.** Linear interpolation between
  3-hourly fixes turns every plateau into a flat tread and every change into a
  corner - the intensity graph looks like a staircase. Interpolate with the
  shape-preserving cubic instead; a natural cubic is worse, it invents peaks.
  **Then collapse the plateaus**: a run of equal values becomes ONE knot at the
  middle of that run, so `50 55 60 60 60 60 60 65 70` eases slowly through 60
  and never draws a tread. Wind and pressure are collapsed and interpolated
  **independently** - a pressure plateau must not drag the wind curve with it.
  Set `data.plateau_ease: false` to go back to knot-per-fix.
10. **Phase boundaries are data-driven.** Never hard-code the hour where the
   disturbance becomes a tropical cyclone, or where the remnant vortex and the
   extratropical stage begin - derive them from the series, or a storm whose
   timeline sits elsewhere will be coloured as the wrong phase.
11. **Super-cyclone landfalls are automatic.** Above 155 kt the C6 impact clip
   and sound are selected from the intensity at landfall, and the effect is
   scaled by `1 + (wind - 155) * 3 %`. Above 185 kt the theme colour continues
   past deep blue to black at 200 kt, and a peak above 155 kt recolours the
   panorama banner. The typhoon icon itself stays on the C5 art.
12. **Many damage points, little time.** A compact disaster area (13 Japanese
   prefectures) reaches minimum distance within ~2.5 s of screen time. Three
   fixes, in order of importance: **merge nearby places with `group`** (15 events
   became 6), then queue them (`min_gap`), then shorten (`popup_duration`) and
   fan them out (`spread`).
13. **Never hard-code a date fragment.** The timeline chip, the peak sub-labels
   and the cell text all derive their year/month from `S.t0`; a literal `2016-`
   or `SEP` is right for exactly one storm.
14. **Many landfalls need a hold.** Landfall name tags persist by design so the
   map keeps showing where the storm came ashore. A storm that crosses an
   archipelago six times in 21 hours piles them into an unreadable heap - set
   `view.landfall_tag_hold` and fan `off_y` out instead. The map markers still
   stay.
15. **The queue has a deadline.** The follow-cam keeps moving, so a queue that
   runs too long ends with its last numbers pushed off frame - or over the HUD.
   Check `info`: the whole queue should finish while the affected area is still
   well placed. Tighten `min_gap` rather than letting it run.
16. **The end card's LIFETIME is the tropical-cyclone stage only.** The
    disturbance, remnant-vortex and extratropical stretches are tracked and
    coloured, but they are not the storm's lifetime - derive the window from the
    `TC` entries in `S.phase`, never from the series start and end.
17. **A rapid-intensification jump reads as sudden.** Blend straight from the
    source band to the target band, finish that blend in the first ~45 % of the
    interval (`ri_blend_frac`) and hold the new level for the rest; the ERI
    particle and sound are suppressed for jumps landing in the bands listed in
    `ri_no_fx_bands` (by default `C1`, `C5+`, `C5++`).
18. **The banner art follows the peak category.** A C2 storm wearing the C5
    banner is a hard-coded default showing through. Pick
    `summary/Summary-N-TC-<peak level>.mp4`; `banner.asset` overrides it.
19. **The intensity graph has two axes.** Pressure ticks on the LEFT, wind ticks
    on the RIGHT - the category gridlines belong to the wind curve, so their
    values go right.
20. **Every TROPICAL upgrade gets its own effect.** A storm can weaken below
    34 kt and re-intensify; `note_ts` fires at each TD -> TS crossing, not just
    the first. Crossings inside the extratropical phase are skipped
    (`data.ts_fx_skip_phases`) - winds recovering inside an extratropical system
    are not a tropical storm upgrade.
21. **Every line that can carry Chinese goes through `mixed()`.** The intro
    footer (`假想情景`), the HUD credit line (which names agencies: `民政部`,
    `消防庁`, `应急管理部`), the banner and the summary header. Drawn with the
    Latin font alone each becomes a row of tofu boxes - and this one shipped
    unnoticed for two storms because the placeholder boxes look like text at a
    glance. Centre with `mixed_w()`, never `anchor='mm'`.
22. **Credit any third-party imagery.** A satellite loop from an outside
    product must be named in the end card (`credits`) and in `storm.credit_line`.
    Cropping the provider's burned-in watermark out is fine *provided* the credit
    is on screen - never strip an attribution and leave nothing in its place.
23. **A cloud loop with a map can be checked against the track.** When the
    imagery carries coastlines, the storm's position relative to land at a known
    timestamp independently verifies the frame-to-data-hour mapping: project the
    track onto the frame at the event time and see whether the eye sits where the
    data puts it. Do this before trusting a hand-built timing report.
24. **Retiming a track is a data edit, not a style one.** To make a storm move
   faster while keeping its trajectory, compress the *timestamps*
   (`tau = integral of 1/speed`) - never drop fixes, which leaves the speed
   alone and only coarsens the sampling. Ramp the speed in and out over ~15 h so
   the joins stay smooth, and remap the landfall file, the peak hours,
   `ace_end_h` and any date text in the same pass. The fixes will fall off the
   synoptic grid, which is exactly why rule 8 resamples rather than filtering.

## Pre-render overview

`python scripts/typhoon_anim.py --config <config> preview` writes
`<storm>/output/preview.png` at the global map's native pixel density (60 px/degree; about 8534x4800 for the current WPAC window) without starting video rendering.
`render` and `all` generate the same still before constructing the animation
renderer or launching the video encoder. Preview failure stops video rendering.
Existing MP4s are not modified by the `preview` command.

The self-contained single script carries local copies of season pass 1's
`pick_basin`, `basin_window`, and `fit_aspect` rules and stage 2 overview's
world-map crop and trail painter. It selects the basin by covered-area ratio,
unions its bounds with the track plus 5-degree padding (10 degrees south),
grows the window to 16:9, and samples `map/basins/EARTH.png`. Intensity colours,
phase blending and dashed remnant tracks follow the season still. No icons,
fix dots, HUD or summary cards are drawn. The preview path has no black outline and uses 30% of its original coloured-stroke width; animation paths are unchanged. Shared code is copied with a
`_preview_` prefix, never imported from another skill branch. This framing is
for the still; the animation's existing camera is unchanged.

## Export dimensions and current-source rerenders

`output.width` / `output.height` optionally select positive even output sizes.
The default is 1920x1080; use 2560/1440 for the 2K120 export. The author canvas
remains 1920x1080, scaled with Lanczos by FFmpeg. See
[rendering performance](rendering-performance.md) for implementation details.

On a rerender from updated inputs, read the current project `sourcedata`
directly. Do not substitute a historical build snapshot or inline series.
Recompute peak times, positions, labels and totals from the current tables;
relative peak hours become stale when the track start changes. Inspect explicit
`data.reanalysis`, `data.damage` and `ace_end_h` overrides for conflicts with
the requested current-source run. Preserve intentional overrides unless the
task makes the current source tables authoritative. Keep presentation settings
separate from old numerical annotations. Hash input text files at start/end
when a long background render must detect concurrent edits.

Path resolution: `paths.storm`/`workdir`, `assets`, and explicit `cache` are relative to the configuration file directory. `sourcedata`, `build`, and `output` are relative to the resolved storm directory. Absolute paths remain supported.

## TC-only ACE and unobstructed ending framing

ACE includes only synoptic 00/06/12/18Z samples inside the actual start/end
fix times of `data.series` blocks whose phase is `TC`, after skip_first/skip_last.
Other phases (DB, RV, EX) never contribute, even above 34 kt. The existing
34 kt threshold, raw intensity interpolation and ace_end_h cutoff remain.
Any explicit banner.line2 ACE figure must be refreshed when the rule/data changes.

Use `view.panorama: auto` for project endings. Auto framing fits the full path
between both 440 px side cards (40 px outer margins), with another 40 px
clearance from each card and the 235 px top banner, and 48 px bottom clearance.
The minimum longitude span is 22.8 degrees. Center the track within that clear
rectangle; do not cap this fit to a regional map window. The main animation
continues to use the world map. Explicit manual panorama configs remain supported.

Optional geography is bundled at parent skill `assets/geo/`, separate from the project workspace. Normal rendering does not require it.
