# Season workflow

The rule book for the season folder's three scripts. Read this before changing any
of them. Rules here win over local improvements in the code.

---

## 1. The six stages

A season is not one program. It is six stages, and three of them live in this
folder.

| # | stage | what it is | where |
|---|---|---|---|
| 1 | **data** | one folder per storm plus a season index, filled and tidied by hand | the season folder's `sourcedata/` |
| 2 | **overview** | the stills: one whole-season sheet and one per storm | `season_overview.py` |
| 3 | **season notes** | the quirks of THIS season, in prose | `<year>.md` in `examples/` |
| 4 | **plate** | the season as one video: tracks, icons, effects, no numbers | `season_pass1.py` |
| 5 | **edit** | camera moves, cuts, effects over the plate. **Must not change the duration** | outside this folder, by hand |
| 6 | **cards** | the data cards and the timeline, composited over the edited plate | `season_pass2.py` |

Stage 5 must not change the duration because stage 6 lays its timeline on the
finished cut and reads nothing but the frame index. Stage 4 is therefore framed
with room for stage 6 - see rule 4.

Stages 2, 4 and 6 are mutually independent: each reads `sourcedata/` (and, for
stage 4, the asset pack) directly, and none imports another. That is why stage 6
can also run against `--base black` and produce the data layer on its own.

## 2. Stage 1: the data

`sourcedata/` holds one directory per storm plus `INDEX.txt`. Per storm:

| file | columns | meaning |
|---|---|---|
| `Num.txt` | 3 lines | invest number, JTWC number, JMA naming stamp (`-` if unnamed) |
| `TC.txt` | 5 | best track: time, lon, lat, wind kt, pressure hPa |
| `DB.txt` | 5 | disturbance phase, same shape |
| `RV.txt` | 5 | remnant-vortex phase |
| `EX.txt` | 5 | extratropical phase |
| `hypo.txt` | 1 | `True`/`False`, a hypothetical storm |
| `landfall.txt` | 4 | place (may contain spaces), 14-digit time, lon, lat |
| `damage.txt` | 5 | lon, lat, place, dead+missing, loss in 万 CNY |

Use `YYYYMMDDHHmmSS` (14 digits, explicit four-digit year) or the long
`YYYY-MM-DD-HH-MM-SS`. Season scripts additionally accept legacy 12-digit
`YYMMDDHHmmSS` inputs for existing season datasets only (pivot at 50). New
data must use four-digit years; single-storm input rejects two-digit years.

**The naming stamp is found by its SHAPE, not its line number.** The JMA number
that used to sit third was only ever a placeholder and has been dropped, so a
file is three lines today and was four before. Older files must keep loading, so
`_build()` scans for the first 14-digit (or legacy 12-digit) or long-form token and takes that as the
naming time. Never hard-code an index into `Num.txt`.

Phases are merged in the order `DB -> TC -> RV -> EX`, and each `Series` carries
its own `phase` array. Phase boundaries are **derived** - the midpoint between
the last fix of one phase and the first of the next - so never hard-code an hour
for them.

An empty placeholder file (a `DB.txt` created ahead of the data, an `EX.txt` for
a storm that never transitioned) is skipped rather than contributing a zero
point.

## 3. Stage 2: the stills

Two products, both 1920x1080 by default and both cut from the SAME map:

* `overview.png` - the whole season, every track laid on in **genesis order**, so
  the later a storm starts the higher its layer sits.
* `NNW.png` - one per storm, named from its JTWC number.

There is no peak marker, no name call-out and no title banner. The map and the
tracks are the whole picture. The label is off unless `--labels` is given.

The basin is decided ONCE, from every storm at once, and reused for every still.
Deciding it per storm is wrong: a storm near a basin edge then lands on a
different sheet from its neighbours, which is how one season produced 25 sheets
that matched and one that did not.

## 4. The map and the framing rule

This is the part people get wrong, so it is written out in full.

**The map is `map/basins/` and nothing else.** `map/basins.json` carries each
sheet's geographic window and its size. The sheets arrive already composited -
graticule, region lines and labels are baked in - so there is no overlay to blend
and no dim step to apply. Everything else under `SMCY1.3/map/` (`sources/`,
`[GLOBAL]*`, `basins/EARTH.png` when it is only a copy) is superseded.

### Picking the sheet

Score every sheet by

    covered area / map area

where the covered area is the intersection of the sheet's own window with the
track grown by the padding, and the map area is the sheet's whole window. Take
the largest. This lets the basin that actually owns the track win, while a basin
that merely swallows the track inside a huge window loses.

`map/basins/EARTH.png` - the whole world - must be registered in `basins.json`
like any other sheet and is the fallback when nothing scores above zero.

### Padding

Grow the track's bounding box by **5 degrees** on the west, east and north, and
**10 degrees** to the south. The south margin is larger because stage 6 lays its
timeline there; it is measured **from the track**, not from the sheet.

### The window

    window = union(sheet's own window, padded track bounding box)

The sheet stays the authority and the padding is the patch that reaches any part
of the track that spills outside it.

### Filling the frame

A whole-basin window is about 1.25 : 1 in degrees, so it can never fit a 16:9
frame without either stretching the map or repeating its edge. Grow the window
**about its own centre** - never crop it - until its degree aspect matches the
frame, then cut that window out. The extra band is real map because the sheet is
a sub-window of a world map; see `season_pass1._load_basin_img`, which always
samples the whole-world sheet for exactly this reason while reporting the basin
the rule picked.

Never resize a window into a frame of a different aspect. That is a stretched
map, and the renderer has no code path that does it any more.

### Where the default comes from

`--crop` defaults to `auto`, which is this rule. `world` and `wpac` still exist in
`WIN_PRESET` as explicit overrides, and a `lon0,lon1,lat0,lat1` literal is
accepted. For the 2020 season `auto` reproduces the hand-written `wpac` window
exactly, which is the check that the rule is right.

## 5. The time warp

One season is compressed onto the screen, so the clock cannot be linear.

| constant | value | meaning |
|---|---|---|
| `SE_ACT` | 0.5 | days per second while a cyclone is active |
| `SE_QUIET` | 15.0 | days per second when the basin is quiet |
| `SE_PAD` | 1.0 | days of padding added to each side of an active block |
| `SE_EASE` | 1.0 | days over which the rate eases quadratically at each join |
| `SE_MERGE_D` | 1.0 | blocks closer than this many days merge into one |

Activity blocks are built from the storms' lifetimes, padded, then merged. The
ease is quadratic, `u²` on the way in and the mirror on the way out. The result
is a date <-> screen-second map built once (`SeasonTime`).

Consequence to keep in mind: the first months of a WPac season have no storms at
all, so at 15 days/s they pass in a couple of seconds. That is intended.

Note the log line uses `%.2f` for the active rate. `%.0f` rounds 0.5 to 0 and
reads as if nothing were happening.

## 6. Drawing order

A frame is composed in **three layers, bottom to top**:

1. every storm's **trail** into one shared overlay
2. every storm's **halo** into a second shared overlay
3. the icons, the four motion effects and the labels, straight onto the frame

The split is not cosmetic. Drawn storm-by-storm the halos buried the paths - and
being translucent, buried each other too. All trails must be down before any
halo.

## 7. Sizes: two kinds, and only two

Every size in the season renderer is a ratio. There are no pixel counts.

**Geography rides the icon.** The icon is a fixed size on the map, so at a finer
render it is a smaller share of the frame and its effects shrink with it. Halo,
ERI burst, TD->TS upgrade, landfall impact, `Landed` marker and the map label are
all `K x ICON`. The ratios come from the single-storm renderer, which is the
reference for the look.

**Screen furniture does not exist yet** - but when the timeline and cards are
added, remember they are frame-relative, not geography-relative.

Rule for anyone adding a size: decide which of the two it is, then express it as
a ratio. A bare pixel number is a bug.

### The one trap that has already bitten twice

`SeasonR` sets `ICON = ICON_PX * SC`. The shared drawing helpers
(`trail`, `glow`) **also** multiply by `SC` themselves. So a multiplier passed to
them must be `K * ICON / base` with **no second `SC`** - otherwise the size grows
as `SC²` and the path gets 4x fatter every time the render doubles. The fix
marker never had the extra `SC`, which is why it looked right while the path did
not.

## 8. Per-frame budget

The renderer is CPU-bound and roughly linear in pixels. Measured on this machine
(12 logical cores), from a real render at the densest part of the season:

| size | px/deg | frame | fps | 34661 frames |
|---|---|---|---|---|
| 960x540 | 6.75 | - | ~12 | 0.8 h |
| 3840x2160 | 27.0 | 0.287 s | 3.9 | 2.8 h |
| 4800x2700 | 33.8 | 0.358 s | 3.1 | 3.4 h |
| 5760x3240 | 40.5 | 0.651 s | 1.5 | 6.3 h |
| 8534x4800 | 60.0 | ~0.8 s | 1.2 | ~8 h |

8534x4800 is the height at which the frame is exactly the world sheet's own grid
(60 px/deg), i.e. no map resampling at all.

`--limit N` renders only N frames and is the cheap way to time a candidate size
before committing. `--audio 0` skips the sound stage.

## 9. Stage 3: the season notes

Quirks that belong to ONE season go in `examples/<year>.md` - prose, not a
config. They are things like: a storm whose track crosses the dateline, a
depression that never got a number, a landfall the source data records twice, a
storm the operator wants held on screen longer.

There is no YAML and no schema. If a note turns into something the renderer must
always do, it belongs in this rule book or in the style spec instead.

## 10. Sound

`season_audio()` lays the same inventory the single storm uses onto the season's
own time base: the TD->TS upgrade notes, the ERI cue, the 170 kt and category-4
noise beds, and a per-category landfall hit. There is **no BGM**.

One bus carries the whole season, so the mix is peak-normalised rather than
clipped. That is deliberate but it has a cost: with 26 storms the summed peak
runs well past 1.0, so every cue is scaled down by the same factor and a single
landfall sounds quieter than it would alone.

**The cues are scheduled against the whole season, not against `--from/--to`.**
A short test window therefore plays the whole season's cues packed into those
few seconds. Render the full season if you want to judge the sound.

Landfall sounds live in `SMCY1.3/landfall/` and are read as
`landfall/sound.landfall.<LEVEL>.ogg`. If that directory holds shortcuts rather
than the `.ogg` files, the sound stage fails after the whole video has been
rendered - check it first.

## 11. Things that are deliberately absent

Do not add these to `season_pass1.py`:

* a timeline, or any date/scale bar
* data cards, ACE curves, damage or death read-outs
* a HUD, a title, an intro or a summary banner
* damage pop-ups
* a camera move - the season camera is fixed by design

All of that is stage 6, and it goes over the finished cut, not into the plate.
Stage 6 is `season_pass2.py`; what it draws, and the rules its numbers follow, are
in `season-cards.md`.

## 12. The card layer's own rules

Three of them are worth knowing before reading `season-cards.md`, because they are
the same rules as pass 1's, restated for screen furniture:

* **Everything is author units at 1920x1080**, times `sc`. Screen furniture rides
  the FRAME, unlike geography, which rides the icon - so card sizes are ratios of
  the card, never of `ICON`.
* **Numbers are contracts.** The tally's five criteria, the ACE definitions and the
  significant-figure rules are not display choices to tune; they were each
  specified and each cost a round to get right. `season-cards.md` §4-5.
* **The card layer never re-times its base.** It reads the frame index. Anything
  that made it depend on the base's content or duration would break stage 5.
* **The summary banner belongs to stage 6**, not to the plate. It is the one
  thing on this layer that announces a single system rather than the season, it
  is the only use of the `summary/` art outside the single renderer, and its own
  rules - stacking, the 3 s hold, the separated axes of motion - are in
  `season-cards.md` section 6b.
