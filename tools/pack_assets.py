#!/usr/bin/env python3
"""Split an installed skill into release packs and write assets.manifest.json.

  python tools/pack_assets.py --skill <installed skill root> [--out dist] [--tag assets-v1]

The script only reads the skill: it writes zips and the manifest, and never
touches the source tree. Every zip stores skill-relative paths, so extracting a
pack at the skill root always reproduces the exact layout the renderers expect
(`assets/SMCY1.3/...`, `runtime/...`, `bin/typhoon/...`).

Coverage is enforced: any file under the packed trees that no pack claims is
reported and makes the run fail, so a new asset cannot silently be left behind.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path

# Pack -> skill-relative files/directories it owns. Order matters only for the report.
PACKS = {
    "map": ["assets/SMCY1.3/map/basins.json", "assets/SMCY1.3/map/basins"],
    "icons": ["assets/SMCY1.3/mainicon", "assets/SMCY1.3/summary"],
    "fx": [
        "assets/SMCY1.3/landfall",
        "assets/SMCY1.3/particle",
        "assets/SMCY1.3/gui",
        "assets/SMCY1.3/resources",
        "assets/SMCY1.3/intensity",
        "assets/SMCY1.3/option",
        "assets/SMCY1.3/sound",
        "assets/SMCY1.3/评分表",
        "assets/SMCY1.3/position_trucker.xlsx",
    ],
    "font": ["assets/SMCY1.3/font"],
    "legacy": [
        "assets/SMCY1.3/timeline",
        "assets/SMCY1.3/map/sources",
        "assets/SMCY1.3/map/waterwave",
        "assets/SMCY1.3/map/[GLOBAL].png",
        "assets/SMCY1.3/map/[GLOBAL].tif",
        "assets/SMCY1.3/map/[GLOBAL]_HD_10800.png",
    ],
    "geo": ["assets/geo"],
    "runtime": ["runtime/python", "runtime/bin"],
    "exe": ["bin/typhoon"],
}

# Packs installed by `fetch_assets.py` with no arguments: everything a
# source-mode render needs. The rest are opt-in.
DEFAULT_PACKS = ["map", "icons", "fx", "font", "runtime"]
OPTIONAL_PACKS = ["exe", "geo", "legacy"]

DESCRIPTIONS = {
    "map": "basin map sheets and basins.json (renderer base maps)",
    "icons": "category icon art and summary banners",
    "fx": "landfall, particle, GUI, ACE rulers, sound and intensity tables",
    "font": "Saira and Source Han Sans SC",
    "legacy": "superseded map sheets and the unused timeline clips (not needed to render)",
    "geo": "optional GeoNames / outline preprocessing data",
    "runtime": "portable CPython 3.12 libraries and FFmpeg for source-mode rendering",
    "exe": "frozen typhoon.exe with its own bundled Python",
}

# Media is already compressed; deflating it costs CPU for nothing.
STORE_EXT = {
    ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff",
    ".ogg", ".mp3", ".wav", ".zip", ".gz", ".7z", ".rar", ".otf", ".ttf", ".ttc",
    ".woff", ".woff2", ".eot", ".pyd", ".dll", ".exe", ".lib", ".npy", ".npz",
    ".xlsx", ".pkl", ".fits",
}
STORE_MIN = 4 * 1024 * 1024  # anything this big is stored even if not listed above

SKIP_DIRS = {"__pycache__", ".git"}
# .lnk are Windows shortcuts to the author's own machine and are useless to users.
SKIP_SUFFIX = {".pyc", ".pyo", ".lnk"}
SKIP_NAMES = {"desktop.ini", "Thumbs.db", ".DS_Store"}

# Small files that live inside the packed trees but belong to git, not to a pack.
GIT_TRACKED = {"runtime/platform.json", "assets.manifest.json"}


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def walk(root: Path, rel: str):
    """Yield files under a skill-relative file-or-directory spec."""
    target = root / rel
    if not target.exists():
        return
    if target.is_file():
        yield rel
        return
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if Path(name).suffix.lower() in SKIP_SUFFIX or name in SKIP_NAMES:
                continue
            yield Path(dirpath, name).relative_to(root).as_posix()


def collect(root: Path):
    """{pack: [rel paths]}, plus the orphan check over the packed trees."""
    packed: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    for pack, specs in PACKS.items():
        files = []
        for spec in specs:
            for rel in walk(root, spec):
                if rel in seen:
                    print(f"  ! {rel} claimed by both {seen[rel]} and {pack}", file=sys.stderr)
                    continue
                seen[rel] = pack
                files.append(rel)
        packed[pack] = sorted(files)

    # Orphans: files under the asset/runtime trees that no pack claims.
    orphans = []
    for top in ("assets/SMCY1.3", "assets/geo", "runtime", "bin/typhoon"):
        base = root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if Path(name).suffix.lower() in SKIP_SUFFIX or name in SKIP_NAMES:
                    continue
                rel = Path(dirpath, name).relative_to(root).as_posix()
                if rel not in seen and rel not in GIT_TRACKED:
                    orphans.append(rel)
    return packed, orphans


def write_zip(root: Path, out: Path, files: list[str], compress: bool = True):
    stored = deflated = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=9) as zf:
        for rel in files:
            src = root / rel
            store = (src.suffix.lower() in STORE_EXT) or (src.stat().st_size >= STORE_MIN)
            info = zipfile.ZipInfo.from_file(src, arcname=rel)
            info.date_time = time.localtime(src.stat().st_mtime)[:6]
            if store or not compress:
                info.compress_type = zipfile.ZIP_STORED
                stored += 1
            else:
                info.compress_type = zipfile.ZIP_DEFLATED
                deflated += 1
            info.external_attr = 0o644 << 16
            with open(src, "rb") as fh, zf.open(info, "w") as dst:
                while True:
                    block = fh.read(1 << 22)
                    if not block:
                        break
                    dst.write(block)
    return stored, deflated


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:,.1f} GB"


def main() -> int:
    here = Path(__file__).resolve().parent
    repo = here.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", default=str(repo), help="installed skill root to read (default: this repository)")
    ap.add_argument("--out", default=str(repo / "dist"), help="where to write the zips (default: <repo>/dist)")
    ap.add_argument("--manifest", default=str(repo / "assets.manifest.json"), help="manifest path to write")
    ap.add_argument("--repo", default="Nekobenzene/cyclone-track-animation-skill", help="owner/name used to build release URLs")
    ap.add_argument("--tag", default="assets-v1", help="release tag the manifest points at")
    ap.add_argument("--only", default="", help="comma-separated pack filter")
    ap.add_argument("--compress", default="1", help="1 = deflate small files, 0 = store everything")
    args = ap.parse_args()

    root = Path(args.skill).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    for required in ("single/scripts", "season/scripts", "assets/SMCY1.3"):
        if not (root / required).exists():
            print(f"error: {root} does not look like the skill root (missing {required})", file=sys.stderr)
            return 2

    wanted = [p.strip() for p in args.only.split(",") if p.strip()] or list(PACKS)
    packed, orphans = collect(root)
    if orphans:
        print("error: these files are under a packed tree but no pack claims them:", file=sys.stderr)
        for rel in orphans:
            print(f"  {rel}", file=sys.stderr)
        print("Add them to PACKS in tools/pack_assets.py and re-run.", file=sys.stderr)
        return 3

    manifest = {
        "schema": 1,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": args.repo,
        "tag": args.tag,
        "url_template": "https://github.com/{repo}/releases/download/{tag}/{file}",
        "default_packs": DEFAULT_PACKS,
        "optional_packs": OPTIONAL_PACKS,
        "packs": {},
    }

    grand_files = grand_bytes = 0
    for pack in wanted:
        files = packed.get(pack) or []
        if not files:
            print(f"  {pack}: no files found under {root} - skipped")
            continue
        size = sum((root / rel).stat().st_size for rel in files)
        print(f"  {pack}: {len(files)} files, {human(size)} - hashing")
        entries = [
            {"path": rel, "bytes": (root / rel).stat().st_size, "sha256": sha256_file(root / rel)}
            for rel in files
        ]
        zip_name = f"smcy13-{pack}.zip" if pack.startswith(("map", "icons", "fx", "font", "legacy")) else f"{pack}-win64.zip"
        if pack == "geo":
            zip_name = "geo-optional.zip"
        zip_path = out / zip_name
        print(f"  {pack}: writing {zip_name}")
        stored, deflated = write_zip(root, zip_path, files, compress=args.compress != "0")
        zbytes = zip_path.stat().st_size
        print(f"  {pack}: {zip_name} {human(zbytes)} (stored {stored}, deflated {deflated})")
        manifest["packs"][pack] = {
            "file": zip_name,
            "bytes": zbytes,
            "sha256": sha256_file(zip_path),
            "description": DESCRIPTIONS.get(pack, ""),
            "default": pack in DEFAULT_PACKS,
            "file_count": len(files),
            "uncompressed_bytes": size,
            "files": entries,
        }
        grand_files += len(files)
        grand_bytes += size

    manifest["totals"] = {
        "packs": len(manifest["packs"]),
        "file_count": grand_files,
        "uncompressed_bytes": grand_bytes,
        "zip_bytes": sum(p["bytes"] for p in manifest["packs"].values()),
        "default_zip_bytes": sum(p["bytes"] for p in manifest["packs"].values() if p["default"]),
        "default_file_count": sum(p["file_count"] for p in manifest["packs"].values() if p["default"]),
    }
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nmanifest: {args.manifest}")
    print(f"packs: {manifest['totals']['packs']}  files: {grand_files}  raw: {human(grand_bytes)}  zipped: {human(manifest['totals']['zip_bytes'])}")
    print(f"default install: {manifest['totals']['default_file_count']} files, {human(manifest['totals']['default_zip_bytes'])} to download")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
