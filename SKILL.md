---
name: typhoon-track-animation
description: Create SMCY1.3-style cyclone animations and static track/ACE heat previews from best-track data. Use single for one cyclone with a follow camera, season for a whole basin season with a fixed camera and separate data cards, or the standalone preview for PNG and interactive HTML output.
---

# Cyclone track animation

Use this skill's installed scripts and shared assets; keep project data outside the skill.
Any agent with file and terminal access can use it. Read [README](README.md) for setup,
project structure and the complete workflow, then only the mode-specific instructions needed:

| Task | Read | Compiled entry |
|---|---|---|
| One cyclone animation | [single/SKILL.md](single/SKILL.md) | `typhoon.exe single <project> <command>` |
| Whole-season plate and data cards | [season/SKILL.md](season/SKILL.md) | `typhoon.exe season-plate` / `season-cards` |
| Static map, black or transparent preview; ACE heat; offline HTML | [references/preview.md](references/preview.md) | `typhoon.exe preview single|season|html <project>` |
| VIS_CLEAN crop, background removal, feathering and screen clips | [references/vis-clean.md](references/vis-clean.md) | `typhoon.exe vis-clean tune|preview|export <project>` |
| Direct cloud video overlay while rendering single | [references/cloud-video.md](references/cloud-video.md) | `typhoon.exe cloud-video configure|preview|probe <project>` |
| Source edits, rebuilding and publishing | [PUBLISHING.md](PUBLISHING.md) | `typhoon.exe build-exe` / maintenance modes |

The executable is `<skill>/bin/typhoon/typhoon.exe`. Source alternatives remain available.
Install shared resources using [DOWNLOAD.md](DOWNLOAD.md) after a Git clone.

## Inputs and resources

Each cyclone needs **at least one valid track of any supported type**; `TC.txt` is optional.
Use `sourcedata/track.txt` with a full or sparse sixth-column type, or legacy per-type
files, including interleaved times. Read [track data](references/track-data.md) for
types, timestamps, duplicate handling, TS/SS transitions and trail rules.
Read current `sourcedata/`, never a stale build snapshot.

Shared resources resolve relative to the skill:

```text
<skill>/assets/SMCY1.3/     maps, icons, effects, Saira and Source Han Sans SC
<skill>/assets/_cache/     generated media cache
<skill>/assets/geo/        optional geographic preprocessing data
<skill>/runtime/python/   source-mode dependencies, Windows x64 CPython 3.12
<skill>/runtime/bin/      FFmpeg and FFprobe
<skill>/bin/typhoon/      compiled tools and bundled Python interpreter
```

Projects use `sourcedata/`, `build/`, and `output/`. A season has one cyclone folder
per `sourcedata/` child. Project location is arbitrary; explicit asset/cache overrides
remain supported. Single YAML paths are relative to the YAML or project as described
in README. Preserve existing user configs and data.

## Agent working files

Create `<project>/build/` before producing working files. Put tool stdout/stderr,
render/probe logs, helper scripts, scratch configs, diagnostic reports, test frames
and all intermediates directly there from the outset, including background and failed
runs. Use explicit output paths; run tools from build if their output is relative to
the current directory. Do not temporarily scatter files in the project root.
Keep final deliverables in `output/`, source inputs in `sourcedata/`, and shared
extracted media in the configured shared cache.

## Rendering contracts

Single video standard: **1920×1080 / 120 fps**. Static previews use the original world
map's pixel density. Two independent preview choices are `--background map|black|transparent`
and `--layers both|track|heat`; default map + both. Black previews are optional and
can be invoked at any time. Follow the complete [preview standard](references/preview.md)
for opaque pure-colour paths above 40% ACE heat, unlabelled colour bars, shared season
scale and independent storm calculations.

Use bundled Saira for English/digits and Source Han Sans SC for Chinese. Retain font
licenses. Preserve animation composition and timing unless the user requests changes.
ACE counts only qualifying TC samples. [Extreme intensity rules](references/extreme-intensity.md)
cover 200–500 kt colour, halo and the 200 kt landfall size cap.

## Editing and synchronization

Edit a working copy rather than the installed skill. Animation implementations live
in single/season; static compositing lives in `scripts/track_preview.py`, reused by
the original preview commands. Keep source and compiled entry behaviour consistent.
Run relevant tests, rebuild after source edits, and verify compiled commands before
distribution. Rebuilding requires external Windows x64 Python 3.12 with pip; normal
compiled rendering does not. See [publishing](PUBLISHING.md).

Once the installed skill and remote are synchronized and verified, temporary skill
copies in the work directory can be removed. First remove directory links themselves;
preserve their shared targets and all user projects, source data and deliverables.
