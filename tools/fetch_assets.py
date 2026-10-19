#!/usr/bin/env python3
"""安装渲染器所需的 SMCY1.3 素材包。

本仓库只跟踪代码与文档；素材、字体和便携运行库以 GitHub Release 附件发布
（清单见 `assets.manifest.json`）。本工具负责下载你指定的包，先校验 zip、
再逐个校验解包后的文件，全部通过才移动到目标位置，因此中断不会留下半装的 skill。

  python tools/fetch_assets.py --list
  python tools/fetch_assets.py                       # 默认包，跑源码所需
  python tools/fetch_assets.py --pack fx,font        # 只要这几个
  python tools/fetch_assets.py --all                 # 全部，含 legacy 素材
  python tools/fetch_assets.py --verify-only         # 只复核已装文件

离线或镜像安装同样可行：

  python tools/fetch_assets.py --base D:\\mirror\\assets-v1
  python tools/fetch_assets.py --base https://huggingface.co/<user>/<repo>/resolve/main

重复运行是安全的：与清单一致的文件会被跳过，因此它同时充当修复命令。
完整说明见 DOWNLOAD.md。
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
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_support import skill_root, python_command

CHUNK = 1 << 22


def init_stdout() -> None:
    """面向控制台时用系统编码（中文 Windows 下即 GBK，显示正常）；
    被重定向或接管道时改用 UTF-8，避免日志里出现乱码或问号。"""
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
    return entry.get('url') or manifest["url_template"].format(repo=manifest["repo"], tag=manifest["tag"], file=entry["file"])


def open_source(url: str, proxy: str | None, timeout: float):
    if url.startswith("file://"):
        path = Path(urllib.request.url2pathname(url[7:]))
        return open(path, "rb"), path.stat().st_size
    if "://" not in url:  # 普通本地路径
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
    print(f"  下载 {url}")
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
    print(f"\r  已下载 {human(done)}，用时 {time.time() - started:,.0f} 秒" + " " * 24)
    if total and done != total:
        raise RuntimeError(f"下载不完整：收到 {done} 字节，应为 {total} 字节")


def safe_rel(name: str) -> str:
    """拒绝 zip-slip 与绝对路径条目。"""
    name = name.replace("\\", "/")
    if name.startswith("/") or ".." in name.split("/") or (len(name) > 1 and name[1] == ":"):
        raise RuntimeError(f"包内条目路径不安全，已拒绝：{name!r}")
    return name


def already_installed(dest: Path, entry: dict, quiet: bool = False) -> bool:
    missing = 0
    for f in entry["files"]:
        target = dest / f["path"]
        if not target.is_file() or target.stat().st_size != f["bytes"]:
            missing += 1
    if not missing and not quiet:
        print(f"  已存在的 {entry['file_count']} 个文件大小均一致")
    return missing == 0


def verify(dest: Path, entry: dict, quiet: bool = False) -> list[str]:
    bad = []
    for f in entry["files"]:
        target = dest / f["path"]
        if not target.is_file():
            bad.append(f"{f['path']}：缺失")
            continue
        if target.stat().st_size != f["bytes"]:
            bad.append(f"{f['path']}：大小不符")
            continue
        if sha256_file(target) != f["sha256"]:
            bad.append(f"{f['path']}：哈希不符")
    return bad


def install(pack: str, manifest: dict, dest: Path, args) -> str:
    entry = manifest["packs"][pack]
    print(f"\n[{pack}] {entry.get('description', '')}")
    print(f"  {entry['file_count']} 个文件，解包后 {human(entry['uncompressed_bytes'])}，需下载 {human(entry['bytes'])}")

    if already_installed(dest, entry, quiet=args.verify_only):
        if args.verify_only:
            print("  校验哈希中")
            bad = verify(dest, entry, quiet=True)
            if bad:
                print(f"  ! {len(bad)} 个文件与清单不符，可重新下载修复")
            else:
                print(f"  通过：{entry['file_count']} 个文件全部一致")
                return "ok"
        else:
            return "skipped"

    if args.verify_only and not args.force:
        print("  不完整；去掉 --verify-only 重跑即可修复")
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
        print(f"  复用已下载的 {zip_path}")

    print("  校验压缩包")
    got = sha256_file(zip_path)
    if got != entry["sha256"]:
        zip_path.unlink(missing_ok=True)
        raise RuntimeError(f"{entry['file']} 的 SHA-256 校验失败（实际 {got[:16]}...，"
                           f"应为 {entry['sha256'][:16]}...）；已删除损坏文件，请重试")

    print("  解包并逐个校验")
    staging = Path(tempfile.mkdtemp(prefix=f"dsh-{pack}-", dir=str(workdir)))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"{entry['file']} 内条目损坏：{bad}")
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
                errors.append(f"{f['path']}：压缩包内缺失")
                continue
            if staged.stat().st_size != f["bytes"]:
                errors.append(f"{f['path']}：大小不符")
                continue
            if sha256_file(staged) != f["sha256"]:
                errors.append(f"{f['path']}：哈希不符")
        if errors:
            for line in errors[:20]:
                print(f"  ! {line}")
            raise RuntimeError(f"{len(errors)} 个文件校验失败；未安装任何文件")

        print(f"  {entry['file_count']} 个文件校验通过，正在安装")
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
        print(f"  已保留 {zip_path}")
    return "installed"


def main() -> int:
    init_stdout()
    repo = skill_root()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="完整说明见仓库根目录的 DOWNLOAD.md")
    ap.add_argument("--manifest", default=str(repo / "assets.manifest.json"), help="清单文件路径")
    ap.add_argument("--dest", default=str(repo), help="安装到的 skill 根目录（默认为本仓库）")
    ap.add_argument("--pack", default="", help="逗号分隔的包名（不填则用清单里的默认包）")
    ap.add_argument("--all", action="store_true", help="安装全部包，含可选的 legacy / geo")
    ap.add_argument("--list", action="store_true", help="列出所有包后退出")
    ap.add_argument("--base", default=None, help="发布源：URL、镜像目录或 file:// 路径")
    ap.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
                    help="代理地址，例如 http://127.0.0.1:7890（默认取 HTTPS_PROXY）")
    ap.add_argument("--timeout", type=float, default=60.0, help="单次请求超时秒数")
    ap.add_argument("--verify-only", action="store_true", help="只校验已装文件，不下载")
    ap.add_argument("--force", action="store_true", help="即使文件看起来已就绪也重新下载")
    ap.add_argument("--keep-zip", action="store_true", help="保留下载的压缩包到 .dsh_assets/downloads")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"错误：找不到清单文件 {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dest = Path(args.dest).resolve()

    if args.list:
        print(f"{manifest['repo']}  版本标签 {manifest['tag']}\n")
        for name, entry in manifest["packs"].items():
            tag = "默认" if name in manifest["default_packs"] else "可选"
            print(f"  {name:<8} {tag:<5} {human(entry['bytes']):>10}  "
                  f"{entry['file_count']:>5} 个文件  {entry.get('description', '')}")
        t = manifest["totals"]
        print(f"\n  默认安装：{human(t['default_zip_bytes'])} / {t['default_file_count']} 个文件")
        print(f"  全部安装：{human(t['zip_bytes'])} / {t['file_count']} 个文件")
        return 0

    if args.all:
        packs = list(manifest["packs"])
    elif args.pack:
        packs = [p.strip() for p in args.pack.split(",") if p.strip()]
    else:
        packs = [p for p in manifest["default_packs"] if p in manifest["packs"]]
    unknown = [p for p in packs if p not in manifest["packs"]]
    if unknown:
        print(f"错误：未知的包：{', '.join(unknown)}", file=sys.stderr)
        print(f"可用的包：{', '.join(manifest['packs'])}", file=sys.stderr)
        return 2

    print(f"安装目录：{dest}")
    print(f"安装包：{', '.join(packs)}")
    if "runtime" in packs:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print("提示：runtime 包是 Windows x64 CPython 3.12 的库。渲染器只要发现")
        print("      runtime/python 存在就会把它放到 sys.path 最前面，因此 3.10 /")
        print("      3.14 解释器会在这里导入失败。若你不是 3.12，请改用：")
        print("      --pack map,icons,fx,font")
        if version != "3.12":
            print(f"      （当前解释器为 {version}）")
    results = {}
    for pack in packs:
        try:
            results[pack] = install(pack, manifest, dest, args)
        except (urllib.error.URLError, RuntimeError, OSError) as exc:
            results[pack] = "failed"
            print(f"  错误：{exc}", file=sys.stderr)

    status_cn = {"ok": "已校验", "installed": "已安装", "skipped": "已存在，跳过",
                 "failed": "失败", "incomplete": "不完整"}
    print("\n结果汇总")
    for pack, status in results.items():
        print(f"  {pack:<10} {status_cn.get(status, status)}")
    failed = [p for p, s in results.items() if s in ("failed", "incomplete")]
    if failed:
        print(f"\n{len(failed)} 个包需要处理：{', '.join(failed)}", file=sys.stderr)
        return 1
    print("\n安装完成。可运行 check 自检：  bin\\typhoon\\typhoon.exe check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
