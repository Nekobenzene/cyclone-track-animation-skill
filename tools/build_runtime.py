#!/usr/bin/env python3
"""Build `runtime/` from upstream sources instead of downloading the runtime pack.

Use this when you would rather not redistribute the portable runtime, or when
your interpreter is not the packaged Windows x64 CPython 3.12.

  python tools/build_runtime.py                 # install deps for THIS interpreter into runtime/python
  python tools/build_runtime.py --ffmpeg C:\\tools\\ffmpeg\\bin   # copy ffmpeg/ffprobe from a folder
  python tools/build_runtime.py --ffmpeg https://.../ffmpeg.zip  # or from an archive
  python tools/build_runtime.py --cross 3.12    # fetch win_amd64 cp312 wheels without running them

`runtime/bin` is what the renderers put on PATH, so FFmpeg and FFprobe must end
up there. Without them the renderers fall back to whatever `ffmpeg` your PATH
resolves to, which may differ in encoding defaults from the tested build.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# ffmpeg-9.0.1-full_build is what the published runtime pack carries.
FFMPEG_HINT = "https://www.gyan.dev/ffmpeg/builds/  (ffmpeg-release-full.7z / -full-shared.zip)"


def run(cmd: list[str]) -> int:
    print("  $ " + " ".join(cmd))
    return subprocess.call(cmd)


def install_deps(repo: Path, cross: str | None) -> int:
    target = repo / "runtime" / "python"
    target.mkdir(parents=True, exist_ok=True)
    req = repo / "requirements.txt"
    base = [sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(target), "-r", str(req)]
    if cross:
        base += ["--python-version", cross, "--implementation", "cp", "--platform", "win_amd64", "--only-binary=:all:"]
        print(f"  cross-installing wheels for CPython {cross} win_amd64 (they will not import in this interpreter)")
    return run(base)


def copy_ffmpeg(repo: Path, source: str) -> int:
    target = repo / "runtime" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    wanted = ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe")

    def take(folder: Path) -> int:
        found = 0
        for name in wanted:
            candidate = folder / name
            if candidate.is_file():
                shutil.copy2(candidate, target / name)
                print(f"  copied {candidate.name} -> {target}")
                found += 1
        return found

    if source.startswith(("http://", "https://")):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ffmpeg-download"
            print(f"  downloading {source}")
            urllib.request.urlretrieve(source, archive)
            if zipfile.is_zipfile(archive):
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(Path(tmp) / "x")
                found = 0
                for folder in (Path(tmp) / "x").rglob("*"):
                    if folder.is_dir():
                        found += take(folder)
            else:
                print("  ! only .zip archives are unpacked automatically; extract 7z manually and pass the folder")
                return 2
            if not found:
                print("  ! no ffmpeg/ffprobe found inside the archive")
                return 2
        return 0

    if source.lower() == "path":
        which = shutil.which("ffmpeg")
        if not which:
            print("  ! ffmpeg is not on PATH")
            return 2
        return take(Path(which).parent)

    folder = Path(source)
    if not folder.is_dir():
        print(f"  ! not a folder: {folder}")
        return 2
    return 0 if take(folder) else 2


def main() -> int:
    here = Path(__file__).resolve().parent
    repo = here.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(repo), help="skill root to build into (default: this repository)")
    ap.add_argument("--cross", default=None, help="fetch wheels for another CPython, e.g. 3.12")
    ap.add_argument("--ffmpeg", default=None, help="folder, zip URL, or 'path' to copy ffmpeg/ffprobe from")
    ap.add_argument("--skip-deps", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    print(f"building runtime in {root}")

    if not args.skip_deps:
        version = sys.version_info
        print(f"  interpreter: {version.major}.{version.minor}.{version.micro} ({sys.platform})")
        if cross := args.cross:
            print(f"  cross target: {cross}")
        elif sys.platform != "win32" or version[:2] != (3, 12):
            print("  note: the published scripts target Windows x64 CPython 3.12;"
                  " wheels built for this interpreter may not match that runtime.")
        if install_deps(root, args.cross) != 0:
            print("  ! pip failed; runtime/python is incomplete", file=sys.stderr)
            return 1

    if args.ffmpeg:
        if copy_ffmpeg(root, args.ffmpeg) != 0:
            return 1
    else:
        print("  no --ffmpeg given; runtime/bin left alone.")
        print(f"  the tested build is ffmpeg 9.0.1-full_build: {FFMPEG_HINT}")

    print("\ndone. Verify with:  python single/scripts/launch.py <project> info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
