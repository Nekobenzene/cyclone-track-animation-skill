#!/usr/bin/env python3
"""Install the SMCY1.3 asset packs that the renderers need.

The repository tracks code and documentation only; the artwork, fonts and the
portable runtime are published as GitHub Release attachments (see
`assets.manifest.json`). This tool downloads the packs you ask for, checks the
zip and then every extracted file against the manifest's SHA-256, and only then
moves them into place, so an interrupted download cannot leave a half-installed
skill behind.

  python tools/fetch_assets.py --list
  python tools/fetch_assets.py                       # default packs, for source-mode rendering
  python tools/fetch_assets.py --pack fx,font        # just these
  python tools/fetch_assets.py --all                 # every pack, including legacy art
  python tools/fetch_assets.py --verify-only         # re-check what is already installed

Offline or mirrored installs work too:

  python tools/fetch_assets.py --base D:\\mirror\\assets-v1
  python tools/fetch_assets.py --base https://huggingface.co/<user>/<repo>/resolve/main

Re-running is safe: files that already match the manifest are skipped, so the
tool doubles as a repair command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

CHUNK = 1 << 22


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:,.1f} GB"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def pack_url(manifest: dict, pack: str, base: str | None) -> str:
    entry = manifest["packs"][pack]
    if base:
        if base.startswith(("http://", "https://", "file://")):
            return base.rstrip("/") + "/" + entry["file"]
        return str(Path(base) / entry["file"])
    return manifest["url_template"].format(repo=manifest["repo"], tag=manifest["tag"], file=entry["file"])


def open_source(url: str, proxy: str | None, timeout: float):
    if url.startswith("file://"):
        path = Path(urllib.request.url2pathname(url[7:]))
        return open(path, "rb"), path.stat().st_size
    if "://" not in url:  # plain local path
        path = Path(url)
        return open(path, "rb"), path.stat().st_size
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"User-Agent": "cyclone-track-animation-fetch/1.0"})
    response = opener.open(request, timeout=timeout)
    length = int(response.headers.get("Content-Length") or 0)
    return response, length


def download(url: str, dest: Path, proxy: str | None, timeout: float) -> None:
    print(f"  downloading {url}")
    src, total = open_source(url, proxy, timeout)
    done = 0
    started = time.time()
    last = 0.0
    try:
        with open(dest, "wb") as out:
            while True:
                block = src.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                now = time.time()
                if now - last > 1.0:
                    last = now
                    rate = done / max(now - started, 1e-6)
                    if total:
                        pct = 100.0 * done / total
                        print(f"\r  {human(done)} / {human(total)}  {pct:5.1f}%  {human(rate)}/s", end="")
                    else:
                        print(f"\r  {human(done)}  {human(rate)}/s", end="")
                    sys.stdout.flush()
    finally:
        src.close()
    print(f"\r  {human(done)} downloaded in {time.time() - started:,.0f}s" + " " * 24)
    if total and done != total:
        raise RuntimeError(f"short download: got {done} of {total} bytes")


def safe_rel(name: str) -> str:
    """Reject zip-slip and absolute entries."""
    name = name.replace("\\", "/")
    if name.startswith("/") or ".." in name.split("/") or (len(name) > 1 and name[1] == ":"):
        raise RuntimeError(f"refusing unsafe entry in pack: {name!r}")
    return name


def already_installed(dest: Path, entry: dict, quiet: bool = False) -> bool:
    missing = 0
    for f in entry["files"]:
        target = dest / f["path"]
        if not target.is_file() or target.stat().st_size != f["bytes"]:
            missing += 1
    if not missing and not quiet:
        print(f"  all {entry['file_count']} files already present with the expected size")
    return missing == 0


def install(pack: str, manifest: dict, dest: Path, args) -> str:
    entry = manifest["packs"][pack]
    print(f"\n[{pack}] {entry.get('description', '')}")
    print(f"  {entry['file_count']} files, {human(entry['uncompressed_bytes'])} unpacked, {human(entry['bytes'])} to download")

    if already_installed(dest, entry, quiet=args.verify_only):
        if args.verify_only:
            print("  verifying hashes")
            bad = verify(dest, entry, quiet=True)
            if bad:
                print(f"  ! {len(bad)} file(s) do not match the manifest, re-downloading")
            else:
                print(f"  ok: {entry['file_count']} files verified")
                return "ok"
        else:
            return "skipped"

    if args.verify_only and not args.force:
        print("  incomplete; run without --verify-only to repair")
        return "incomplete"

    url = pack_url(manifest, pack, args.base)
    workdir = dest / ".dsh_assets"
    workdir.mkdir(parents=True, exist_ok=True)
    downloads = workdir / "downloads"
    downloads.mkdir(exist_ok=True)
    zip_path = downloads / entry["file"]

    if not zip_path.is_file() or (not args.base and zip_path.stat().st_size != entry["bytes"]):
        download(url, zip_path, args.proxy, args.timeout)
    else:
        print(f"  reusing {zip_path}")

    print("  checking the archive")
    got = sha256_file(zip_path)
    if got != entry["sha256"]:
        zip_path.unlink(missing_ok=True)
        raise RuntimeError(f"{entry['file']} failed its SHA-256 check (got {got[:16]}..., want {entry['sha256'][:16]}...); deleted, please retry")

    print("  extracting and verifying")
    staging = Path(tempfile.mkdtemp(prefix=f"dsh-{pack}-", dir=str(workdir)))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"corrupt entry in {entry['file']}: {bad}")
            for member in zf.infolist():
                if member.is_dir():
                    continue
                rel = safe_rel(member.filename)
                out = staging / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, CHUNK)

        errors = []
        for f in entry["files"]:
            staged = staging / f["path"]
            if not staged.is_file():
                errors.append(f"{f['path']}: missing from the archive")
                continue
            if staged.stat().st_size != f["bytes"]:
                errors.append(f"{f['path']}: wrong size")
                continue
            if sha256_file(staged) != f["sha256"]:
                errors.append(f"{f['path']}: wrong hash")
        if errors:
            for line in errors[:20]:
                print(f"  ! {line}")
            raise RuntimeError(f"{len(errors)} file(s) failed verification; nothing was installed")

        print(f"  verified {entry['file_count']} files; installing")
        for f in entry["files"]:
            staged = staging / f["path"]
            target = dest / f["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    if not args.keep_zip:
        zip_path.unlink(missing_ok=True)
    else:
        print(f"  kept {zip_path}")
    return "installed"


def verify(dest: Path, entry: dict, quiet: bool = False) -> list[str]:
    bad = []
    for f in entry["files"]:
        target = dest / f["path"]
        if not target.is_file():
            bad.append(f"{f['path']}: missing")
            continue
        if target.stat().st_size != f["bytes"]:
            bad.append(f"{f['path']}: wrong size")
            continue
        if not quiet and sha256_file(target) != f["sha256"]:
            bad.append(f"{f['path']}: wrong hash")
        elif quiet and sha256_file(target) != f["sha256"]:
            bad.append(f"{f['path']}: wrong hash")
    return bad


def main() -> int:
    here = Path(__file__).resolve().parent
    repo = here.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(repo / "assets.manifest.json"))
    ap.add_argument("--dest", default=str(repo), help="skill root to install into (default: this repository)")
    ap.add_argument("--pack", default="", help="comma-separated packs (default: the manifest's default set)")
    ap.add_argument("--all", action="store_true", help="every pack, including the optional ones")
    ap.add_argument("--list", action="store_true", help="show the packs and exit")
    ap.add_argument("--base", default=None, help="release base: URL, mirror directory, or file:// path")
    ap.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
                    help="proxy URL, e.g. http://127.0.0.1:2080 (defaults to HTTPS_PROXY)")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--verify-only", action="store_true", help="check what is installed, download nothing")
    ap.add_argument("--force", action="store_true", help="re-download even when the files look present")
    ap.add_argument("--keep-zip", action="store_true", help="keep the downloaded archive under .dsh_assets/downloads")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"error: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dest = Path(args.dest).resolve()

    if args.list:
        print(f"{manifest['repo']}  tag {manifest['tag']}\n")
        for name, entry in manifest["packs"].items():
            tag = "default" if name in manifest["default_packs"] else "optional"
            print(f"  {name:<8} {tag:<9} {human(entry['bytes']):>10}  {entry['file_count']:>5} files  {entry.get('description', '')}")
        t = manifest["totals"]
        print(f"\n  default install: {human(t['default_zip_bytes'])} / {t['default_file_count']} files")
        print(f"  everything:      {human(t['zip_bytes'])} / {t['file_count']} files")
        return 0

    if args.all:
        packs = list(manifest["packs"])
    elif args.pack:
        packs = [p.strip() for p in args.pack.split(",") if p.strip()]
    else:
        packs = [p for p in manifest["default_packs"] if p in manifest["packs"]]
    unknown = [p for p in packs if p not in manifest["packs"]]
    if unknown:
        print(f"error: unknown pack(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(manifest['packs'])}", file=sys.stderr)
        return 2

    print(f"installing into {dest}")
    print(f"packs: {', '.join(packs)}")
    if "runtime" in packs:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print("note: the runtime pack is Windows x64 CPython 3.12. The renderers put")
        print("      runtime/python on sys.path whenever that folder exists, so a 3.10 or")
        print("      3.14 interpreter will fail to import numpy/cv2 from it. If you are not")
        print("      on 3.12, install without it:  --pack map,icons,fx,font")
        if version != "3.12":
            print(f"      (this interpreter is {version})")
    results = {}
    for pack in packs:
        try:
            results[pack] = install(pack, manifest, dest, args)
        except (urllib.error.URLError, RuntimeError, OSError) as exc:
            results[pack] = "failed"
            print(f"  error: {exc}", file=sys.stderr)

    print("\nsummary")
    for pack, status in results.items():
        print(f"  {pack:<10} {status}")
    failed = [p for p, s in results.items() if s in ("failed", "incomplete")]
    if failed:
        print(f"\n{len(failed)} pack(s) need attention: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nNow check the install:  python single/scripts/launch.py --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
