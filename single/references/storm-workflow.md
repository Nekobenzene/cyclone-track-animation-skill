# Single production workflow

For one cyclone, use `single/scripts/launch.py <project> <command>` or
`typhoon.exe single <project> <command>`. Paths in commands are relative to the
actual skill installation; project data stays outside it. Read the complete
[YAML/data schema](storm-pipeline.md) when adjusting configuration and the
[visual specification](storm-style-spec.md) before changing composition or effects.

## Project and input

```text
<project>/
  sourcedata/  track.txt or per-type tracks; optional Num/hypo/landfall/damage/cloud
  build/       storm.yaml, logs, helper scripts, decoded cloud, audio/video intermediates
  output/      MP4, posters, previews
```

At least one valid path of any type is required; TC is optional. All track formats,
types and transitions are defined in [track data](../../references/track-data.md).
New timestamps use four-digit years and UTC. Auxiliary input formats are in the
pipeline reference. Do not manufacture a TC segment, identity or naming timestamp.
Damage units must match `data.damage_loss_unit`; preserve intentional overrides.

The skill provides shared assets, fonts, FFmpeg and dependencies. Source mode needs
a compatible Python; compiled mode bundles its interpreter. Installation details
are in [DOWNLOAD](../../DOWNLOAD.md). No per-project copy of scripts or media is needed.
The cache defaults beside the asset pack; YAML can override it. Keep the source
asset pack read-only and generated extracted media in the shared cache.

## Inspect, configure, preview

Run `info` first. The launcher reads the unique `build/*.yaml`/`*.yml`, or generates
`build/storm.yaml` if absent. Check names, UTC span, track types, peak times, ACE,
landfalls and losses. Set opening copy explicitly when desired; hypothetical flags
do not rewrite configured text. Use `panorama: auto` to fit the track between cards
and below the summary banner. YAML relative-path bases are documented in README.

Use the [independent preview](../../references/preview.md) for map/black/transparent
track and ACE heat stills, or the original `preview` command. Black preview is
optional. `test` checks animation keyframes and `poster` creates a representative
frame. Inspect opening text, mixed Chinese/Latin labels, HUD, peak and landfall
cards, and the ending before a long render. Keep test frames and logs in build.

## Render

`all` prepares assets, renders video, makes effects audio and muxes the final MP4.
Individual commands are `assets`, `render`, `audio`, `mux`. Video standard is
1920×1080/120 fps, H.264 CRF16, AAC192k, effects only. Smaller test exports sample
the same 120 fps author timeline. Native-map static output is independent of video
size. See [performance](rendering-performance.md) for memory bounds and export sizing.

Check the final stream size/fps, duration and audio before delivery. Rendering
reads current sourcedata; don't substitute old build snapshots. When source data
changes, revisit manually selected peak hours, reanalysis, ACE cutoff and any
explicit numerical banner copy. Preserve existing deliberate settings unless the
task requests recalculation. Background commands use explicit build logs/output paths.

## Visual contracts

The animation follows the style specification: category transitions, hemisphere
icons, strengthening TS/SS upgrade triggers, timed ERI/landfall effects, sound
intervals, panorama cards and the closing banner. There is no additional statistics
page after the panorama. Static preview compositing lives in the shared preview
script; video drawing stays in the renderer. Use bundled Saira and Source Han Sans
SC with the text measurement helpers. Changes to the approved style must be
reflected in the specification. [Extreme intensities](../../references/extreme-intensity.md)
define the 200–500 kt palette and 200 kt landfall size limit.
