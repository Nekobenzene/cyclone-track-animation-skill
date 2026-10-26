# Season stage 6 — the data cards

The contract for `scripts/season_pass2.py`. Read with `season-workflow.md` (the
rules) and `season-style-spec.md` (the frozen look); this file is what pass 2 is.

Pass 2 draws the season's numbers and composites them over a base **it did not
draw**. It reads the frame index and nothing else, so the base's timing is never
touched — that is the whole reason it can run after stage 5 has cut the plate
about.

---

## 1. Command line

    python season_pass2.py info
    python season_pass2.py preview  --base black --size 1920x1080 --at 2020-11-01
    python season_pass2.py render   --base black --size 960x540 --fps 30 --out x.mp4
    python season_pass2.py render   --base <edited plate>.mp4 --size 8534x4800 --fps 120

| flag | meaning |
|---|---|
| `--base` | `black`, `map`, or a video file. `black` is the standalone data layer |
| `--season` / `--assets` | the two roots; both default to the usual desktop paths |
| `--size` / `--fps` | the OUTPUT. The overlay is drawn on its own canvas, below |
| `--at` | one frame, by date (`2020-10-31T06`) — the `preview` command |
| `--from` / `--to` / `--limit` | the render window |
| `--render-w` | override the overlay canvas width (default `min(3840, max(1920, W))`) |

`info` prints the axes a run will use — the rate axis, the ACE axis, the ruler's
own scale, the damage axes, the tally axis, the block count and **how many summary
banners there are and how deep the stack ever gets** — without drawing anything.
Read it before a long render.

## 2. Two canvases, and which one "high resolution" means

The output is one width; the canvas the overlay is DRAWN on is another, and it is
capped:

    render_w = int(render_w) if given else min(3840, max(1920, W))

So an 8534-wide output has its data layer drawn at 3840 and then upscaled 2.22x.
Cropping the 8534 master at 1:1 therefore shows a 3840 drawing; no amount of
cropping sharpens it. Rendering the layer natively at 8534 was compared and is not
visibly better (see `season-style-spec.md` §11), and native 16K costs 1033 ms a
frame, so **the cap stays**.

The overlay's own geometry is author units at 1920x1080 scaled by
`sc = render_w / 1920`. `sc` is 1.0 at a 1920 canvas and 2.0 at the 3840 default,
and **a lot of bugs only exist when `sc != 1`** — see §8.

## 3. The cards

Left column, top to bottom, 480 wide at x=10, in author units:

| card | box | contents |
|---|---|---|
| identity | `(10, 10, 480, 80)` | `WPAC <year>`, then the UTC date and clock |
| damage | `(10, 96, 480, 94)` | deaths and direct loss, each a label + a well |
| ACE | `(10, 196, 480, 264)` | rate curve, cumulative curve, ACE ruler, caption |
| tally | `(10, 466, 480, 146)` | five rulers stacked, one per category |
| timeline | `(60, 930, 1800, 140)` | baseline, month ticks, heat-coloured pointer |

The column is DERIVED: `BOX_DAMAGE` starts `_COL_GAP` below `BOX_IDENTITY`, and so
on down. It used to be four hand-written `y` values, and shortening one card
opened a hole between the other two.

The ACE card and the tally share one left inset, `0.021 x card width`, so the two
rulers start on the same vertical line.

### Panels, wells and the white frames

Everything static — panels, black wells, grid, axes, month names, the labels that
do not carry a value — is rasterised once into `self._static` and blitted.

**The bars' white frames are NOT in that bake.** They go into `self._frame_rects`
and are drawn at the very end of `frame()`, after every fill. `ImageDraw` draws a
rectangle's outline INSIDE its box, so a frame baked under its own bar is painted
over along the edge the fill starts from. Drawing them last also means no later
block can be added that covers one by accident.

## 4. The four numbers, and how they are formatted

| read-out | model | format |
|---|---|---|
| deaths | cumulative; each storm booked at end + 6 h | exact integer + `人`; from 10 000 up, `万人` at three significant figures |
| loss | same booking | three significant figures; `亿元` at ≥ 1.0, `万元` below |
| ACE | cumulative, summed at the strict 00/06/12/18Z points | `%.1f`, on the right-hand axis |
| ACE rate | **real time**: `4/1e4 x SUM over the systems on the field of v^2`, v >= 34 kt | `%.2f`, on the left-hand axis |

**Three significant figures are a BIG-NUMBER rule, not a precision.** For the loss
the operator asked for them outright. For deaths they apply only once the count
reaches 万人: below that the exact integer is both shorter and true, so
`1234 -> "1234人"` and `12345 -> "1.23万人"`. `_round_sig` and `_sig` implement it;
`%.3g` cannot be used because it switches to `1.23e+04` inside a Chinese label.

The unit split is decided on the ROUNDED value, not the raw one, so the two
branches join up: at three figures `0.9999亿元` is `10000万元`, which would print
as `"损失：10000万元"` — the wrong unit and a wider string than `1.00亿元`.

## 5. The tally: five independent criteria

Five rulers stacked flush, one per category, sharing their edges. Each category is
its own test, on its own scale:

| ruler | test | colour | source of the colour |
|---|---|---|---|
| C5 | peak reaches 137 kt | `(252, 20, 252)` | `mainicon/tc_sshws/N-TC-C5.mp4` |
| MH | peak reaches 96 kt | `(252, 128, 0)` | `N-TC-C3.mp4` |
| HU | peak reaches 64 kt | `(252, 252, 52)` | `N-TC-C1.mp4` |
| TS | **named** (JMA) | `(8, 252, 0)` | `N-TC-TS.mp4` |
| TD | **numbered** (JTWC) | `(64, 100, 200)` | `N-TD-D.mp4` |

96 and 64 are the Saffir-Simpson 3 and 1 boundaries; 137 is the 5 boundary.

* **Cumulative, not exclusive.** The number beside MH is every system that has
  reached MH, not only those whose current category is MH. Normally
  `C5 <= MH <= HU <= TS <= TD`; the counts read 2/6/9/15/18 for a season of
  2/4/3/6/3.
* **Peak reached SO FAR.** A system joins a ruler when it actually gets there, not
  retroactively once it is over — and it never leaves, which needs no extra code
  because a running maximum never falls. A category-3 typhoon that weakens to a
  tropical storm stays counted in MH, and in HU, TS and TD below it.
* **TD and TS are agency decisions; the other three are wind speeds.** JTWC numbers
  and JMA names independently, so a system can be named before it is numbered or
  reach hurricane force without ever being named. When that happens a LOWER ruler
  can be shorter than a higher one, and it is not a bug. 2020 has no such case.
* **TD is taken as the first fix.** `Num.txt` carries no numbering timestamp — an
  invest id, the `xxW` number, naming time and a reserved JMA number — and every folder in
  a season has a number, so a system is numbered for its whole tracked life. This
  is the line to revisit if a season ever carries an unnumbered system.
* **A count ramps in over `P2_EASE_S` = 1.5 SCREEN seconds** from the moment the
  criterion is met, and the printed digit flips at the midpoint of its own ramp.

Colours are **read off the icon videos**, not chosen: the dominant disc colour
across the whole clip (28 frames, pixels with chroma > 110, mode of the
4-quantised histogram). The `Cx-.mp4` / `Cx+.mp4` / `C6(n).mp4` variants are NOT
used — only the plain `Cx.mp4`. Note the videos differ from the flat PNGs in
`gui/simpleicon/` (their C3 is `#FF6000`, the video's is `#FC8000`), and the
videos are what appear on the map.

TD is the one read with a caveat: the icon is dark, only 35k of its pixels clear
the chroma gate and its value is 0.78 against the others' 0.99. It is still the
clear mode by 8x, and on the panel it reads as blue rather than as a shade of the
panel, which pure grey did not.

### The stack geometry

One ruler's own width:height is the DAMAGE well's, `260:16` — thickness follows
from the width, it is not chosen. The bars are flush, and neighbours overlap by
exactly one stroke so the shared edge is a SINGLE line.

    pitch = height - (stroke - 1)      in LAYER pixels, stroke = max(1, int(sc))

That `- 1` is not decoration. `ImageDraw.rectangle` with `width=w` draws inside the
box and, at `w = 1`, on the box's first and last rows; neighbours offset by `h - 1`
therefore land on ADJACENT rows and the shared edge comes out twice the outer
edge. The card is sized for the widest case, `stroke = 1`, i.e. `pitch == height`.

Both `h` and the pitch are computed in `build_static` from the live `sc`, and each
bar's bottom is derived from the PITCH rather than from the height, so the two
edges are the same expression and cannot differ by a float ulp.

## 6. The ACE card

Two scales on one plot: the rate on the left axis, the cumulative ACE on the right
axis (drawn as a pale step curve, with an end-cap so the two curves are told apart
by where they END rather than by colour). The cursor is a heat-coloured dot on the
rate curve plus a white dot on the cumulative line, and one number drives both.

The ruler under the plot is the client's `gui/ace/ace_color_1000.png`, drawn twice:
a 25%-alpha wash of the true value, and the solid booked value on top. Ticks are
cut INTO the bar every 10 units of the ruler's own scale (`ace_full`), every 50 at
half depth, and light up as the bar passes them. The bar's scale is **not** the
plot's right axis: `ace_axis` is the cumulative ACE rounded up to a sensible
label, `ace_full` is that rounded up to a multiple of 50, so the ruler keeps
headroom and does not fill completely at the season's end.

### The rate curve: sampled on the data's grid, then decimated

Two decisions, both made by measurement, and getting either wrong is visible.

**Sample on the grid `rate` lives on — one point per HOUR — not once per pixel
column.** `rate` is piecewise linear between hourly knots, so hourly samples
reproduce it exactly. Sampling once per column means one sample per 12.1 hours of
season at the 8K layer, and a spike about half a day wide and eleven rate units
tall is then drawn as a single linear step: the 2020 peak read **9.88**. That
figure was measured while the rate was still a 24 h difference and the true peak
was 10.73; the argument is about the sampling grid, not the rate model, so it
stands unchanged now that the peak is **11.56**.

**Then decimate, because 8762 points is twelve times what a 724-column plot can
show.** Ramer-Douglas-Peucker on vertical distance, tolerance half a layer pixel.
Geometry is baked once in `build_static`; the per-frame work is only the truncation
and the colour. Measured: the 5881 points inside the plotted window to 198 under
the old 24 h difference and to **298** under the real-time rate — a difference is
a smoothed version of the thing it smooths, so the real-time curve is the spikier
one and keeps more of its points. Max deviation 0.997 layer px at `sc` = 2 against
the 1.0 px tolerance, the peak kept to 0.0000 px, and the frame cost re-measured
at 11.5 / 29.2 ms for `render_w` 1920 / 3840, against 11.8 / 28.8 booked before
the change: inside the run-to-run noise.

The marker's value is read from the hourly array itself and its point is INSERTED
into the drawn polyline, so "the marker is on the curve" and "the number is exact"
both hold. Reading the number back off the decimated polyline instead would put the
simplification's own tolerance back into the read-out — the 0.85-unit error the
change existed to remove.

**The truncation happens even when the cursor is off-plot.** The plot's x window
opens with the season's first month, so for the first four months of screen time
the cursor lies to the LEFT of the plot. Truncating only when the cursor is on-plot
put the whole season's curve on screen before the season had begun.

## 6b. The summary banner

Single's panorama banner, brought into this layer: one bar per storm, entering at
the top right the instant that storm dissipates. It is the one element here that
does not read out the season as a whole - it announces a single system.

| rule | value |
|---|---|
| size | `BAN_W x BAN_H` = 1400x70 author units, 20:1 - the art's own ratio |
| home | top right: `BAN_RIGHT` = 24 from the right, `BAN_TOP` = 20 from the top |
| enter | slides in from `BAN_SLIDE` = 460 px out, right to left, fading in, over `BAN_IN_S` = 0.8 s |
| hold | `BAN_HOLD_S` = 3.0 s |
| exit | slides back out to the right, fading, over `BAN_OUT_S` = 0.8 s |
| stack | a new banner joins at the BOTTOM of whatever is showing, `BAN_GAP` = 6 apart |
| rise | when one starts leaving, the ones below wait `BAN_RISE_DELAY` = 0.3 s and then rise one slot over `BAN_RISE_S` = 0.5 s on a cubic ease, staggered top to bottom by `BAN_RISE_STAGGER` = 0.1 s per slot |
| motion | vertical and horizontal are independent: a banner can rise while fading out |

* **The art follows the PEAK category**, exactly as in single:
  `summary/Summary-N-TC-<TD/TS/C1..C5>.mp4`, with C5+ and C5++ collapsing onto
  C5. It comes out of the pack lazily, one level at a time, into
  `<work>/res/_cache/fx/sumban_<level>/` at the clip's own 60 fps, 5 s per level.
* **Super-cyclone tint matches single.** Peaks at or below 155 kt retain the
  original art. Above 155 and below 170 kt use `(214, 106, 255)`; 170-185 kt
  interpolate from `(126, 44, 176)` to `(40, 74, 178)`; 185-200 kt fade
  linearly to #C6E8FF, then follow the shared anomalous palette through 500 kt. Replace HSV only where saturation
  exceeds 0.28, with single's median saturation/value normalization, preserving
  white cores and neutral pixels. Tint the original art before resizing and
  drawing text; include the tint in the frame-cache key so storms sharing C5
  art cannot reuse one another's peak colour. Helpers remain local to season.
* **The two lines are single's**, printed at single's own offsets - quoted at its
  1700-wide card and scaled by `BAN_W / 1700`: `<NN>W   <NAME>` (just `<NN>W` for
  a system that was never named), then `PEAK .. kt / .. hPa   ACE .. x10^4 kt2
  LOSS ~ ..   DEATHS ..`. A storm with no `damage.txt` prints `n/a`, as single
  does. The figures go through the card's own three-significant-figure rules, so
  a banner and the card beside it cannot disagree about what a storm cost.
* **Every position is a pure function of the screen second.** Nothing accumulates
  frame to frame, so a still is exactly the picture the render draws at that
  second, and a stack can be inspected without replaying the season.
* **The rises ADD.** A banner carries one eased displacement per departure that
  lifted it, so departures close together sum their velocities instead of
  snapping to an index.
* **One departure that lifts several banners staggers them**, top to bottom, by
  `BAN_RISE_STAGGER` = 0.1 s per slot: the one directly under the leaver goes at
  +0.3 s, the next at +0.4 s, and so on, so the stack closes as a downward wave
  rather than lurching on one frame. The stagger is a per-departure delay, so it
  rides the same additive structure as the velocities.
* **The fade is a true alpha fade**, not single's darkening paste. Single's base
  is a dark backdrop; this layer's base is a real plate, where a darkened opaque
  card would read as a black rectangle sliding in.
* **The season window can cut the last banner.** This layer never re-times its
  base, so a storm that dissipates with less than 4.6 s of film left is still
  showing its banner when the film ends.

## 7. The timeline

A baseline at y = 990 from x = 60 to 1860, with month ticks and labels centred in
the middle of each month. Its pointer is a heat-coloured glow, a solid line and a
ball, coloured by the ACE increment at that instant. The whole strip is part of
the static bake.

## 8. The traps, collected

Every one of these has happened. They are grouped by what they have in common,
because the common thing is what makes them recur.

### Units

* **A bare pixel number is a bug**, exactly as in pass 1. Everything is author
  units, or a ratio of the card.
* **`A + N * sc` needs both operands in the same space.** `bar_x0 = dx + 182.0*sc`
  had `dx` in author units and `182.0*sc` already in layer pixels, so the damage
  fill started `(sc-1)*dx` pixels left of the well its own frame was drawn around.
  The original wrote `(dx + 182) * sc`; a "roll back to the original's numbers"
  pass copied the numbers and dropped the parentheses.
* **This class is invisible at `sc = 1`.** `render_w` floors at 1920, so a 540p
  output has `sc = 1` and the two forms are the same float. The convenient debug
  resolution hides the whole family.

### Layers

* **Static bake vs live pass.** A label drawn in both shows through as a ghost.
  Every offset used by both layers is a NAMED constant for that reason.
* **Z-order between the layers is not automatic.** Static is composited first, so
  anything baked is under everything live. Bars' frames therefore live in
  `_frame_rects`, drawn last.

### Text

* **A sprite's height is not its ink height.** `_mtext` builds a sprite `cap*2.2`
  tall and composites it at `y - 0.45*cap`, so the ink is about
  `[y + 0.02c, y + 1.05c]`. Judging overflow by the sprite box overestimates by
  1.2x and points the wrong way — it is how the clock got moved up into the title.
* **Measure text on rendered pixels, and measure the right thing.** Number
  advances are not ink: in a tabular cell a `1` inks a fraction of its cell. Both
  a field-edge measurement and a sprite-box measurement gave contradictory answers
  here before the ink was measured directly.

### Measurements

* **A test that cannot see the failure proves nothing.** A "is the fill inside its
  frame" check that only searched INSIDE the frame reported "inside" for exactly
  the overflow it existed to catch. Search outside the box, on all four sides.
* **A tight colour tolerance, or the wrong pixel gets matched.** At a tolerance of
  120 the antialiased edge of a grey label matched the blue fill.
* **Kill the obvious sampling mistake.** Reading a fill's colour at "5 % along the
  bar" lands in the bare well when that bar is 1/30 full, and hands the test a
  black "fill" to search for. Take the expected colour from the constants.
* **Check the check.** After a fix, put the old expression back and confirm the
  test reports the failure. Otherwise there is no evidence the test works.

## 9. Performance

Per frame, warmed, independent of output size because the canvas is bounded:

| `render_w` | canvas | ms/frame |
|---|---|---|
| 1920 | 1920x1080 | 11.8 |
| 3840 (default) | 3840x2160 | 28.8 |
| 8534 | 8534x4800 | 177.5 |
| 17068 | 17068x9600 | 1032.7 |

The three rules that keep it there, and that must not be broken:

1. **author units, never pixels** — a bare output-pixel count is what makes 16K
   thirty times slower than 8K instead of four;
2. **static is cached once** — panels, grid, month names and every fixed string
   are rasterised once and blitted;
3. **nothing per-frame is a Python loop over pixels** — numbers, curves and bars
   are numpy over precomputed arrays or a bounded number of draw calls.

Rule 1 is not only about speed: it is the same rule that keeps the layout correct
at every size.

## 10. Checking a change

There is no test suite shipped. The checks that paid for themselves, in the order
they are worth re-writing:

1. `info` — the axes and the block count, before anything long.
2. **Counts against the data**: bucket every system by hand and compare with the
   model. A wrong model still draws a convincing bar.
3. **Cell geometry against the card**: every text row's ink band
   `[y + 0.02c, y + 1.05c]` inside its own panel, and no two rows touching.
4. **Strokes on a rendered frame**: walk a column through the stack and count the
   frame strokes and their thickness, at `sc` = 1 AND 2 AND 4. The `w = 1` and
   `w = 2` cases are different code paths in PIL.
5. **Fills against their frames**, searched on a window that reaches outside the
   frame on all four sides.
6. **The rate curve's own peak** against the hourly array, and the marker's
   read-out against both.
7. **A time sweep**, not a single peak frame — the off-plot bug only exists in the
   first four months, and the intro is the easiest place to render one frame and
   move on.

For all 200–500 kt body/halo nodes, use [extreme intensity rules](../../references/extreme-intensity.md). Cap both landfall size multipliers at 200 kt while retaining actual wind for colour and statistics.
