# Style spec (frozen) - do not restyle

Rendered from `typhoon_anim.py`. Any change here changes every storm's
look, so treat this file as the contract.

## Output

| | |
|---|---|
| resolution / fps | 1920x1080 / 120 |
| structure | intro 5 s + main 46 s + pull-back 2 s + adaptive panorama hold; reserved end card **0 s** (total = 53 s + actual hold) |
| video | H.264 CRF 16, yuv420p, +faststart |
| audio | AAC 192k, **sound effects only - no BGM** |
| poster | single frame at `last_peak + 0.6 h` |

## Camera

* Follow-cam, centred on the storm with a small lead along the direction of
  travel, field of view **22.8° lon** (aspect 16:9, so 12.825° lat).
* Sub-pixel crop (`warpAffine`), camera path smoothed with a 101-frame Hann window.
* Pull-back over 2 s to `view.panorama_span_lon` centred on `view.panorama_center`,
  or to an automatic fit when `view.panorama: auto` (keeps the whole track below
  the 235 px banner).

## Time warp

210 h of data is mapped onto 46 s with a velocity profile that slows near
genesis, the peak (τ≈0.53), landfall (τ≈0.71) and dissipation:

```
speed(τ) = 1 - 0.42·G(τ,0.53,0.085) - 0.26·G(τ,0.71,0.055)
             - 0.16·G(τ,0.06,0.07)  - 0.12·G(τ,0.98,0.05)
```

## Screen layout (1920x1080)

| Panel | Box | Contents |
|---|---|---|
| status (top-left) | `40, 30, 640, 360` | UTC TIME / POSITION / INTENSITY, category badge |
| title (top-right) | right-aligned at x=1880, y 30..182 | storm title 60 px, `name_cn - id` 30 px, source line 20 px |
| ACE | `1160, 210, 720, 182` | label 21 px, value 42 px, 684x57 reveal bar, full scale auto-extends past 40; summed on synoptic fixes but ramped continuously so the bar never jerks |
| intensity graph | `40, 530, 700, 356` | wind (solid, no fill) + MSLP (dashed) drawn with a shape-preserving cubic over plateau-collapsed knots. **Left axis = pressure (870..1010 hPa), right axis = wind (the category gridlines)**, 185 kt top auto-extending past it | Y axis tops out at 185 kt and auto-extends past it; with 3+ peaks the micro-labels alternate height so they do not collide |
| legend | `40, 894, 700, 58` | TD TS C1..C5 C5+ C5++, 75 px pitch |
| timeline | `40, 962, 1840, 84` | day ticks, playhead, elapsed + clock chips |
| cloud inset | centre `1640, 620`, r = 210 | feathered, screen-blended |
| credit line | centred y=1062, 18 px | `storm.credit_line` |

Panels: fill `(7,11,22,205)`, 1 px border `(255,255,255,92)`, radius 4.
All HUD text is at full brightness (labels ~236, values 255).

## Fonts

`consola.ttf` / `consolab.ttf` (Latin), `msyh.ttc` / `msyhbd.ttc` (CJK),
`seguisb.ttf` / `arialbd.ttf` (titles). Chinese and Latin in one string **must**
be drawn with `mixed()` / `mixed_base()` so they share a baseline; the CJK size
is set so its visual height matches the Latin cap height (e.g. Arial Bold 32 px
pairs with YaHei Bold 27 px).

## Intensity vocabulary

| wind (kt) | level | colour | icon |
|---|---|---|---|
| <34 | TD | `196,220,255` | `N-TD-D` |
| 34-63 | TS | `58,226,92` | `N-TC-TS` |
| 64-82 | C1 | `255,232,40` | `N-TC-C1` |
| 83-95 | C2 | `255,158,30` | `N-TC-C2` |
| 96-112 | C3 | `244,86,32` | `N-TC-C3` |
| 113-136 | C4 | `232,34,28` | `N-TC-C4` |
| 137-155 | C5 | `255,60,226` | `N-TC-C5` |
| 156-169 | **C5+** | `214,106,255` (pink-purple) | C5 icon hue-replaced |
| >=170 | **C5++** | deep purple `126,44,176` → deep blue `40,74,178` at 185 kt | C5 icon hue-replaced |

* Level changes are **cross-faded**, not snapped: colours blend over ±3.5 kt and
  the icons are mixed with the same weights (weighted `Image.blend`).
* The **dashed** run of the track is the remnant-vortex phase; it follows the
  derived phase boundary, so it sits on the right segment for every storm.
* **Plateaus are eased, not drawn flat.** Consecutive equal wind (or pressure)
  fixes collapse to a single knot at the middle of the run, so the curve keeps
  moving slowly through the plateau. The two quantities are handled separately.
* **Rapid intensification is a window test on the smoothed curve**, not a
  two-band jump (spec rule 11). Walk the whole time axis and mark a 6 h window
  when the wind rises **>= 20 kt**, or a 24 h window when the total rise
  **>= 60 kt** and no 6 h inside it rises less than 10 kt. Touching windows merge
  into one event; the window start is wherever the curve says, not 00/06/12/18Z.
  The ERI animation's **midpoint** is placed on the event's midpoint, and the
  event is never reported on the end card.
  `particle/ERI.gif` + `sound/random/Rapid Intensification.ogg` fire there (the
  GIF is 37 frames in **0.3 s**), except for events that end in **C1, C5+ or
  C5++** (`data.ri_no_fx_bands`), which blend silently.

  The window only drives that burst. **It never moves the icon's level**: an
  event can run 40 h, so holding the icon at the window's target level would show
  a category the wind has not reached for most of it (the badge would read
  `CATEGORY 5++` at 165 kt). The level always follows the wind; inside a window
  the crossfade between adjacent bands is merely sharpened by
  `data.ri_blend_frac` so the change still reads as sudden.
* **The icon cross-fade is linear in INTENSITY, not in time.** Around a band
  boundary  the incoming icon rises from 0 at  - icon_fade_kt to 1 at
   + icon_fade_kt (3 kt by default), so the C5 boundary at 137 kt begins
  blending at 134 and completes at 140. The two icons are blended into ONE
  layer, so the number inside the icon cross-fades with the colour and nothing
  brightens or jumps. Because the opacity is a function of the wind alone,
  **weakening plays exactly the same fade in reverse**, and a storm sitting on a
  boundary shows the blend - which is itself the signal that it is on the
  boundary.
* **The halo is a deliberate, graded effect.** The lower bands get none - the
  library art already carries its own soft glow, and running it through the hue
  replace brightens that halo (measured C1 +197 %, C5 +81 % of the ring), which
  reads as a glow nobody asked for. C5++ gets a weak halo from 170 kt, growing
  to a strong one by 184 kt. The halo is added only where the base pixel is
  still dark, so it grows outward without blowing out the numeral.
* Icon linear size grows **+1 % per kt above 155 kt, cumulatively** (cap 1.32x).
* The C5+/C5++ tint replaces hue only - the white core stays white so the "5"
  stays readable.
* **TC high-wind theme:** Keep the purple -> blue ramp through 170..185 kt,
  then interpolate linearly to the ACE fill's right-edge colour `#C6E8FF` at
  200 kt and hold it above 200 kt. Apply the same endpoint in single preview
  and season overview copies. Existing TC category and tint rules remain.
  Above 185 kt, smoothstep the centre numeral 5 to black-red `#1E0309` at
  200 kt. Apply after glow through a cached mask from the original C5 numeral,
  protecting the surrounding white eye, rings, arms and animated lightning.
* **EX icons:** 30 kt and below retain the authored sprite exactly. Above 30 kt,
  blend in colours sampled from actual TC sprites over 30..37 kt. Take the median
  bright chroma from four rotation frames, excluding white/neutral and dark pixels;
  sample C5+/170/185 kt nodes after applying the TC renderer's own tint. Place
  TD through C5+ colours at each finite TC band's midpoint; interpolate linearly
  in RGB between nodes without category plateaus or narrow fade windows. Follow the
  continuous purple/blue/ACE-fill-endpoint ramp through 170/185/200 kt. Sample
  the median RGB of the rightmost column in `gui/ace/ace_color_1000.png` for
  the 200 kt node (currently `#C6E8FF`). Use floating RGB
  colour, without the TC tint cache's 8-value quantization; feather the chroma
  mask and preserve neutral white core and EX lettering. This changes only the
  EX sprite, including during phase crossfades, not track colour or phase rules.
  Preserve each source pixel's authored brightness; never normalize exposure
  from a per-frame histogram or median, which makes rotation flash in colour.
  Do not add a separate high-wind outline to EX sprites.
  At wind >=100 kt, screen-composite blue-white lightning from the uncoloured
  C7 clip at the same animation frame. Derive filaments against a six-turn,
  same-angle neutral baseline; exclude static body edges and the centre numeral.
  Cache the extracted native-resolution filaments at icon size, preserving the
  EX lettering. Below 100 kt, skip this layer.
  EX never triggers the TD-to-TS upgrade flash or sound; an empty `ts_all`
  list means no event and must not fall back to the unfiltered `ts` crossing.
* **Single high-wind cards:** Over 185..200 kt, the `CATEGORY 5++` background
  follows the theme continuously to `#C6E8FF`, and its text smoothsteps from
  white to `#1E0309`. Below 185 kt retain existing styling, including the
  176..182 kt text fade. Panorama peak/landfall accents and heading text follow
  the continuous theme, while other text smoothsteps from its old colour to
  `#C6E8FF`. Do not switch colour immediately above 185 kt. The summary
  banner's embedded 5 darkens over 185..200 kt to `#1E0309` using a stable
  source numeral mask; do not recolour the surrounding eye or lightning.
  Both summary-banner text lines smoothstep to `#1E0309` over 185..200 kt;
  fade their shadow out over the same interval.

## The two intensity cards

Under `INTENSITY` the HUD stacks three blocks (spec rules 16, 17):

| block | content |
|---|---|
| `CATEGORY n` badge | SSHWS level, filled in the level's theme colour |
| CMA card | extended Beaufort force + Chinese grade, e.g. `12 级  台风`. The m/s value is **never printed**. Grade colours: 热带扰动 bright grey, 热带低压 grass green, 热带风暴 sea blue, 强热带风暴 gold, 台风 orange, 强台风 pink, 超强台风 red. An extratropical system reads `温带气旋` in the disturbance grey - the tropical scale does not describe it |
| value row | `nnn kt  -  nnnn hPa` |

The kt -> CMA m/s relation is **read off `intensity/机构对照.jpg`**, not converted
(`kt * 0.514444` is a whole grade out around 104 kt). The mapping lives in
`intensity/mapping.json` and is loaded, never re-derived.

Beside the cyclone icon a label names it (spec rule 17): the **INVEST number**
during the disturbance phase, the **depression number** once it is a tropical
cyclone but unnamed, and the **English name** once named.

## Effects

| Trigger | Effect |
|---|---|
| every TD→TS crossing | `note_ts.mp4` + `note_ts.ogg` (0.5 s) - a storm that weakens below TS and re-intensifies gets a second flash. Crossings in the **extratropical** phase are skipped |
| >=113 kt | `noice_category4.ogg` looped over each C4+ interval; silent in weaker gaps |
| >=170 kt | `noice_170.ogg` looped over each interval at or above 170 kt |
| landfall | impact clip + sound chosen from the category at landfall, at native 60 fps (never slowed). **Above 155 kt** it switches to `landfall-C6.mp4` + `sound.landfall.C6.ogg` and the effect grows by `1 + (wind-155)*5 %` of linear size (spec rule 13), keeping the clip's aspect. `weaken.ogg` 0.35 s later at 2/3 gain |
| landfall marker | `Landed-Cx.mp4` **spins continuously on the path at 30 % of its linear size**; the library clip's shrink-and-vanish tail is **cut** (spec rule 3). It never scales with intensity - only the impact burst does |
| peak marker | a colour dot with a **thin white ring**, filled in that peak's own theme colour (spec rule 4); it stays on the path for the whole run |
| peak / landfall text | appears with the marker, then **fades out 2 s later** (spec rule 2). The marker stays |
| damage event | floating number from the place: red `death+missing` (skipped when 0) and yellow `loss亿(CNY)` (skipped when 0), projectile motion up→decelerate→fall, at **1.5x speed with a fade-out** (spec rule 15), plus `sweep.gif` + `sweep1.ogg`. Places sharing a `group` are **summed into one pop-up**; the rest are **queued** (`damage.min_gap`) and **fanned out** (`damage.spread`). The flight is **centred on the closest-approach moment** (spec rule 1), so it is at its apex exactly when the centre is nearest |

Audio gains: each landfall clip is peak-normalised, then weighted by the
category at landfall (TS 1.00, C1/C2 0.95, C3 0.70, C4 0.50, C5+ 0.35) so a C5
strike does not bury a C1 one; everything else uses the tuned values × 2/3, then
a soft limiter at 0.82.

The phase boundaries (disturbance / tropical cyclone / remnant vortex /
extratropical) are **derived** from the series - the midpoint between the last
fix of one phase and the first fix of the next - never hard-coded.

## Ending

The ending is **one continuous shot** (spec rule 5): cache a separate panorama
frame and you get a visible jump the moment the zoom-out finishes. Pull back
through the real camera.

1. **Pull-back (2 s)** - camera zooms out, all panels slide up/down while fading,
   the storm icon and landfall markers fade out, the path stays.
2. **Panorama (2 s, batched in 4 s columns)** - the track alone, with **no text
   annotations on the path** (spec rule 6). Instead:
   * the `summary/Summary-N-TC-<peak>.mp4` banner slides in **from the right**;
   * **landfall cards enter from the right**, one card per landfall;
   * **peak cards enter from the left**, one card per peak;
   * each card carries its own intensity theme colour.

   A landfall card shows place, lon/lat, intensity and UTC time. A peak card
   shows the peak index, `xx kt / xx hPa`, the SSHWS level and the UTC time.

   When one side has more cards than fit (spec rule 7) the columns **batch**: a
   column holds for **4 s**, fades out (left for landfalls, right for peaks) and
   the next column enters. If one side has few while the other has many, the
   sparse side's cards **and the banner wait in place** and fade out together
   with the busy side's last column.
3. **Reserved end card (0 s)** - no displayed frames. The dimmed/blurred
   statistics and credits page has been removed. `frame_summary(t)` remains
   an inert extension hook; exports end at the panorama boundary. There is no
   extra tail or fade to black.

Every card enters with a short slide-and-fade, both here and at the start of the
track animation (spec rule 9) - nothing is allowed to simply appear.

## Intro card

Black, logo centred, three lines fading in at 0.9 s / 1.8 s / 2.6 s:

| line | y | content |
|---|---|---|
| title | 690 | `storm.intro_title` (fallback `storm.title`), verbatim, Saira Bold 60, tracked. Recommended authored copy: `CYCLONE <NAME>` / `hypoTC <NAME>`. If neither field exists, use `CYCLONE` / `hypoTC` according to hypothetical status. |
| name | 762 | `storm.intro_line`, verbatim (empty when absent), mixed fonts, 25 px. Recommended copy: `<热带气旋 / 假想热带气旋><中文名> - <year> - WESTERN NORTH PACIFIC`. |
| footer | 828 | `intro_footer`, mixed fonts, 15 px |

Every one of the three goes through the mixed CJK/Latin helper - a Chinese
character in a Latin-only line renders as a tofu box.

## Cards that grow with the data

Two blocks are laid out from the data, so a storm with an unusual number of
features still fits:

* **End-card peak list** - up to 5 maxima stay in one column; past that it splits
  into two columns inside the left column only (x = 110 / 510), with a compact
  `135/930 - 07-28 18Z` form.
* **Panorama tags** - `pano_dx` / `pano_dy` are the *preferred* offsets. A solver
  then displaces a tag (44 px steps vertically, then along its leader) until it
  clears both the tags already placed **and the projected track**. Never
  hand-tune the offsets against a projection.
* **Intensity-graph peak tags** - the collision threshold is the label's own
  width plus 14 px, so short tags like `P1`..`P10` do not stack.

## Crediting

Third-party imagery is credited on the end card and in the HUD credit line. If
the provider's watermark has to be cropped away to make the inset clean, the
on-screen credit replaces it - never remove an attribution and leave nothing.

## Text rules

ASCII only, apart from Chinese. Write `CNY`, `x10^4 kt2`, `20.4N`, `09-14 19Z` -
never `° × ⁴ ² · → ≈ ¥`.

Any line that mixes the two scripts must go through `mixed()` / `mixed_base()`:
the HUD title block, the panorama banner's two lines, the summary card's header
subtitle (a Japanese customary name will render as tofu otherwise) and every
Chinese string.

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

## Compact corner HUD revision

Status, title/ACE and graph/legend groups are composited at 85% of their author sizes, anchored to the same outer margins. Timeline geometry and type remain unchanged. The status card has tighter row spacing and a 530x336 author box; the left white accent stripe is removed. ACE uses a 154px-high author box and a 44px trough at y+96 to reduce empty space. Static and live layers are transformed together so values, curves and ticks stay aligned. These settings supersede the older HUD geometry table above.

## Landfall impact size (season rule)

The impact clip retains its aspect ratio and plays at native 60 fps for 1 s.
Its longest side in the 1920x1080 composition is:

```text
grow = 1                           if wind <= 155 kt
grow = 1 + (wind - 155) * 0.05      otherwise
fade = max(0, 1 - 0.005 * (170 - wind))
box = max(4, round((2.966 * 1.2) * 236 * grow * fade))
```

Wind comes from the intensity grid interpolated at the landfall hour. As in
season's active code, the linear `fade` term continues above 1 above 170 kt;
do not clamp it to 1. `236` is single's base icon glyph, not season's 140 px
glyph. This replaces the old `400 * grow` impact box; large events can exceed
the frame height. Persistent Landed markers keep their existing size.

## Landfall impact tint

Use the same tint rule as icon sprites, based on the interpolated intensity
at landfall. Only C5+/C5++ are recoloured: quantize each `theme_col` channel
down to a multiple of 8, then apply `tinted()` to the impact asset, preserving
white cores. C5 and lower categories retain original artwork. The colour is
latched for the 1 s impact; no additional glow or Landed-marker tint is added.
`output.fps` optionally samples the 120 fps timeline at 1..120 fps; use 30 for
previews while retaining the same author layout and motion timing.

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
