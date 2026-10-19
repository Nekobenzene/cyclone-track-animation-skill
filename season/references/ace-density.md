# ACE density on overview tracks

This optional preview reads current `sourcedata/` and overlays a smooth ACE field
on the existing season and individual storm track overviews. Run from the skill root:

```text
python season/scripts/season_overview.py ace-density --season <project>
python season/scripts/season_overview.py all --season <project> --heat
python season/scripts/season_overview.py storms --season <project> --heat --only 22
```

The ordinary `all`, `overview` and `storms` commands default to path plus heat.
Use `--layers track` for plain tracks or `--layers heat` for heat alone. `ace-density` produces the full season and
all individual storm overviews with heat. Default heat output uses the native EARTH map density (60 pixels/degree):
2020WP is 8535×4800 for its existing basin crop. `--size native` selects this
explicitly; `--size WxH` overrides it. All static products default to native density.

## Calculation and shared scale

Only TC fixes at >=34 kt contribute ACE, using the renderer's six-hour samples,
raw intensity interpolation and ACE end time. Each contribution is distributed
on its continuous TC track, with boundaries clipped at start/end and phase changes.
Bilinear deposition, separable Gaussian convolution and scalar interpolation
produce continuous pixel colours, in ACE per square degree. No physical-area or
sea/land correction is applied. The original 1° cells remain the statistical unit,
not visible colour blocks.

Defaults selected on 2020WP: sigma 3°, radius 15° per axis, 30-minute samples,
960-pixel-wide scalar field, opacity 0.4. The heat uses the authored RGBA ramp in
`gui/ace_heat.png`, composited below the overview paths; pure-colour paths are drawn last.

Calculate the full season field before filtering storms. Round its actual peak
half up to 0.01 and use that SAME maximum for every image. A zero or very small
peak uses 0.01 to avoid division by zero. Each individual storm field is calculated
independently using only its own ACE contributions; never normalize a storm by
its own maximum and never crop the full season heat for a storm image.
Thus lower-ACE storms generally appear much lighter. Values above the rounded
maximum use the top colour without changing the underlying field.

Images contain only the unlabelled colour column: no numeric ticks, scale values,
diagnostic title or panel. The upper limit and peaks remain available in JSON.

## Parameters and output

Use the [offline HTML tuner](ace-density-html.md) for live adjustments.
A saved settings file can drive production output:

```text
python season/scripts/season_overview.py ace-density --season <project> --heat-parameters <parameters.json>
```

Alternatively use `--heat-sigma`, `--heat-radius`, `--heat-step`,
`--heat-field-width`, `--heat-opacity`, `--heat-max` (0 = automatic full season peak).
Manual maxima are also rounded to 0.01. With a settings JSON its corresponding
values take precedence over command defaults. Normal framing and size flags apply.

Outputs go to `<project>/output/overview/`: `overview.png`, `NNW.png`, and
`ace_density.json` containing the shared maximum, season peak, settings, and each
image's independently calculated peak and ACE integral. `--only` filters individual
outputs, never the season reference maximum. Agent logs and intermediates go in
`<project>/build/`. The compiled `preview season` command uses the same implementation.
