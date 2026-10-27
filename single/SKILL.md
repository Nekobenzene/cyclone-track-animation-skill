---
name: typhoon-track-animation-single
description: Render one cyclone with an SMCY1.3 follow camera, intensity-coloured track, animated category icons, ACE bar, landfall/damage effects and a panorama with summary cards, from source tracks and optional YAML configuration.
---

# Single cyclone

## Video export selection

Default video output is **track only**, including the main track animation and
ending panorama, with a static editing lead-in instead of the title opening. Use `--video-mode intro|track|full` with
`all`, `render`, `audio`, `mux` or `info`; CLI overrides YAML `output.video_mode`.
`intro` exports only the 3.3 s opening, `full` exports opening + track + panorama.
Track and full share identical durations and audio timelines: track holds its
initial map and complete HUD for INTRO seconds, so an intro can replace that
lead-in without moving the track or sound. HUD has no entrance animation. The
cyclone icon and label fade in during INTRO's last 0.5 s, then movement begins.
The camera, cloud frame and icon rotation stay fixed during the lead-in. Full's
intro crossfades onto this same prepared scene. Intro audio is silent. Use the same mode for split
render/audio/mux steps. Final names add `_intro`, `_track` or `_full` before `.mp4`;
intermediate video/audio names also include the mode, preventing cross-mode reuse.

```text
bin/typhoon/typhoon.exe single <project> all                     # track only
bin/typhoon/typhoon.exe single <project> all --video-mode intro
bin/typhoon/typhoon.exe single <project> all --video-mode full
```

Read the parent [SKILL](../SKILL.md) for shared resources and working-file rules.
Minimum input is one valid path of any supported type; TC is optional. The executable
and all source commands below are relative to the parent skill root.

## Workflow

```text
bin/typhoon/typhoon.exe single <project> info
bin/typhoon/typhoon.exe preview single <project>
bin/typhoon/typhoon.exe single <project> test
bin/typhoon/typhoon.exe single <project> all
```

`single/scripts/launch.py <project> <command>` is the source alternative.
The launcher uses the unique YAML in `build/`, or creates `build/storm.yaml`
when absent. Defaults are 1920×1080/120 fps and `panorama: auto`. Existing configs
are preserved. Edit identity, opening copy, peaks and credits as needed; read current
source tracks directly. `single-config --config <yaml> <command>` chooses an explicit
config. `assets`, `render`, `audio`, `mux` run individual stages; `poster` makes a still.

Static preview uses the [shared preview implementation](../references/preview.md):
original map density, optional heat, map/black/transparent backgrounds. Original
`single <project> preview` accepts the same `--background` and `--layers` options.
`preview-black` is an optional black shortcut (add `--layers track` for paths alone) and is not a prerequisite.
`render`/`all` generate the default map preview before encoding; the animation
camera and paths are independent of static preview styling.

## Data and visual contracts

- [Path data](../references/track-data.md): unified/sparse types, interleaved files,
  WV/MD, SD/SS, hemispheres and transitions. TC-only ACE uses 00/06/12/18 UTC,
  wind ≥34 kt and the configured cutoff.
- [Configuration and pipeline](references/storm-pipeline.md): full YAML fields,
  landfall/damage/cloud inputs, relative path bases and stage outputs.
- [Animation workflow](references/storm-workflow.md) and
  [style specification](references/storm-style-spec.md): timing, geometry and effects.
- [Performance](references/rendering-performance.md): bounded caches, encoding,
  interval-based intensity sound and source-data rerenders.
- [VIS_CLEAN processing](../references/vis-clean.md): offline crop/tone/feather tuner,
  UTC-aligned export and `cloud.format: screen` without a second crop or mask.
- [Direct cloud video](../references/cloud-video.md): compiled configuration/preview
  scripts and `cloud.format: vis-clean-video` for on-demand processing during final
  path rendering, with automatic alignment from first/last observation UTC.
- [Extreme intensities](../references/extreme-intensity.md): palette to 500 kt,
  high-wind numeral/banner/card treatment and landfall size cap.

Opening title is verbatim: `intro_title` overrides `title`; explicit empty strings hide it. The Chinese second line is generated as `<category> <name_cn>  <year>-<basin>`; existing `intro_line` supplies a fallback Chinese name, and explicit empty `intro_line` hides it. Title and second line fade in simultaneously at 0.9–1.7 s; intro lasts 3.3 s, with a 0.7 s map crossfade. No footer is drawn. Category uses TC-only peak wind when any TC exists; otherwise ST/SD/SS takes priority over EX, then disturbance. See the style specification for basin and strict 112/154/169 kt prefix thresholds. Missing titles fall back to hypoTC/CYCLONE. Choose hemisphere
art from current latitude. TS/SS upgrade FX/audio trigger only when entering the
respective level while strengthening, regardless of preceding type; SS FX are
yellow-green. Sustained C4+/170 kt sounds stop during weaker intervals.

Use auto panorama to fit the full track between the side cards and below the top
banner. The film ends with this panorama; there is no separate statistics page.
Use bundled fonts and text-measurement helpers for Chinese/Latin mixed text.
Inspect keyframes for readable text, card layout and event placement before a long run.
For source-derived peaks, omit `data.peaks` or set it to `auto`: every local wind
maximum is recomputed from the current effective intensity knots; a maximum plateau
counts once, at its lowest-pressure fix. Explicit lists (including `[]`) remain overrides.
Check old generated single-peak lists against all source cycles before rerendering.
The panorama banner derives loss and deaths+missing totals from loaded damage events
unless explicitly overridden by `banner.loss` / `banner.deaths` / `banner.line2`.
Cloud footage fades out over `cloud.fade_out_seconds` (default 0.5 output seconds)
after its final observation. Check the last cloud frame, fade midpoint and exit,
plus the panorama banner and all peak cards before the production render.
