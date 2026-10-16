#!/usr/bin/env python3
"""把 `dist/*.zip` 发布为 GitHub Release 附件（维护者工具，不需要 gh CLI）。

  python tools/publish_release.py --dry-run
  python tools/publish_release.py
  python tools/publish_release.py --pack fx --tag assets-v2

token 依次从 --token-file、环境变量 GH_TOKEN、GITHUB_TOKEN 读取，需要对目标仓库
具备 `Contents: Read and write` 权限。全部走 REST API，因此不依赖本机安装 `gh`。

附件是流式上传的，600 MB 的包不会读进内存。已存在且大小一致的附件会被跳过，
所以"上传中断就重跑一次"就是续传方式。
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


def init_stdout() -> None:
    """面向控制台时用系统编码；被重定向或接管道时改用 UTF-8，避免日志乱码。"""
    try:
        if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


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
            print(f"  Release {tag} 已存在：{found['html_url']}")
            return found
        payload = json.dumps({"tag_name": tag, "name": name, "body": body, "draft": False, "prerelease": False}).encode()
        if dry:
            print(f"  将创建 Release {tag}（{name}）")
            return {"upload_url": f"{API}/repos/{slug}/releases/placeholder/assets{{?name,label}}", "assets": []}
        created = self.request("POST", f"{API}/repos/{slug}/releases", data=payload,
                               headers={"Content-Type": "application/json"})
        print(f"  已创建 Release {tag}：{created['html_url']}")
        return created


def upload(github: GitHub, release: dict, path: Path, dry: bool) -> str:
    existing = {a["name"]: a for a in release.get("assets", [])}
    size = path.stat().st_size
    have = existing.get(path.name)
    if have and have.get("size") == size:
        print(f"  {path.name}：已上传过（{human(size)}）")
        return "skipped"
    if have:
        print(f"  {path.name}：替换旧附件（{human(have.get('size', 0))} -> {human(size)}）")
        if not dry:
            github.request("DELETE", f"{API}/repos/{release['_slug']}/releases/assets/{have['id']}")
    if dry:
        print(f"  将上传 {path.name}（{human(size)}）")
        return "dry-run"

    base = release["upload_url"].split("{")[0]
    url = f"{base}?name={urllib.parse.quote(path.name)}"
    request = urllib.request.Request(url, data=open(path, "rb"), method="POST", headers=github._headers({
        "Content-Type": "application/zip",
        "Content-Length": str(size),
    }))
    print(f"  上传 {path.name}（{human(size)}）...")
    try:
        with github.opener.open(request, timeout=github.timeout) as response:
            json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"上传 {path.name} 失败：{exc.code}\n{detail}") from exc
    print(f"  {path.name}：完成")
    return "uploaded"


def main() -> int:
    init_stdout()
    here = Path(__file__).resolve().parent
    repo = here.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(repo / "assets.manifest.json"), help="清单路径")
    ap.add_argument("--dist", default=str(repo / "dist"), help="zip 所在目录")
    ap.add_argument("--tag", default=None, help="Release 标签（默认取清单里的 tag）")
    ap.add_argument("--repo", default=None, help="owner/name（默认取清单里的 repo）")
    ap.add_argument("--pack", default="", help="逗号分隔的包名；默认 dist/ 里的全部")
    ap.add_argument("--token-file", default=None, help="存放 token 的文件")
    ap.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
                    help="代理地址，例如 http://127.0.0.1:7890")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要做什么，不访问 GitHub")
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
            print(f"  ! 清单里没有包 {pack}", file=sys.stderr)
            return 2
        path = dist / entry["file"]
        if not path.is_file():
            print(f"  ! 缺少 {path}；请先运行 tools/pack_assets.py", file=sys.stderr)
            return 2
        if path.stat().st_size != entry["bytes"]:
            print(f"  ! {path.name} 实际 {path.stat().st_size} 字节，清单记录 {entry['bytes']} 字节"
                  f"——请重新打包，让清单与要上传的文件一致", file=sys.stderr)
            return 2
        uploads.append((pack, path))

    total = sum(p.stat().st_size for _, p in uploads)
    print(f"仓库 {slug}  标签 {tag}  {'（试运行）' if args.dry_run else ''}")
    print(f"{len(uploads)} 个包，共需上传 {human(total)}")

    token = ""
    if args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token and not args.dry_run:
        print("错误：没有 token。请用 --token-file，或设置 GH_TOKEN / GITHUB_TOKEN。", file=sys.stderr)
        return 2
    if not token:
        token = "dry-run"

    github = GitHub(token, args.proxy)
    if not args.dry_run:
        info = github.repo(slug)
        print(f"  已认证为 {info.get('full_name')}（push={info.get('permissions', {}).get('push')}）")

    release = github.ensure_release(
        slug, tag, f"SMCY1.3 素材包 {tag}",
        "cyclone-track-animation-skill 的素材、字体与运行库包。\n\n"
        "安装方式见仓库的 DOWNLOAD.md；每个文件的 SHA-256 记录在 assets.manifest.json。\n"
        "这些压缩包在 skill 根目录解压即可还原渲染器期望的目录结构。",
        args.dry_run)
    release.setdefault("_slug", slug)

    results = {}
    for pack, path in uploads:
        results[pack] = upload(github, release, path, args.dry_run)

    status_cn = {"skipped": "已存在，跳过", "uploaded": "已上传", "dry-run": "试运行"}
    print("\n结果汇总")
    for pack, status in results.items():
        print(f"  {pack:<10} {status_cn.get(status, status)}")
    if not args.dry_run:
        print(f"\nRelease：https://github.com/{slug}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
