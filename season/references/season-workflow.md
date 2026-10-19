# Season production workflow

A season project contains `sourcedata/<cyclone>/`, `build/`, and `output/`.
Each cyclone needs at least one valid path of any supported type. TC.txt is optional.
All passes read current source data. Use [track data](../../references/track-data.md)
for unified/sparse types, interleaved files and UTC format; use
[pipeline](season-pipeline.md) for file formats and output paths.

## Stages

| Stage | Tool | Result |
|---|---|---|
| Inspect and preview | `preview season` / `season-overview info` | Full-season and per-storm PNGs |
| Interactive tuning, optional | `preview html` | Offline map/heat/track controls and parameter export |
| Plate | `season-plate season-info` then `season-render` | Fixed-camera tracks, icons, effects and sound |
| Camera edit, optional | External editor | Cut/zoom over the plate without changing time correspondence |
| Cards | `season-cards info`, `preview`, then `render` | Five season readouts and timeline over a base |

The compiled commands live in `bin/typhoon/typhoon.exe`; source counterparts are
`scripts/track_preview.py`, `season/scripts/season_pass1.py`, and `season_pass2.py`.
`season_overview.py` is a compatibility adapter to the independent preview script.
Examples of the complete commands are in [season/SKILL](../SKILL.md).

## Preview and map

Follow the [static preview contract](../../references/preview.md): original world-map
pixel density, map → 40% ACE heat → opaque pure-colour paths, no dark path outline,
and map/black/transparent × both/track/heat options. The basin is chosen from all
storms and used consistently; individual crops use the approved framing rules.
Calculate all-season peak before filtering, round half up to 0.01 and share it
across independently calculated storm fields. Keep only an unlabelled colour bar.
More calculation and HTML options: [ACE](ace-density.md), [HTML](ace-density-html.md).

Map metadata is `assets/SMCY1.3/map/basins.json`; source pixels are from
`map/basins/EARTH.png` at 21600×10800, 60 pixels/degree. Labels and graticule are
already baked in. Basin metadata chooses framing, not a separate lower-resolution
image for the approved static preview. Static and video camera policies are distinct;
do not change animation framing to match a still without an explicit request.

## Plate

Run info and inspect time blocks, storm order, source span, ACE and expected frame
count. The released season calendar/title/month markers target 2020 WP; adapt them
for a different year or basin. Preserve the time-warp and effect timings in the
[style specification](season-style-spec.md). Explicitly set video size/fps for
plate and cards; standard delivery examples use 1920×1080/120 fps. Plate defaults
21600×10800/60 fps, cards 1920×1080/60 fps.

For a short test, select `--from`, `--to`, `--limit` and optionally `--audio 0`. Put diagnostic outputs in build.
The plate contains no timeline, opening, HUD or seasonal summary cards. Shared
icons/effects are cached beside the source pack and reused across storms.

## Edit and data layer

Card compositing reads frame index and must match the plate time axis. Optional
camera edits may change framing but must preserve total duration and time mapping.
Use `--base black`, `--base map`, or a project-relative video path. Card definitions,
statistics, digit formatting and layout are specified in
[card models](season-cards.md); inspect an actual composited frame before export.
Use bundled Saira and Source Han Sans SC; retain tabular digit placement.

## Files and delivery

`--season` defaults to the current directory. Relative assets/output/cache/video
overrides resolve from the selected project; built-in defaults resolve from the
skill. Optional Chinese names live in `build/season_names.txt`. Generated logs,
helper scripts and intermediate frames go directly in build; final PNG/HTML/MP4
go in output. Verify final streams and output timing, and keep user source data
unchanged. See parent [SKILL](../../SKILL.md) for working-file and synchronization rules.
