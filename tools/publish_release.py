#!/usr/bin/env python3
"""Publish `dist/*.zip` as GitHub Release attachments (maintainer tool, no gh CLI needed).

  python tools/publish_release.py --dry-run
  python tools/publish_release.py
  python tools/publish_release.py --pack fx --tag assets-v2

The token is read from --token-file, then GH_TOKEN / GITHUB_TOKEN, and needs
`Contents: Read and write` on the target repository. Everything goes through the
REST API, so nothing here depends on `gh` being installed.

Attachments are streamed, so a 600 MB pack is not loaded into memory. An
attachment that already exists with the same size is skipped, which makes a
re-run the way to resume an interrupted upload.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:,.1f} GB"


class GitHub:
    def __init__(self, token: str, proxy: str | None, timeout: float = 600.0):
        self.token = token
        self.proxy = proxy
        self.timeout = timeout
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cyclone-track-animation-publish/1.0",
        }
        headers.update(extra or {})
        return headers

    def request(self, method: str, url: str, data=None, headers: dict | None = None):
        request = urllib.request.Request(url, data=data, method=method, headers=self._headers(headers))
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit(f"GitHub API {method} {url} -> {exc.code}\n{detail}") from exc
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body

    def repo(self, slug: str) -> dict:
        return self.request("GET", f"{API}/repos/{slug}")

    def release_by_tag(self, slug: str, tag: str):
        try:
            return self.request("GET", f"{API}/repos/{slug}/releases/tags/{tag}")
        except SystemExit:
            return None

    def ensure_release(self, slug: str, tag: str, name: str, body: str, dry: bool) -> dict:
        found = self.release_by_tag(slug, tag)
        if found:
            print(f"  release {tag} exists: {found['html_url']}")
            return found
        payload = json.dumps({"tag_name": tag, "name": name, "body": body, "draft": False, "prerelease": False}).encode()
        if dry:
            print(f"  would create release {tag} ({name})")
            return {"upload_url": f"{API}/repos/{slug}/releases/placeholder/assets{{?name,label}}", "assets": []}
        created = self.request("POST", f"{API}/repos/{slug}/releases", data=payload,
                               headers={"Content-Type": "application/json"})
        print(f"  created release {tag}: {created['html_url']}")
        return created


def upload(github: GitHub, release: dict, path: Path, dry: bool) -> str:
    existing = {a["name"]: a for a in release.get("assets", [])}
    size = path.stat().st_size
    have = existing.get(path.name)
    if have and have.get("size") == size:
        print(f"  {path.name}: already uploaded ({human(size)})")
        return "skipped"
    if have:
        print(f"  {path.name}: replacing stale attachment ({human(have.get('size', 0))} -> {human(size)})")
        if not dry:
            github.request("DELETE", f"{API}/repos/{release['_slug']}/releases/assets/{have['id']}")
    if dry:
        print(f"  would upload {path.name} ({human(size)})")
        return "dry-run"

    base = release["upload_url"].split("{")[0]
    url = f"{base}?name={urllib.parse.quote(path.name)}"
    request = urllib.request.Request(url, data=open(path, "rb"), method="POST", headers=github._headers({
        "Content-Type": "application/zip",
        "Content-Length": str(size),
    }))
    print(f"  uploading {path.name} ({human(size)}) ...")
    try:
        with github.opener.open(request, timeout=github.timeout) as response:
            json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"upload of {path.name} failed: {exc.code}\n{detail}") from exc
    print(f"  {path.name}: done")
    return "uploaded"


def main() -> int:
    here = Path(__file__).resolve().parent
    repo = here.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(repo / "assets.manifest.json"))
    ap.add_argument("--dist", default=str(repo / "dist"))
    ap.add_argument("--tag", default=None, help="release tag (default: the manifest's tag)")
    ap.add_argument("--repo", default=None, help="owner/name (default: the manifest's repo)")
    ap.add_argument("--pack", default="", help="comma-separated pack names; default all in dist/")
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    slug = args.repo or manifest["repo"]
    tag = args.tag or manifest["tag"]
    wanted = [p.strip() for p in args.pack.split(",") if p.strip()] or list(manifest["packs"])
    dist = Path(args.dist)

    uploads = []
    for pack in wanted:
        entry = manifest["packs"].get(pack)
        if not entry:
            print(f"  ! {pack} is not in the manifest", file=sys.stderr)
            return 2
        path = dist / entry["file"]
        if not path.is_file():
            print(f"  ! missing {path}; run tools/pack_assets.py first", file=sys.stderr)
            return 2
        if path.stat().st_size != entry["bytes"]:
            print(f"  ! {path.name} is {path.stat().st_size} bytes but the manifest says {entry['bytes']}"
                  f" - repack so the manifest matches what you upload", file=sys.stderr)
            return 2
        uploads.append((pack, path))

    total = sum(p.stat().st_size for _, p in uploads)
    print(f"repo {slug}  tag {tag}  {'(dry run) ' if args.dry_run else ''}")
    print(f"{len(uploads)} pack(s), {human(total)} to upload")

    token = ""
    if args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token and not args.dry_run:
        print("error: no token. Pass --token-file, or set GH_TOKEN/GITHUB_TOKEN.", file=sys.stderr)
        return 2
    if not token:
        token = "dry-run"

    github = GitHub(token, args.proxy)
    if not args.dry_run:
        info = github.repo(slug)
        print(f"  authenticated as {info.get('full_name')} (push={info.get('permissions', {}).get('push')})")

    release = github.ensure_release(
        slug, tag, f"SMCY1.3 asset packs {tag}",
        "Asset, font and runtime packs for cyclone-track-animation-skill.\n\n"
        "Install with `python tools/fetch_assets.py`; every file is listed with its "
        "SHA-256 in `assets.manifest.json`. These archives unpack at the skill root.",
        args.dry_run)
    release.setdefault("_slug", slug)

    results = {}
    for pack, path in uploads:
        results[pack] = upload(github, release, path, args.dry_run)

    print("\nsummary")
    for pack, status in results.items():
        print(f"  {pack:<10} {status}")
    if not args.dry_run:
        print(f"\nrelease: https://github.com/{slug}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
