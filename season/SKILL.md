---
name: typhoon-track-animation-season
description: Render a whole cyclone season as an SMCY1.3 fixed-camera animation plate, separate data-card/timeline pass, and native-resolution track/ACE heat overviews with interactive HTML tuning.
---

# Season

Read the parent [SKILL](../SKILL.md) for shared resources and working-file rules.
Prepare `sourcedata/<cyclone>/` per cyclone, with at least one valid track of any
type. TC.txt is optional. Follow [track data](../references/track-data.md).
Commands below are relative to the skill root and read current source tables.

## Workflow

1. Inspect and preview all paths:

   ```text
   bin/typhoon/typhoon.exe season-overview info --season <project>
   bin/typhoon/typhoon.exe preview season <project>
   bin/typhoon/typhoon.exe preview html <project>
   ```

2. Render the animation plate:

   ```text
   bin/typhoon/typhoon.exe season-plate season-info --season <project> --size 1920x1080 --fps 120
   bin/typhoon/typhoon.exe season-plate season-render --season <project> --size 1920x1080 --fps 120
   ```

3. Optionally edit camera moves while preserving duration and timing; then overlay cards:

   ```text
   bin/typhoon/typhoon.exe season-cards info --season <project> --size 1920x1080 --fps 120
   bin/typhoon/typhoon.exe season-cards render --season <project> --base output/edited_plate.mp4 --size 1920x1080 --fps 120 --out output/season_final.mp4
   ```

Source alternatives are `season/scripts/season_overview.py`, `season_pass1.py`
and `season_pass2.py`. The overview is an adapter to `scripts/track_preview.py`.
Plate contains tracks, icons, effects and sound; cards contain statistics and the
timeline over a map, black background or existing video. Card compositing uses the
frame index, so edited video must retain the plate's time correspondence.

The current season animation calendar/title/month marks target **2020 WP**.
Adapt those definitions for other seasons; `--season` selects the data directory.
Always specify video size/fps: plate defaults 21600×10800/60, cards 1920×1080/60.
Static previews default to native map density and have a separate size option.

## References

- [Static preview](../references/preview.md): map/black/transparent × both/track/heat,
  pure opaque paths above 40% heat, original map density, independent per-storm fields
  and one rounded season-wide scale. Black preview and HTML tuning are optional.
- [HTML parameters](references/ace-density-html.md) and [ACE calculation](references/ace-density.md).
- [Production workflow](references/season-workflow.md), [pipeline](references/season-pipeline.md),
  [card models](references/season-cards.md), [visual specification](references/season-style-spec.md).
- [Extreme intensity rules](../references/extreme-intensity.md): colours and halo to
  500 kt, dark-red numeral above 185 kt, landfall impact size capped at 200 kt.

Relative `--assets`, `--out`, plate `--cache` and video `--base` resolve from the
selected project; default resources resolve from the installed skill. Keep custom
names in `build/season_names.txt`. Preserve bundled Saira and Source Han Sans SC
font routing and data-card digit placement. Each pass reads source data independently;
static previews reuse data/colour definitions without launching effect extraction.
