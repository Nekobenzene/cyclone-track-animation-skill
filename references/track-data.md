# Path data and type transitions

## Disturbance and subtropical paths

`DB.txt`, `DB-LO.txt` and `DB-aL.txt` select the tropical disturbance aL art.
`MV.txt` / `DB-MV.txt` select tropical wave art (asset aWV);
`MD.txt` / `DB-MD.txt` select monsoon
depression art (asset MD). `SD.txt` and `SS.txt` are subtropical paths: the
current interpolated wind selects SD below 34 kt and SS at or above 34 kt,
regardless of which of these two filenames contains the fix. These filename
subtypes also apply to explicit `data.series` entries. All detected segments
are merged by timestamp. Avoid duplicate fixes across files at the same time.

The icon uses the N series at latitude >= 0 and the S series at latitude < 0,
evaluated at the current path position. Extracted S frames occupy separate
shared-cache folders and are created when the path reaches the southern hemisphere.
The SS upgrade effect takes its yellow-green chroma from the SS icon while
retaining white highlights. ACE includes TC fixes only. See the upgrade trigger
rule below: entering TS/SS from EX is supported; remaining EX is not an upgrade.

## Unified track.txt (optional)

Prefer `sourcedata/track.txt` for a storm that repeatedly changes type. When
present it takes precedence over legacy phase files and `data.series`, so old
files do not double-load. Without it, the original multi-file workflow remains.
The first five whitespace-separated columns remain UTC timestamp, longitude,
latitude, wind (kt), pressure (hPa). A sixth column specifies the type:
`DB`, `MV`, `MD`, `TC`, `RV`, `EX`, or `ST` (subtropical). `SD`/`SS` are also
accepted as subtropical types; displayed SD/SS still follows the 34 kt boundary.
`DB-LO`/`DB-aL`, `DB-MV`, `DB-MD` are accepted aliases. Explicit TD/TS/C1–C5++
normalize to TC, with the displayed grade derived from wind.

Either give the type on every row, or give it on the first row and only when it
changes. An omitted sixth column inherits the last specified type in that file.
The first unified row must specify its type. The type takes effect at that row's
UTC time. Existing five-column phase files retain their filename default; they
can also use the optional sixth column. TC-only ACE uses the effective row type,
including all TC stretches separated by RV or other stages. Identical duplicate
fixes are merged; conflicting values/types at one timestamp are rejected.

```text
20260101000000 140 15 20 1005 DB
20260101060000 140 15 30 1002 TC
20260101120000 140 15 25 1005 RV
20260101180000 140 15 30 1002 TC
20260102000000 140 15 35 1000
```

Legacy phase files may have gaps and interleave in time: TC.txt can contain 00Z
on two consecutive days while RV.txt contains 06Z/12Z/18Z between them. The
merged sequence is TC/RV/RV/RV/TC, not an uninterrupted TC interval. ACE follows
the merged point types. Do not duplicate a timestamp with conflicting types.

`MV.txt` / `MD.txt` are also accepted directly, equivalent to `DB-MV.txt` / `DB-MD.txt`.

Upgrade FX trigger: play whenever a strengthening storm enters the displayed TS
or SS class, regardless of its previous type. This includes changing from DB,
MV, MD, RV or EX after the wind has already passed 34 kt. Wind crossings and
phase changes both contribute event candidates; repeated upgrades are retained.
A weakening or steady-wind type change does not trigger the upgrade. Animation
and sound use the same event list; SS keeps its yellow-green effect colour.

