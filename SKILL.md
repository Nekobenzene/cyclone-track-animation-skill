---
name: typhoon-track-animation
description: SMCY1.3-style tropical-cyclone animations in independent folders that share one asset pack and no code. Use single/ to animate ONE storm - follow camera, intensity-coloured track, spinning category icons, ACE bar, damage pop-ups, pulled-back panorama and summary card. Use a season folder to animate a WHOLE typhoon season across one basin - every storm on a fixed world camera with the season's time warp, its tracks, icons and effects, and the season's data composited over it. Read only the folder you need; no folder imports another.
---

# Typhoon track animation

使用者和各类 agent 请先阅读 [README.md](README.md)：共享目录、路径数据格式及 single/season 完整制作流程。每个气旋至少提供一份任意阶段的有效路径，TC.txt 并非必需。

| folder | what it renders | start here |
|---|---|---|
| `single/` | one storm: follow camera, intensity-coloured track, animated category icons, ACE bar, damage pop-ups, panorama, summary banner | `single/SKILL.md` |
| `season/` | a whole season: every storm on a fixed world camera with the season's time warp, its tracks, icons and effects, and the season's data | `season/SKILL.md` |

Every folder reads the same **SMCY1.3 asset pack** (map sources, icons, landfall fx,
sfx, fonts) and all of them reproduce the same frozen visual language, but they
share **no code**: each folder carries its own scripts, references and examples,
and neither imports code from the other. Both read parent-level resources.

## Workspace paths

The project workspace is separate from this installed skill. Its current layout is:

```text
<work>/
  single/<Storm>/{sourcedata,build,output}/
  season/<YearBasin>/{sourcedata,build,output}/
  res/SMCY1.3/    shared source assets (read-only)
  res/_cache/     shared extracted icons and effects
```

Here `<work>` is `C:\Users\tangtang\Desktop\work`. Paths such as
`single/scripts/` and `season/references/` in this skill refer to the installed
skill, not the project directories with the same names. Resolve projects under
the workspace and scripts under this skill's actual installation directory.
Asset-relative paths such as `SMCY1.3/map/` default to this skill's `assets/SMCY1.3/map/`; existing workspace asset overrides remain supported.
Keep each project's inputs, build files and outputs inside that project;
use `<work>/res/_cache` for shared extracted media.

## Bundled resources shared by single and season

```text
typhoon-track-animation/
  assets/SMCY1.3/     complete shared read-only source asset pack
  assets/geo/        optional geographic data and helpers
  assets/_cache/     derived shared media cache (created on demand)
  runtime/python/    NumPy, Pillow, OpenCV and PyYAML
  runtime/bin/       FFmpeg and FFprobe
  runtime/platform.json
  single/scripts/
  season/scripts/
```

Both renderers use this shared runtime automatically, without importing each
other's code. New single projects default to the bundled asset pack through
`single/scripts/launch.py`; all season scripts default to the same pack.
Existing project YAML asset paths remain authoritative. Workspace res assets
remain supported as explicit overrides. Runtime targets Windows x64 Python 3.12;
the interpreter itself remains external.

## Bundled Chinese font routing

Chinese text uses Source Han Sans SC from parent-skill
`assets/SMCY1.3/font/SourceHanSansSC/`: Regular for body text, Medium for
secondary labels where provided, Bold for emphasized labels and banners.
English/digits remain Saira. Neither renderer requires Microsoft YaHei or
Windows font paths. The original Adobe SIL OFL 1.1 license is bundled as
`LICENSE.txt`; retain it and font copyright notices when distributing.
Official download URLs and SHA-256 hashes are recorded in `source.json`.
Font paths are anchored to the skill, independent of project asset overrides.

## Windows executable and editable sources

`bin/typhoon/typhoon.exe` packages the Python interpreter and renderer code for
Windows x64. Keep its entire directory (including `_internal/`) plus the shared
`assets/` and `runtime/bin/` directories in the skill layout. No system Python
is needed for the executable. The external `runtime/python/` remains for source
execution; the frozen executable uses its own packaged Python libraries.

```text
bin/typhoon/typhoon.exe check
bin/typhoon/typhoon.exe single <project> info
bin/typhoon/typhoon.exe single <project> all
bin/typhoon/typhoon.exe single-config --config <project-yaml> all
bin/typhoon/typhoon.exe season-plate season-info --season <project>
bin/typhoon/typhoon.exe season-cards info --season <project>
bin/typhoon/typhoon.exe season-overview info --season <project>
```

All original `single/scripts/*.py` and `season/scripts/*.py` files remain the
editable sources. After modifying them, run `python scripts/build_exe.py` using
Windows x64 Python 3.12 (pip/network required for temporary PyInstaller build
tools). The build records source hashes in `bin/typhoon/source_manifest.json`.
Editing external `.py` files does not alter an already built executable; rebuild
it to apply code changes. Assets and fonts stay external and require no rebuild.
Executable packaging is for portability and does not promise faster rendering.
Do not rebuild/replace an executable directory while that executable is running.

## Optional geographic data

The former workspace `res/geo` package lives at skill `assets/geo/`. It contains
GeoNames cities/countries, simplified country outlines, derived place/seat lists,
original zip files and geographic helper scripts. It is reserved for optional
preprocessing; normal single/season rendering does not load it. No rebuild is
needed to add or change this external data.

`places.py`, `seats.py`, `outer.py`, and `landfall_rule.py` locate data relative
to their own directory. For project-facing helpers use `--season <project>`
(default current directory). `landfall_rule.py` writes damage anchors; run only
when that data update is requested. `cleanup.py` is an unchanged historical
maintenance utility with old paths; do not use it during ordinary skill runs.
