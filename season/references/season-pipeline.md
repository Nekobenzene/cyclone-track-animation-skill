# Season pipeline

What goes in, what comes out, and which stage owns it. Read with
`season-workflow.md`, which carries the rules; this file carries the plumbing.

---

## The chain

    sourcedata/                     stage 1  hand-filled best-track text
        |
        +--> season_overview.py     stage 2  overview.png + NNW.png
        |
        +--> season_pass1.py        stage 4  the plate (one silent-then-muxed mp4)
                    |
                    v
              edited plate          stage 5  by hand, outside this folder
                    |
                    v
              season_pass2.py       stage 6  the cards + timeline, over the plate
                                             (or over `black`, standalone)

Stages 2, 4 and 6 are independent of each other and all read `sourcedata/`
directly. Stage 3 (`examples/<year>.md`) is read by a human and changes what the
scripts are asked to do; it is not parsed.

Stage 6 reads the frame index and nothing else, so it can run before or after
stage 5 without knowing which: `--base black` gives the data layer alone,
`--base <cut>.mp4` lays it over the finished cut. **Stage 5 must not change the
duration**, because stage 6's timeline is pinned to the frame clock.

## Folder layout a season is expected to have

    <season>/                       e.g. work/season/2020WP
      Overview.xlsx                 the operator's own tally - not read by anything here
      sourcedata/
        INDEX.txt                   one line per storm
        WP01_Vongfong/              one directory per storm, named NN_Name
          Num.txt TC.txt DB.txt RV.txt EX.txt
          hypo.txt landfall.txt damage.txt
      build/                        work area
        tmp/                        scratch and audio
        pass1_backups/              optional rollback copies of the scripts
        render_*.log                render logs
      output/                       finished products
        overview/                   stage 2 stills
        *.mp4                       stage 4 plates

The scripts never write into `sourcedata/`. Stage 1 is the operator's, and a
render must not be able to corrupt it.

## Path binding

All three scripts resolve the season from a folder, not from a config file.
Shared assets are at `<work>/res/SMCY1.3`, cache at `<work>/res/_cache`:

    season_pass1.py    SEASON_ROOT / SEASON_ASSETS / SEASON_CACHE constants near
                       the top of Section B
    season_overview.py --season / --assets / --out
    season_pass2.py    --season / --assets / --out

Overview and pass 2 default to `<work>/season/2020WP` and
`<work>/res/SMCY1.3`; pass 1 constants use those same paths.

`_bind_paths()` also derives a shared cache beside the asset pack
(`<pack>/../_cache`), not inside it: `SMCY1.3` is the read-only source of truth
and must not accumulate derived frames. Extracted icons and effect clips live
there and are reused across storms and across runs.

## The asset pack

`SMCY1.3/` is read-only and shared by every folder of this skill.

| path | what it is | used by |
|---|---|---|
| `map/basins.json` | each sheet's window and size | both pass 1 scripts |
| `map/basins/*.png` | the only map source | both pass 1 scripts |
| `mainicon/` | the spinning category art | pass 1 |
| `landfall/` | impact clips and the landfall sounds | pass 1 |
| `particle/` | `note_ts` upgrade flash, `ERI.gif` | pass 1 |
| `sound/random/` | ERI, 170 kt and category-4 beds, upgrade note | pass 1 |
| `summary/` | the summary banner art | pass 2's per-storm summary banner |
| `timeline/` | month strips and ACE point clips | not used by the scripts |
| `font/` | Saira, plus the CJK faces the labels need | all three scripts |
| `gui/ace/ace_color_1000.png` | the ACE colour ramp | pass 1's ACE bar **and** pass 2's ruler |
| `mainicon/tc_sshws/N-TC-*.mp4` | the intensity icons, as video | the SOURCE OF the tally colours |
| `resources/acerate.png` | the ACE-rate colour ramp | pass 2, but read as a node table, not as a bitmap |

Nothing under `map/` other than `basins/` may be read. See the workflow book for
why.

Two of the pass 2 entries deserve a note. `gui/ace/ace_color_1000.png` is shared
with pass 1, so replacing it changes both passes and a plate rendered before the
replacement will not match cards rendered after it. And `resources/acerate.png` is
read as 14 fixed colour nodes with linear interpolation, not sampled as a bitmap:
sampling would tie the ramp to the strip's 776-row length and to PNG quantisation,
whereas the nodes are the design.

## Products

### Stage 2 - `season_overview.py`

    output/overview/overview.png     1920x1080 by default
    output/overview/NNW.png          one per storm, JTWC-numbered

`--size` changes both. `--ss` supersamples the map crop; a wide crop benefits,
a narrow one does not need it.

### Stage 4 - `season_pass1.py`

    output/season_pass1_<from>_<to>_<W>x<H>_<fps>fps.mp4

or whatever `--out` says. The video is written silent first, then the effects
audio is built and muxed in, so the file changes size twice. `--audio 0` stops
after the silent pass.

### Stage 6 - `season_pass2.py`

    output/season_pass2_<base>_<W>x<H>_<fps>fps.mp4     or whatever --out says

The data layer is drawn on its own canvas and composited over the base, so its
per-frame cost does not depend on the output size: `render_w` is
`min(3840, max(1920, W))` and at an 8534-wide output the layer is drawn at 3840
and upscaled 2.22x. That upscale was checked at 1:1 and at 2-3x zoom and is not
visible; rendering natively at 8K costs 177 ms/frame against 29 ms and 16K costs
1033 ms, so the cap is what keeps 16K possible at all.

The cards, their models and their number formats are in
`season-cards.md`; the frozen constants are in `season-style-spec.md` §11.

An earlier `season_pass2.py` was lost and only its bytecode survived. It has since
been rebuilt from that bytecode's own constants, and the rebuilt source is now what
this folder ships. **The old bytecode is kept only as the historical record**, under
a name Python never loads:

    scripts/__pycache__/season_pass2.original-20261009.pyc   the lost original (source size 228298)
    scripts/__pycache__/season_pass2.cpython-310.pyc         the CURRENT build, in step with the .py

Every `__pycache__` entry under this skill is a plain cache of the `.py` beside it
and is rebuilt with `python -m py_compile <script>` after a source change; the
`original-*` file is the one entry that is data rather than cache.

## Timing a render before committing

`info` first - it prints the basin, the window, the per-storm screen seconds, the
activity blocks and the exact frame count, without rendering anything.

Then a real one-frame or few-frame run at the candidate size:

    python scripts/season_pass1.py season-render --size 8534x4800 --fps 120 \
        --from 2020-10-28 --to 2020-11-01 --limit 1 --audio 0 --out <tmp>.mp4

Pick a window in the **densest** part of the season for this. A quiet-stretch
sample runs an order of magnitude faster and gives a useless estimate.

## Logs

Long renders should be redirected to a file, because the progress line is the
only way to know the run is alive:

    1/34661  0.0%  4.50 fps  eta 2:08:16

`python -u` matters: without it the pipe buffers and the log stays empty for
minutes at a time, which looks like a hang.
