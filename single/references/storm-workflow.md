# Section A - single-storm track animation

The frozen SMCY1.3 look for **one storm**: a follow camera, an intensity-coloured
path, animated category icons, an ACE reveal bar, damage pop-ups and a pull-back/panorama
ending. Everything that defines the look lives in `typhoon_anim.py`; a
new storm needs **a config file and input data only**.

> This half renders a single storm and stops there.

---

# Typhoon track animation (SMCY1.3 style)

Everything that defines the **look** is already frozen in
`typhoon_anim.py`. A new storm needs **a config file and input data only** -
never restyle, never re-lay-out, never "improve" the HUD. If a storm genuinely
cannot be expressed by the config schema, extend the schema, not the style.

## Files

| Path | Role |
|---|---|
| `typhoon_anim.py` | the renderer (frozen style; config driven) |
| `../examples/meranti_2016.yaml` | reference config - Meranti 2016 (WP172016), reproduces the shipped video pixel-for-pixel |
| `storm-style-spec.md` | exact layout / fonts / colours / timings - read before changing anything |
| `storm-pipeline.md` | input data formats, config schema, asset mapping, pitfalls |

## Directory layout (one folder per storm)

The work root groups storm projects under `single/`, seasons under `season/`,
and shared resources under `res/`. Never write a second storm's files into an
existing storm folder.

Two track-file naming conventions are in use. Section A configs name their
files **explicitly** in `data.series`, so either works and nothing here depends
on the names; the season folders use the short `DB.txt` / `TC.txt` / `RV.txt` /
`EX.txt` used by the multi-storm tooling.

```
<work root>\
  res\SMCY1.3\                 shared asset pack (read-only)
  single\<Storm>\              e.g. 2016Meranti
    sourcedata\                ALL inputs
      DB.txt TC.txt            track segments - only the ones the storm has
      RV.txt EX.txt            optional continuation segments
      Num.txt                  invest / depression / naming UTC time, one per line
      hypo.txt                 True or False - is this a fictional storm?
      landfall.txt             normalised landfall list (may be empty)
      damage.txt               lon lat name dead+missing loss
      <satellite loop>.mp4     optional Himawari-8 infrared loop
    build\                     config + a storm's own intermediates
      <storm>.yaml             the config
      cloud\ tmp\              regenerable, this storm only
      video_silent.mp4  audio.wav
    output\                    finished MP4 + poster
    旧版（无用）\               superseded cuts

  res\
    _cache\                    the library's art, extracted ONCE for every storm
      icons\ fx\
```

**The extracted library art is shared, never per storm.** `icons_*` / `fx_*` used
to be written into each storm's `build\`, which costs a full copy of the library
per storm - about 550 MB each. They are identical for every storm, so they live
in `res\_cache\` and extraction is idempotent (a folder that already holds
the frames is left alone). A storm's `build\` keeps only what is genuinely its
own: `tmp\`, `cloud\`, `audio.wav`, `video_silent.mp4`. `paths.cache` overrides
the location.

`paths.sourcedata` / `paths.build` / `paths.output` default to those names, and
`paths.assets` retains the legacy sibling-pack fallback. In the current
workspace layout, set it explicitly; cache defaults beside the asset pack:

```yaml
paths:
  storm: C:\...\work\single\2016Meranti
  assets: C:\...\work\res\SMCY1.3
  tag:   v8
```

## Workflow for a new typhoon

### 0. Prerequisites

```powershell
python -m pip install pyyaml            # only if not installed
python -c "import numpy, cv2, PIL"      # numpy, opencv-python, pillow
ffmpeg -version                         # must be on PATH
```

The SMCY1.3 asset pack must exist at `<work root>/res/SMCY1.3`; set
`paths.assets` to its absolute path.

### 1. Create the storm folder and collect the inputs

Create `<work root>\single\<Storm>\sourcedata\` and put in it:

1. **Track segments** - `DB.txt` (disturbance), `TC.txt` (the cyclone itself),
   `RV.txt` (remnant vortex), `EX.txt` (extratropical). Write only the ones the
   storm has; the renderer finds them by name, so **the config does not have to
   list them**. One point per line, UTC, lon before lat:

   ```
   20260908180000    143.8    13.2    20    1005
   time            lonE     latN   wind_kt  pressure_hpa
   ```

   The timestamp is `YYYYMMDDHHmmSS`; `YYYY-MM-DD-HH-MM-SS` still parses. The
   interval is read from the data, so 3-hourly and 6-hourly both work - keep it
   uniform inside one storm. An empty placeholder file is ignored.
2. **`Num.txt`** - three positional lines:
   `90W` (invest) / `24W` (depression) / `20260916120000`
   (the UTC moment it was named, with a four-digit year). The JMA-number row
   is removed. Leave unknown fields blank; preserve blank lines so the fields
   do not shift. The naming timestamp is line 3 (Python index 2).
3. **`hypo.txt`** - `True` for a fictional storm, `False` for a real one. It
   overrides `storm.hypothetical`; it selects the default intro title only when
   no explicit `intro_title` or `title` is present.
   `storm.ef_rating: true` is a separate, storm-specific joke: while the system
   holds SSHWS C3 or above the badge reads `EF n` instead of `CATEGORY n` and the
   CMA grade reads 强龙卷风 in italic. Only Dujuan uses it, because of its 4 km
   pinhole eye - do not switch it on for a normal storm.
4. **`landfall.txt`** - one landfall per line:

   ```
   Chiba   20260921090000  140.12  35.60
   Izu Peninsula  2026-09-21-12-00-00  138.90  34.60
   ```

   **Longitude before latitude**, like the track files. The legacy
   `M.D HHz lat lon` layout still parses (see `storm-pipeline.md` §1.2). The name
   may contain spaces and is the key into the config's presentation block. The
   year is inferred from the series start, so a list may cross new year. Leave the
   file empty for a storm that made no landfall.
5. **`damage.txt`** - one place per line:

   ```
   140.12  35.60  Chiba  8  47000000
   lon     lat    name   dead+missing  loss
   140.47  37.75  福島県  38  0  | 東北 3 県
   ```

   `loss` is a plain number **in CNY yuan** and `/` means none; set
   `data.damage_loss_unit` to `wan` or `yi` if a file is written in those units
   instead. **Put the marker at the seat of government** of the entity the entry
   names - the national capital for a country, the provincial or prefectural
   capital for a province or prefecture - rather than at a hand-picked point near
   the track. The damage animation is triggered by the closest approach, so the
   coordinate decides the timing as well as the position.

   An optional `| group` tail collapses neighbouring places into one pop-up; `|`
   keeps it unambiguous when a name contains spaces.
6. **Himawari-8 infrared loop** (optional). If there is none, drop the `cloud:`
   block; the inset simply never appears.

Ask the user for anything you cannot verify. Never invent casualties or losses.

### 2. Work out the cloud-video time mapping  (only when a cloud loop is used)

The satellite loop is time-synced, so its frame → data-hour mapping must be
measured, not guessed:

```powershell
# burn-in timestamps of the first frames, every 200 frames
ffmpeg -v error -y -i cloud.mp4 -vf "select='eq(n\,0)+eq(n\,200)+eq(n\,400)',crop=300:20:2:2,scale=520:35,tile=1x3" -frames:v 1 stamps.png
```

Read the timestamps from that strip and derive `h0`, `step_h`, and any gap
(`segment1` / `segment2` / `resume_h`). See `storm-pipeline.md` §3 for the
exact procedure and a worked example.

### 3. Write the config

Copy `../examples/meranti_2016.yaml` into `<Storm>\build\` and edit. Every field is
documented in `storm-pipeline.md` §2. The parts that need real thought:

* `paths.storm` - the storm folder; everything else defaults from it.
* `data.series` - the txt file names **relative to `sourcedata`**.
* `storm.hypothetical` - marks a fictional storm (overridden by `hypo.txt`).
  Authored intro text is verbatim: set `storm.intro_title` and `storm.intro_line`
  to include the desired fictional label; the flag never edits configured copy.
* `data.peaks` - **list every local maximum in the intensity series**, not just
  the strongest one or two. Read the curve (or let a script find the local
  maxima) and give each an hour, position, label and `pano_dy`; a 3+ peak storm
  is laid out compactly on the end card automatically.
* `data.reanalysis` - if the official best track and the re-analysis disagree
  (single peak vs double peak, different pressures), the animation follows the
  re-analysis. Put the calibrated values here and mention the official figure in
  `summary.note`.
* `data.landfall_file` + `data.landfalls` - the file carries **time and position**,
  the config carries **presentation only**, keyed by the same short name. Every
  landfall counts, **including small islands**: Kinmen and Xiamen are ~10 px apart
  in the panorama and still need two separate tags, otherwise it looks like one
  fewer landfall. Give each a distinct `off_y` (follow-cam) and `simple_dy`
  (panorama) so labels never collide; `cat` is the SSHWS category at landfall.
  Without `landfall_file` you may inline `h`/`lon`/`lat` per entry instead.
* `data.damage` - one entry per place. `dead`+`lost` are shown in red,
  `loss` in CNY in yellow. **A place with 0 dead and 0 missing shows no red
  pop-up** - that is intended.
* `view.panorama_center` / `panorama_span_lon` - must be chosen so the whole
  track sits **below y = 235 px** in the panorama, otherwise the summary banner
  covers it. Rule of thumb: `lat_top = max_lat + 0.2315 * span_lat`.
* `data.intensity_curve` - leave it on `monotone`. A 3-hourly track joined with
  straight lines reads as a staircase; the shape-preserving cubic is smooth,
  passes through every fix and never overshoots. `data.plateau_ease` (on by
  default) additionally collapses every run of equal values to one knot at the
  run's midpoint, so a plateau eases through instead of drawing a flat tread.
  Wind and pressure are collapsed independently.
* `data.landfalls` needs **no** effect names: the impact clip, ground marker and
  sound are picked from the category at landfall, and anything above 155 kt uses
  the C6 super-cyclone set scaled by `1 + (wind-155)*3 %`. Pin `fx` / `landed`
  only to override. For a storm that lands many times set
  `view.landfall_tag_hold` so the name tags do not pile up.
* `data.rapid_intensification` - when two adjacent fixes jump two or more SSHWS
  bands the icon blends straight from the first band to the second (no
  intermediate levels), finishing in the first ~45 % of the interval
  (`data.ri_blend_frac`) so the jump reads as sudden. The ERI particle + sound
  are skipped for jumps landing in `data.ri_no_fx_bands` (default `C1`, `C5+`,
  `C5++`). On by default.
* `cloud.extract_every` / `cloud.crop` - the first keeps every Nth source frame
  (a 10-minute loop needs every frame), the second stores only a centre crop so a
  wide product does not fill the disk.
* `credits` - **name any third-party imagery**. Cropping a provider's watermark
  out is only acceptable when the credit is on screen instead.
* `view.panorama: auto` - fits the whole track below the summary banner. Use it
  whenever the track is tall (Hagibis spans 28 deg of latitude); frame it by hand
  with `panorama_center` / `panorama_span_lon` only when auto looks wrong.
* `data.damage[].group` - places that are close together and share a group are
  **summed into a single pop-up** (the event sits on the hardest-hit member).
  Merge first: playing a dozen neighbouring prefectures back to back swamps the
  frame no matter how well they are queued.
* `damage.min_gap` / `popup_duration` / `spread` (top level, **not** under `data`)
  - a compact disaster area fires all its numbers inside a couple of seconds.
  Check the `info` output: the whole queue must finish **while the affected area
  is still well placed in frame** - the follow-cam keeps moving, so a queue that
  runs too long ends with its last numbers pushed off the edge.
* `per-peak` `note` - a low-key line shown around that peak only (e.g. the
  official best-track figure when the animation follows a re-analysis).
* `banner.asset` - normally left unset: the banner art is chosen from the
  storm's **peak category** (`Summary-N-TC-C2.mp4` for a C2 storm, not C5).
* `banner.loss` / `banner.deaths` - the banner's second line is **derived** from
  the data (strongest peak, ACE, loss, deaths). Do not hand-write it: a hardcoded
  ACE is computed before the re-analysis is applied and silently goes stale.
* `summary.*` and `credits` are reserved data for a future end-card design.
  The separate statistics/credits page is removed (`SUMMARY = 0`); existing
  config values do not enable it. Pull-back, panorama cards and banner remain.

### 4. Verify the data model

```powershell
python <skill>\scripts\typhoon_anim.py --config <Storm>\build\storm.yaml info
```

Check the printed peaks, ACE, `w>170` window, landfalls and damage trigger
times against the source documents. Damage triggers must be **the moment the
centre is closest to that place** - the script computes it, just sanity-check it.

### 5. Extract assets, then look at test frames

```powershell
python <skill>\scripts\typhoon_anim.py --config <Storm>\build\storm.yaml assets
python <skill>\scripts\typhoon_anim.py --config <Storm>\build\storm.yaml test
```

`test` writes ~19 PNGs to `<Storm>\build\tmp\frame_*.png` covering the intro,
every intensity stage, each landfall, the cloud-gap and the panorama
card. **Open several of them and actually look** - text overflow, label
collisions and missing glyphs are only visible in the rendered frame.

### 6. Render and mux

```powershell
python <skill>\scripts\typhoon_anim.py --config <Storm>\build\storm.yaml all   # ~12 min
# or step by step: assets / render / audio / mux / poster
```

`mux` mixes the sound effects (no BGM) and writes the MP4 + poster into
`<Storm>\output\`.

### 7. Final check

* `ffprobe` the MP4: configured output dimensions (default 1920x1080), 120 fps, AAC audio and the adaptive total duration/frame count reported by the renderer.
* `ffmpeg -v error -i out.mp4 -f null -` must report nothing.
* Re-open frames of the render (peak, landfall, panorama).
* Archive superseded cuts into `<Storm>\旧版（无用）\` instead of deleting them,
  and leave the previous cut in `output\` until the user accepts the new one.
* Clean the regenerable intermediates (`cloud`, `tmp`, `video_silent.mp4`,
  `audio.wav`) once a render is accepted. The shared `res\_cache\` is **not**
  cleaned - it is the point of the design, and it is reused by every storm.

## Two source layouts

`data.series` accepts either arrangement; `skip_first` / `skip_last` are counts:

| layout | example | series |
|---|---|---|
| mutually exclusive segments | Meranti | each file holds only its own stretch, nothing skipped |
| master table + subset views | Hagibis | the best-track file also contains the disturbance and remnant segments, so carve them out with `skip_first: 2, skip_last: 2` |

Either way the four segments must join into one continuous 6-hourly series -
the `info` point count is the check.

## Hard rules (learned the hard way)

1. **The base map is Pacific-centred.** `x = lonE/360*10800`, not `-180..180`.
2. **ASCII only** in every on-screen string except Chinese. No `° × ⁴ ² · → ≈ ¥`.
   Use `CNY`, `x10^4 kt2`, `20.4N`. CJK text must go through `mixed()` /
   `mixed_base()` so the Chinese and Latin fonts sit on one baseline.
3. **Camera motion must stay sub-pixel** (`warpAffine` fractional shift) and be
   smoothed over ~1.7 s, otherwise the follow-cam visibly shakes.
4. **Cloud inset**: crop away the burned-in watermark, feather the edges and
   screen-blend it, so no square border is visible. Fade it out over gaps in the
   satellite data.
5. **Landfall markers** use the `Landed-xx.mp4` animation, played so one full
   spin takes 3 s; they fade out when the camera pulls back.
6. **ACE bar** is revealed left-to-right; the colour ruler is never stretched.
7. **No BGM.** Only the specified sound effects.
8. **Smooth the curve, do not flatten it.** Values are interpolated with a
   shape-preserving cubic, and the ACE bar ramps continuously between synoptic
   fixes. Both changes only affect the *shape between* data points - every
   plotted figure still comes straight from the fixes.
9. **Plateaus ease, they do not flatten.** A repeated value on consecutive fixes
   is one knot at the middle of the run, not a flat tread with two corners.
   Handle wind and pressure separately - they rarely plateau together.
10. **Never hard-code a timeline.** Phase boundaries, the day ticks on the
   timeline (midnight UTC), the peak windows and the note windows are all derived
   from the data. A hard-coded hour looks right for the storm it was written for
   and silently mislabels every other one.
11. **Landfall sound follows the category.** The clip is picked from the category
   at landfall and the gain falls off with it, so a C5 strike does not bury a C1.
12. **Date fragments are data.** Years, months and day ticks come from `S.t0`.
    A hard-coded `SEP` or `2016-` is correct for one storm and wrong on screen
    for every other.
13. **Translate the name the way the audience spells it.** A storm has different
    conventional names per region (mainland Chinese, Taiwanese, Japanese); ask
    which one the video should use rather than copying the one in the source file.
14. **Watch the end of the main phase.** A damage point far from the track can
    have its closest approach on the very last frame, so its number appears as
    the camera pulls back. Check the trigger times in `info` and move the anchor
    if the tail lands past `T_MAIN`.
15. **Changing a track's speed means retiming it.** Compress the timestamps
    (`tau = integral of 1/speed`), never drop fixes - dropping points leaves the
    speed alone and only coarsens the sampling. Then remap landfalls, peak hours
    and `ace_end_h` together, and check that the log's `info` still shows the
    peak values you expect.
16. **Upgrade effects sit on the right threshold.** `note_ts` marks every TD -> TS
    crossing (34 kt), not TS -> C1 - a storm that weakens below TS and
    re-intensifies gets another flash. Crossings inside the extratropical phase
    do not count (`data.ts_fx_skip_phases`): a gale recovering after transition
    is not a tropical storm upgrade. Rapid-intensification bursts are reserved
    for the mid-range jumps; C1, C5+ and C5++ targets blend silently.
17. **The graph has two axes.** Pressure on the left, wind on the right; the
    category gridline values belong to the wind axis. And the panorama banner
    art follows the peak category - a C2 storm must not wear the C5 banner.
18. **Every mixed-script line uses `mixed()`.** The intro footer, the **HUD credit
    line** (it names agencies - `民政部`, `消防庁`, `应急管理部`), the banner and
    the summary header can all carry Chinese; drawn with the Latin font alone it
    becomes a row of tofu boxes, which read as text at a glance and slip through
    review. Centre with `mixed_w()`, do not rely on `anchor='mm'`.
19. **Check a mapped cloud loop against the track.** If the imagery carries
    coastlines, the storm's position relative to land at a known timestamp
    verifies the frame-to-data-hour mapping independently - project the track and
    see whether the eye lands where the data says. Trust that over a hand-built
    timing report.
20. **Do not hand-tune label offsets against a projection.** `pano_dx` /
    `pano_dy` are preferences; the renderer displaces a tag that would collide
    with another tag *or with the track*. Likewise the end card splits its peak
    list into two columns past five entries. Ten maxima must still fit.
21. **Inspect the panorama last.** Check card text and projected labels for
    clipping and collisions. The separate dimmed statistics page is removed;
    no summary-page test frames should be scheduled while `SUMMARY = 0`.
22. **Record where the track came from, and whether it is final.** A track pulled
    from a live feed (IBTrACS `ACTIVE`, JTWC tcvitals, agency bulletins) is
    **provisional**: it may be truncated because the storm is still running, it
    carries no post-analysis, and its intensities are often non-multiples of 5 kt
    where a real best track uses 5-kt steps. Write the source, the snapshot time
    and the word PROVISIONAL into `sourcedata\说明.md`, and say so to the user
    before rendering. Never present live-feed data as a best track.
23. **A track file carries data and nothing else.** Comment lines (`#`) are
    tolerated by the parser but the convention is data-only: provenance belongs in
    `说明.md`, not in the file the renderer reads. Keep segment files uniform
    inside a storm (all 6-hourly or all 3-hourly) - the interval is read from the
    data.
24. **ACE must come from the data, never from the drawn curve.** The intensity
    graph is smoothed (`collapse_plateaus` + monotone cubic) for readability; that
    smoothing moves values at intermediate times, so sampling the *drawn* curve
    would let a cosmetic choice perturb a scientific statistic. ACE samples the
    raw fixes on the 00/06/12/18Z grid. If the on-screen ACE ever disagrees with a
    direct sum from the source file, the renderer is wrong, not the data.
25. **Intro copy is explicit.** Prefer `CYCLONE <NAME>` / 热带气旋 for real storms
    and `hypoTC <NAME>` / 假想热带气旋 for fictional ones in authored configs.
    `intro_title` overrides `title` for the opening only; `intro_line` is verbatim.
    The renderer never replaces words or adds fictional qualifiers to either line.
26. **Rapid intensification is a window test on the smoothed curve, not a
    band-count test.** A burst that gains one SSHWS band at a time is still rapid
    intensification. Flag every 6 h window gaining >= 20 kt, and every 24 h window
    gaining >= 60 kt with no 6 h sub-window under 10 kt; merge contiguous windows
    into one event and centre the burst on the event's midpoint. The old
    "two bands inside one fix gap" rule misses the common case.
27. **Map intensity to the CMA scale by reading the agency chart, not by unit
    conversion.** `kt * 0.514444` is the physical conversion; `机构对照.jpg` is an
    inter-agency calibration and differs by a whole grade at the top end (104 kt:
    chart 48 m/s / 强台风, conversion 53.5 m/s / 超强台风). Anchors and the
    piecewise-eased fit live in `SMCY1.3/intensity/mapping.json`.
28. **Damage popups are centred on the closest approach**, so the flight is
    half-done at that moment - set the start to `t_closest - POPUP_DUR/2`.
29. **Map labels are transient, map markers are permanent.** Peak and landfall
    text fades ~2 s after it appears; the dot stays on the track for the rest of
    the run. The landfall marker keeps spinning (loop the clip, drop its
    shrink-away tail) at 30 % of its library size; the peak marker is a
    white-ringed dot filled in that peak's own theme colour.
30. **The ending is a pull-back, not a cut.** Do not cache a separate panorama
    frame with its own annotations - the swap shows. Keep one camera path and draw
    the same overlays across the transition. The panorama carries no text
    annotations at all: landing and peak facts move into cards that ride in with
    the summary banner (landings from the right, peaks from the left), one card
    per fact, themed by intensity, a column every 4 s.
31. **Never format a NaN.** A track fix may carry a wind but no pressure
    ("N/A"); interpolate it when building the intensity grid, and guard the HUD
    text anyway, or `'%d' % round(nan)` kills the render an hour in.
32. **The CMA card is a separate card, not a second line of the badge.** Under
    `CATEGORY n` sits an identically styled card reading the extended Beaufort
    force and the Chinese grade (`12 级  台风`). The m/s value is never printed.
    An extratropical system reads `温带气旋` in the disturbance grey, because the
    tropical scale does not describe it.
33. **Name the cyclone beside its icon.** INVEST number while it is a
    disturbance, the depression number once it is an unnamed tropical cyclone,
    the English name once named. All three come from `Num.txt` - never guess them
    from the file names.
34. **Nothing appears; everything enters.** Panels, cards and the banner slide
    and fade in at the start of the track animation and again in the panorama.
    An abrupt appearance reads as a rendering fault.
35. **A name is a translation, not a transliteration.** The intro, the badge
    label and the end card all use the audience's conventional name; ask which
    one when the source files disagree with each other.
36. **Match the upgrade animation's arm angle to the icon.** The TS-upgrade
    effect is a two-armed spiral like the cyclone icons; playing it at a fixed
    angle leaves the arms visibly out of step with the icon underneath.
37. **The ACE bar carries integer ticks.** A revealed bar with no scale is
    decoration; the integer marks make it a measurement. The colour ruler itself
    is never stretched.
38. **A rapid-intensification window never moves the icon's level.** It marks a
    period and centres the ERI burst on that period's midpoint; the icon and the
    badge keep following the wind. Blending the icon to the window's *target*
    level looks right for a 6 h jump and is badly wrong for the 24 h windows the
    new test finds - at one point Nesat read `CATEGORY 5++` while the wind was
    165 kt, four knots short of the band.
39. **Scale the burst, never the marker.** A super-cyclone landfall scales the
    impact clip by `1 + (wind-155)*5 %`; the `Landed-Cx` marker that stays on the
    path is always 30 % of its library size, whatever the intensity was.
39. **The icon fade is linear in intensity, not in time.** Around a band
    boundary  the incoming icon goes from transparent at  - icon_fade_kt
    to opaque at  + icon_fade_kt (3 kt), so the C5 boundary at 137 kt blends
    from 134 to 140. One function of the wind covers both directions - falling
    through the same numbers plays the fade in reverse - and a storm parked on a
    boundary shows the blend, which is the useful part.
40. **The halo is graded, and the lower bands get none.** The library art
    already has a soft glow; running it through the hue replace brightens it
    (C1 +197 %, C5 +81 % of the ring) and the icon looks like it gained a halo.
    Only C5++ is tinted, with an additive halo that starts weak at 170 kt and
    grows to 184 kt, and that halo is masked off the bright core so the numeral
    survives.
41. **One icon layer, never a stack.** Blend the outgoing and incoming sprites
    into a single image before compositing. Compositing two layers separately
    with screen blending ADDS them, so the icon brightens mid-fade and jumps
    when the outgoing one is dropped.
42. **Judge a rapid-intensification burst by where the event STARTS, not where
    it ends.** The window test finds long climbs (Dianmu's first peak is a 31 h
    TD -> C5+ run), so keying the burst on the ending band mutes exactly the
    events worth showing - Dianmu's first peak played no ERI at all. Only a hop
    that begins in the top bands is old news.
43. **A landing keeps its square in the panorama too.** The spinning
    `Landed-Cx` marker is the landing's identity on the path; swapping it for a
    plain dot once the camera pulls back loses that, and the viewer has just
    watched the square spin for the whole track.
44. **Play a library clip at its authored rate.** The summary banner is 60 fps;
    extracting it with `setpts=N/20/TB` played it at a third speed and it read
    as slow motion. Check `r_frame_rate` before forcing a frame rate.
45. **A card column enters and leaves through the SAME edge.** Peaks live on the
    left and travel left; landfalls live on the right and travel right. It is
    tempting to reverse the sign for the exit, which sends every card out the
    wrong side. The first column must ride in as well - hard-coding its alpha to
    1 to skip the intro removes the entrance animation entirely.
46. **Do not let the two card columns retire independently.** When one side has
    more columns than the other, the sparse side holds its last column and the
    banner stays until the busiest side finishes, then everything retracts
    together.
47. **A held column is not an outgoing column.** While a side waits out the
    busier one, its outgoing and incoming column are the SAME, so the exit
    animation must be skipped - otherwise the waiting cards replay the slide-out
    every cycle. Only a real column change animates.
48. **The final retraction is a slide-out, not a fade in place.** Everything
    leaves with the motion the carousel has been using, so the last thing the
    viewer sees matches what came before. Do not stack a separate end-of-scene
    fade on top of the exit - that reads as two animations fighting.
49. **Past 185 kt the card TYPE goes white.** The theme colour there is deep
    blue heading for black, so coloured type on the dark card is unreadable. The
    colour bar keeps the theme colour, so the intensity is still encoded.
50. **A phase change fades in LINEARLY IN TIME; a band change ramps LINEARLY IN
    WIND.** They are different quantities and must not share one code path. A low
    pressure becoming a remnant vortex or an extratropical system fades the
    incoming art in evenly across TRANS_H hours either side of the boundary; a
    band change ramps the incoming art across icon_fade_kt either side of the
    band edge.
51. **Test a phase change on the phase NAMES, never on how many levels are
    active.** An ordinary band boundary inside the tropical cyclone (TD/TS at
    34 kt) also returns two levels. Treating that as a phase change drew TD and
    TS on top of each other around 30 kt AND bypassed the wind-linear band ramp,
    which is what made the icon switch feel jerky and steppy.
52. **Align the upgrade effect by ARITHMETIC, never by reading the image.** Both
    the TC icon art and the upgrade effect are authored starting at 0 degrees,
    and the icon art turns exactly **6 whole times** over its 1800-frame loop. The
    renderer keeps every third frame (N_ICON = 600) and plays it at 20 fps, so
    one loop is 30 s, the icon turns 5 s per revolution, and the angle is
    3.6 deg * (nf % 600). Rotating the effect by the icon's angle at the
    trigger aligns the arms. Measuring the angle with an image-analysis helper
    instead produced a mismatch the client could see immediately - and it is
    guesswork where two numbers and a constant are enough.
53. **Latch the alignment angle at the trigger frame.** The icon keeps spinning;
    recomputing the offset every frame drags the effect around with it and flips
    sign at the 0/360 wrap, which reads as a direction jerk.
54. **Blend at most two states, always.** A phase boundary can leave three
    levels partly active; take the top two by weight and blend those into one
    sprite. Compositing all three - or compositing layers separately instead of
    blending into one image - is what produced the ghosting and the jumps.
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

## 1080p120 output and missing identities

Single video defaults to 1920x1080 at 120 fps, H.264 CRF 16. Set
`output.width` and `output.height` to positive even integers to select an export
size; 2560x1440 is the current 2K120 export option. Composition stays 1920x1080
and other export sizes use Lanczos scaling during encoding, not a native redraw.
Every video frame is evaluated at 120 fps.
Overview PNG output remains at the map's native pixel density.

In Num.txt, blank, `-`, `n/a`, `none`, and `null` mean absent. Start with the
invest number if present; at the TC stage prefer the depression number if
present; at the naming timestamp prefer the English name. Missing later
identities retain the most recent available earlier one, including into the
remnant/extratropical stage. All missing means no icon-adjacent identity text.
No number or naming timestamp is invented from the project title.

Optional geography is bundled at parent skill `assets/geo/`, separate from the project workspace. Normal rendering does not require it.
