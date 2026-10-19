# Single rendering performance

## Caches

The self-contained renderer has an LRU font cache (128 entries), exact-time
sample cache (8192 entries), trail position/colour cache (4096 entries), and a
settled static HUD cache. Time keys are not rounded; retain the original
0.8-hour trail stepping and curve geometry. Rebuild clears storm-dependent
sample/trail caches. These changes preserve the composition.

BannerFrames retains paths and decodes/tints frames on demand through a
32 MiB decoded RGB pixel cache. This is a pixel budget, not a process-memory
limit. Cached frames are copied for callers. The world map still decodes
in full, and map/preview loading still has a substantial transient peak.

## Sustained audio

`intensity_intervals(threshold)` solves crossings separately within each
monotone wind-curve knot interval. Each >=113 kt run gets its own C4+ bed;
each >=170 kt run gets its own extreme bed. Never span from the first rising
crossing to the last falling crossing across multiple peaks. Starts/ends
already above threshold and equality plateaus are included. Keep existing
gains and fade-in/out inside each run. Existing WAV/MP4 files require audio
regeneration/muxing to receive this fix.

Run `python -m unittest discover -s tests -p test_audio_intervals.py` for seven regression scenarios,
including multi-peak dips and threshold plateaus.

## Validation

For changes to rendering internals, compare representative original/optimized
RGB frames, including HUD entrance, main track, pull-back and panorama. For
landfall-size changes use the current style formula rather than requiring
old impact pixels. Confirm exports with ffprobe: dimensions, 120/1 fps,
frame count, adaptive duration and AAC audio. A sampled drawing benchmark
does not measure full-render throughput or FFmpeg encoding time.

Export dimensions are independent of the 1920x1080 composition; alternate
positive even dimensions are Lanczos-scaled during encoding. Increasing
export size does not add map or native UI detail.

## Preview frame rates and landfall tint

Set `output.fps: 30` with `output.width: 960` and `output.height: 540` for a
540p30 full-film preview. Output fps accepts integers 1..120 and defaults to
120. Frames sample the existing 120 fps author timeline, preserving camera
smoothing and effect duration; the preview does not resimulate at 30 fps.

Landfall impact tint follows the icon's `icon_tint_colour` rule: C5 and below
keep the authored colour; C5+/C5++ use `theme_col` quantized down to multiples
of 8 and the existing HSV hue-replacement algorithm. White cores are retained.
The target colour uses intensity at landfall, not the later display-frame
intensity. It stays fixed during the 1 s impact. Tint uses the bounded asset
cache; it adds no separate glow and does not alter persistent Landed markers.
