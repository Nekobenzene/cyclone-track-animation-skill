---
name: typhoon-track-animation-season
description: Render a WHOLE tropical-cyclone season as an SMCY1.3-style animation - one fixed basin camera, every storm's intensity-coloured track, spinning category icons and motion effects on one continuous map, driven by a season folder of best-track text files and the SMCY1.3 asset pack. Also produces the still overviews (one whole-season sheet plus one per storm) and the data cards - the five season read-outs and the timeline composited over a finished cut as a separate pass.
---

# Season

Each cyclone needs at least one valid path segment of any supported phase (DB, TC, RV or EX); TC.txt is not mandatory. This skill is usable by any agent with filesystem and command execution capabilities.

Renders a whole season, start to finish, from a folder of per-storm best-track
text files. One process drives every storm, so the map, the camera, the time warp
and the style are shared by all of them.

    season/
      SKILL.md
      scripts/season_pass1.py       the plate: the whole season as one video
      scripts/season_pass2.py       the cards: the data layer, over a plate
      scripts/season_overview.py    the stills: overview.png + one per storm
      examples/2020.md              a season's own quirks, in prose
      references/season-workflow.md the rule book - read before changing anything
      references/season-pipeline.md data -> stills -> plate -> edit -> cards
      references/season-cards.md    what pass 2 is: cards, models, formats, traps
      references/season-style-spec.md the frozen look: time warp, framing, sizes

## The three scripts

`season_pass1.py` renders **the plate** - the season as one continuous video.
Tracks, icons and the four motion effects, and nothing else. There is
deliberately no timeline, no data card, no HUD, no intro and no summary: this is
the layer the camera is cut on, and the numbers go over it later.

    python scripts/season_pass1.py season-info
    python scripts/season_pass1.py season-render
    python scripts/season_pass1.py season-render --size 960x540 --fps 30
    python scripts/season_pass1.py season-render --from 2020-10-26 --to 2020-11-02

`season_pass2.py` renders **the cards** - five season read-outs and a timeline,
composited over a base it did not draw. The base is `black` for the standalone
data layer or a finished plate for the edit. **It never re-times the base**: it
reads the frame index and nothing else. Read `references/season-cards.md` before
touching it - the card models and number formats are contracts.

    python scripts/season_pass2.py info
    python scripts/season_pass2.py preview --base black --size 1920x1080 --at 2020-11-01
    python scripts/season_pass2.py render  --base black --size 960x540 --fps 30 --out x.mp4
    python scripts/season_pass2.py render  --base <plate>.mp4 --size 8534x4800 --fps 120

`season_overview.py` renders **the stills** - one sheet for the whole season
plus one per storm, all from the same map.

    python scripts/season_overview.py all
    python scripts/season_overview.py overview
    python scripts/season_overview.py storms

`info` prints the numbers a run will use (which basin won, the window, each
storm's screen second, the activity blocks, the frame count). Read it before a
long render.

## Which folder does what

`single/` renders ONE storm with a follow camera. This folder renders a whole
season on a fixed camera. They share the asset pack and the visual language but
**no code** - each folder carries its own scripts, references and examples, and
none of them points into another. If a helper is needed on both sides, copy it.

## Notes

* The style is the contract. `references/season-style-spec.md` and the rules in
  `references/season-workflow.md` win over any local improvement.
* All three scripts must stay self-contained. `season_overview.py` reads
  `season_pass1.py` beside it for the basin rule and the trail, and that is the
  only cross-file read allowed - it is deliberate, so the stills cannot drift
  from the animation.
* The map is `map/basins/` and only `map/basins/`. Everything else under
  `SMCY1.3/map/` is superseded; see the workflow book.
* `gui/ace/ace_color_1000.png` is read by **both** passes - pass 2's ACE ruler
  and pass 1's per-storm ACE bar. Replacing it changes both, so a plate rendered
  before the replacement and cards rendered after it will show two different
  ramps in one film.

## Project paths

Season projects live at `<work>/season/<YearBasin>/`; shared assets are
`../assets/SMCY1.3` in the parent skill by default; its shared cache is
`../assets/_cache`. All three scripts load dependencies and FFmpeg from
`../runtime/`. Explicit asset overrides remain supported. All three scripts default to the current directory as the season project.
Use `--season <relative-or-absolute-project>` when launching elsewhere; relative
project paths resolve from the launch directory. Explicit relative `--assets`
and `--out` paths resolve from the selected season project; pass 1 also supports
`--cache` on that basis. Pass 2 relative `--base` file paths resolve from the
project (the `black` and `map` keywords remain unchanged). Shared defaults
resolve from the installed skill location. No script requires a named work
folder or editing project constants. This path update does not change the
existing season timeline/year rules.

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
