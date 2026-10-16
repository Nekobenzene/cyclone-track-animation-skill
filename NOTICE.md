# Third-party notices

The **source code** of this repository is licensed under the MIT License (see
`LICENSE`). That license covers the code in `single/`, `season/`, `scripts/` and
`tools/` only. It does **not** cover the SMCY1.3 asset pack, the bundled runtime
or the fonts, which are distributed separately as GitHub Release attachments and
remain under their own terms.

## Fonts

| Font | Files | License |
|---|---|---|
| Source Han Sans SC | `assets/SMCY1.3/font/SourceHanSansSC/` | SIL Open Font License 1.1 (`LICENSE.txt` is bundled in that folder) |
| Saira | `assets/SMCY1.3/font/_saira_master/` | SIL Open Font License 1.1 |

Official download URLs and SHA-256 hashes for Source Han Sans SC are recorded in
`assets/SMCY1.3/font/SourceHanSansSC/source.json`, so the font can also be
fetched from Adobe's own release instead of from this repository.

The OFL requires that the license text and copyright notice travel with the
font files. Do not remove `LICENSE.txt` from either font folder when
redistributing, and do not sell the fonts on their own.

## FFmpeg / FFprobe

`runtime/bin/ffmpeg.exe` and `runtime/bin/ffprobe.exe` are the
`ffmpeg-9.0.1-full_build` binaries from gyan.dev, a GPL (`--enable-gpl
--enable-version3`) build. They are redistributed here unmodified, as build
inputs of the rendering pipeline.

* Upstream project: <https://ffmpeg.org/>
* Build provider: <https://www.gyan.dev/ffmpeg/builds/>
* Corresponding source for the binaries as shipped: obtain it from the build
  provider's source page, or from <https://ffmpeg.org/download.html>

If you prefer not to redistribute FFmpeg, delete `runtime/bin/` from the release
pack you publish and have `tools/build_runtime.py` fetch a build from upstream
instead.

## Python runtime libraries

`runtime/python/` contains unmodified wheels from PyPI:

| Package | Version | License |
|---|---|---|
| NumPy | 2.3.5 | BSD-3-Clause |
| Pillow | 12.3.0 | MIT-CMU |
| opencv-python-headless | 5.0.0.93 | Apache-2.0 (OpenCV 4.x/5.x) |
| PyYAML | 6.0.3 | MIT |

Each package keeps its own license metadata inside its `*.dist-info` folder.

## Map and effect artwork

`assets/SMCY1.3/` contains the map sheets, category icons, landfall effects,
particles, GUI plates and sound effects used by both renderers, plus the
optional geographic data in `assets/geo/`. These are compiled artwork; the
repository does not relicense them. Anyone republishing a release pack is
responsible for confirming their own right to redistribute that artwork.

`assets/geo/` is an optional preprocessing package. It bundles GeoNames place
data (`cities500.txt`, `cities500.zip`) — GeoNames is published under
CC BY 4.0 (<https://www.geonames.org/legal/>) — plus simplified country
outlines whose upstream archive (`shapes.json.zip`) is bundled alongside the
derived `shapes_simplified_low.json`. Attribute GeoNames if you redistribute
that package, and re-check the outline source before publishing it widely.
