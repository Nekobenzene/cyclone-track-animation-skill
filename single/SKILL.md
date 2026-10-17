---
name: typhoon-track-animation-single
description: Render one tropical cyclone as an SMCY1.3-style broadcast animation - follow camera, intensity-coloured track with fading categories, spinning category icons with level cross-fades, ACE bar, damage pop-ups, a pulled-back panorama with info cards and a tinted summary banner. Driven by a storm config plus best-track text files and the SMCY1.3 asset pack.
---

# Single storm

Minimum input: at least one valid path segment of any supported phase (DB, TC, RV or EX). TC.txt is not mandatory. This skill is usable by any agent with filesystem and command execution capabilities.

Renders one storm, start to finish, from best-track text files:

* a follow camera on an intensity-coloured track (level changes cross-fade linearly in
  wind, phase changes linearly in time),
* the spinning category icon, its glow, and the TD -> TS upgrade / ERI / landfall effects,
* the HUD: storm panel, ACE bar with its ruler, wind and pressure curves,
* damage pop-ups, the pulled-back panorama with peak and landfall cards, and the summary
  banner tinted to the peak category.

## Layout

    single/
      SKILL.md
      scripts/typhoon_anim.py        the whole renderer (self-contained)
      references/storm-workflow.md   the rule book - read this before changing anything
      references/storm-pipeline.md   data -> assets -> render -> audio -> mux
      references/storm-style-spec.md the frozen look: geometry, colours, type, timings
      examples/*.yaml                one config per finished storm, plus template.yaml

## Source-only project startup

For a new project containing only `sourcedata/`, run:

```text
python scripts/launch.py <project> info
python scripts/launch.py <project> all
```

`launch.py` uses the shared parent-skill runtime (NumPy, Pillow, OpenCV, PyYAML,
FFmpeg and FFprobe), creates `build/storm.yaml` only when no project YAML
exists, and renders 1920x1080 at 120 fps. It reads current source tables directly
and uses auto panorama framing. Existing YAMLs are preserved. Standard
DB/TC/RV/EX track filenames and long aliases are detected by the renderer;
nonstandard names require `data.series`. Labels default to the project folder
name; editorial titles, selected peaks and credits can be refined in the YAML.
The complete asset pack is bundled at `../assets/SMCY1.3` and is the
default for new projects. Pass `--assets <SMCY1.3 folder>` to override it;
ancestor `res/SMCY1.3` folders are a fallback. Project YAML paths remain relative.
The bundled runtime targets this Windows x64 Python version (see
`../runtime/platform.json`); Only a compatible Python interpreter remains external.
Do not copy dependencies into each new project. For a different Python ABI or
OS, rebuild the skill runtime with compatible package wheels and FFmpeg tools.

## Use

The black preview is optional: generate it on request or whenever it helps
inspect track colours and patterns. It is not a prerequisite for rendering,
and `render`/`all` do not generate it automatically. It uses the same framing,
resolution and track colours as the normal map preview:

```text
python scripts/preview_black.py --project <project>
python scripts/preview_black.py --config <storm.yaml>
../bin/typhoon/typhoon.exe single <project> preview-black
../bin/typhoon/typhoon.exe single-config --config <storm.yaml> preview-black
```

It writes `output/preview_black.png`, without loading map pixels or extracting
effects. Basin metadata and the shared runtime are still used. Existing
`preview.png` is preserved. The standalone utility and executable command use
the same renderer implementation. Track colours and dashed/solid family rules
are documented in [Single track appearance](../references/track-data.md#single-track-appearance).

    python scripts/typhoon_anim.py --config examples/template.yaml assets
    python scripts/typhoon_anim.py --config examples/template.yaml render
    python scripts/typhoon_anim.py --config examples/template.yaml audio
    python scripts/typhoon_anim.py --config examples/template.yaml mux
    # or the whole chain:
    python scripts/typhoon_anim.py --config <storm>.yaml all

`info` prints the numbers a run will use (peaks, landfalls, ACE, TD->TS crossings) and
`poster` writes the still. The config carries only storm-specific values - everything
else is frozen, so two storms rendered months apart look identical.

## Notes

* Intro copy is verbatim: `storm.intro_title` overrides `storm.title` for the
  opening only; otherwise the opening uses `storm.title`. Only when both fields
  are absent does it default to `hypoTC` (hypothetical) or `CYCLONE` (real).
  `storm.intro_line` is displayed unchanged and defaults to empty. Explicit empty
  strings hide the corresponding text. Include any desired 假想/HYPOTHETICAL
  wording in the copy itself; `hypo.txt`/`storm.hypothetical` never rewrites it.
  Existing configs that relied on automatic wording must now state the desired
  opening explicitly. Keep HUD `title` separate by setting `intro_title`.

* The renderer must stay self-contained: no shared module, no import of any other
  project file. If a second renderer needs the same helper, copy the code into it.
* The style is the contract. `references/storm-style-spec.md` and the rules in
  `references/storm-workflow.md` win over any local improvement.

## Project paths

Follow [Agent working files](../SKILL.md#agent-working-files): create the storm's
`build/` first and write all tool logs, temporary helpers, diagnostic/test files
and intermediates there from the outset, including for background jobs. Never
use the project root as temporary storage before cleanup. Final deliverables
belong in `output/`; shared extracted assets remain in the shared cache.

Storm projects live at `<work>/single/<Storm>/`, with YAML in `build/`:

```yaml
paths:
  storm: ..
  assets: ../../../res/SMCY1.3
  sourcedata: sourcedata
  build: build
  output: output
```

`paths.storm` (legacy alias `workdir`), `paths.assets`, and an explicit
`paths.cache` resolve relative to the YAML file's directory, independent of
launch directory. `sourcedata`, `build`, and `output` resolve relative to the
storm folder. Absolute paths remain supported. Programmatic plain dictionaries
without a config file retain current-directory resolution. The default cache
is beside the asset pack (`<work>/res/_cache`); the legacy sibling-pack asset
fallback remains available.

## End-card slot

The separate dimmed statistics/credits page after the panorama is removed.
Exports end when the panorama cards and banner finish, with no extra end-card
hold, dim/blur, statistics page or fade to black. Pull-back and panorama cards
remain. `SUMMARY = 0` reserves no frames; `frame_summary(t)` is an inert future
design hook. `summary_rows()`, `summary.*` and `credits` remain as data interfaces
for that redesign and are not shown as a separate page. Do not restore the old
page from historical configs or references.

## Explicit years

All dated input fields use four-digit years: `YYYYMMDDHHmmSS` (14 digits),
or `YYYY-MM-DD-HH-MM-SS`. This includes track segments, the naming timestamp
in `Num.txt`, and full timestamps in `landfall.txt`. The renderer rejects
12-digit timestamps instead of guessing a century. Historical dates such as
1628 stay 1628; storm identifiers are not timestamps. Legacy month/day landfall
entries, where used, inherit the explicit track year.

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

`Num.txt` has three positional lines: invest number, depression number, and
UTC naming timestamp (14 digits, four-digit year). Preserve blank placeholders.
There is no JMA-number row; naming time is at index 2.

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

## Chinese text verification

Route variable text through draw_text and measure it with text_width. These helpers select bundled Source Han Sans SC for CJK and Saira for Latin/digits, preserving sizes and anchors. Chinese source notes, landfall places and panorama card rows must not use Latin-only font rendering. Inspect intro, HUD, landfall, damage and panorama keyframes before full rendering; missing-glyph boxes block the render.


## Optimized rendering and intensity sound

The renderer caches fonts, exact track samples, trail colours and the settled
static HUD. Banner frames are decoded/tinted on demand with a bounded pixel
cache. Keep these caches bounded and clear storm-dependent samples on rebuild.
The sustained C4+ and 170 kt sound beds run separately over each qualifying
intensity interval; a weaker gap must remain silent. Landfall impact size uses
the copied season rule; persistent Landed markers do not grow with intensity.
See [rendering performance](references/rendering-performance.md) for sizing,
cache limits, validation and current-source rerender guidance.

## Preview frame rates and landfall tint

* EX retains its source artwork at <=30 kt; above that, use continuous RGB
  interpolation through sampled TC band midpoint colours, without plateaus or
  per-frame exposure normalization. A storm remaining EX never triggers TS/SS upgrade FX/audio.
* TC and EX reach the ACE fill endpoint `#C6E8FF` at 200 kt. TC keeps its
  existing category transitions. At >=100 kt, EX adds lightning extracted from
  the existing uncoloured C7 asset into the shared derived cache.
* Over 185..200 kt, the TC numeral 5 darkens to `#1E0309`. Single's CATEGORY
  5++ badge, panorama cards and summary banner also transition continuously:
  pale theme accents, dark-red badge/banner text, and pale panorama-card text
  at 200 kt. The banner's embedded 5 uses its own stable mask.

See [the style specification](references/storm-style-spec.md) for sampling,
masking, colour endpoints and exact interpolation rules.

Set `output.fps: 30` with `output.width: 960` and `output.height: 540` for a
540p30 full-film preview. Output fps accepts integers 1..120 and defaults to
120. Frames sample the existing 120 fps author timeline, preserving camera
smoothing and effect duration; the preview does not resimulate at 30 fps.

Landfall impact tint follows the icon's `icon_tint_colour` rule: C5 and below
keep the authored colour; C5+/C5++ use `theme_col` quantized down to multiples
of 8 through 200 kt; above 200 kt use the full theme colour. Apply the existing HSV hue-replacement algorithm. White cores are retained.
The target colour uses intensity at landfall, not the later display-frame
intensity. It stays fixed during the 1 s impact. Tint uses the bounded asset
cache; it adds no separate glow and does not alter persistent Landed markers.

## TC-only ACE and unobstructed ending framing

ACE includes only synoptic 00/06/12/18Z samples whose effective type in the
merged, chronologically sorted path is `TC`, after skip_first/skip_last.
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

## Executable option

The parent skill also provides `bin/typhoon/typhoon.exe`, with its Python runtime
bundled. See the parent `SKILL.md` executable section for commands and rebuild
instructions. Original sources remain in this folder; rebuilding applies edits.

## Track types and extreme intensities

Read [path data and transitions](../references/track-data.md) for unified
`track.txt` (full or sparse sixth-column types), interleaved legacy files,
MV/MD, SD/SS, hemisphere-specific art, TC-only ACE and TS/SS upgrade triggers.
Read [extreme intensity rules](../references/extreme-intensity.md) for the
200–500 kt palette, independent halo and 200 kt landfall size cap.
