#!/usr/bin/env python3
"""把已安装的 skill 切分成若干发布包，并生成 assets.manifest.json。

  python tools/pack_assets.py --skill <已安装的 skill 根目录> [--out dist] [--tag assets-v1]

本脚本**只读**源目录：写出 zip 和清单，不会改动被读取的 skill。
每个 zip 内部保存的都是 skill 相对路径，因此在 skill 根目录解压即可还原
渲染器期望的结构（`assets/SMCY1.3/...`、`runtime/...`、`bin/typhoon/...`）。

覆盖检查是强制的：被打包目录下任何文件如果不属于任何包，脚本会报错退出并列出路径，
因此新增素材不会被悄悄漏掉。
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
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_support import skill_root, python_command

# 包 -> 它拥有的 skill 相对文件/目录。顺序只影响报告输出。
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

# `fetch_assets.py` 不带参数时安装的包：跑源码渲染所需的一切；其余按需选择。
DEFAULT_PACKS = ["map", "icons", "fx", "font", "runtime"]
OPTIONAL_PACKS = ["exe", "geo", "legacy"]

DESCRIPTIONS = {
    "map": "底图 map/basins/ 与 basins.json（渲染底图）",
    "icons": "等级图标与概要条",
    "fx": "登陆特效、粒子、GUI、ACE 标尺、音效与强度表",
    "font": "Saira 与思源黑体",
    "legacy": "已废弃的地图纸张与未被引用的时间轴影片（渲染不需要）",
    "geo": "可选的地理预处理数据（GeoNames 与国界轮廓）",
    "runtime": "便携 CPython 3.12 库与 FFmpeg（跑源码必需）",
    "exe": "打包好的 typhoon.exe，自带 Python 解释器",
}

# 媒体本身已压缩，再 deflate 只是白费 CPU。
STORE_EXT = {
    ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff",
    ".ogg", ".mp3", ".wav", ".zip", ".gz", ".7z", ".rar", ".otf", ".ttf", ".ttc",
    ".woff", ".woff2", ".eot", ".pyd", ".dll", ".exe", ".lib", ".npy", ".npz",
    ".xlsx", ".pkl", ".fits",
}
STORE_MIN = 4 * 1024 * 1024  # 超过此大小一律 STORED，即使不在上面的名单里

SKIP_DIRS = {"__pycache__", ".git"}
# .lnk 是指向作者本机的 Windows 快捷方式，对使用者无用。
SKIP_SUFFIX = {".pyc", ".pyo", ".lnk"}
SKIP_NAMES = {"desktop.ini", "Thumbs.db", ".DS_Store"}

# 位于被打包目录内、但属于 git 而非任何包的小文件。
GIT_TRACKED = {"runtime/platform.json", "assets.manifest.json"}


def init_stdout() -> None:
    """面向控制台时用系统编码；被重定向或接管道时改用 UTF-8，避免日志乱码。"""
    try:
        if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


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
    """列出某个 skill 相对文件/目录下的文件。"""
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
    """返回 ({包: [相对路径]}, 孤儿文件列表)。"""
    packed: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    for pack, specs in PACKS.items():
        files = []
        for spec in specs:
            for rel in walk(root, spec):
                if rel in seen:
                    print(f"  ! {rel} 同时被 {seen[rel]} 和 {pack} 认领", file=sys.stderr)
                    continue
                seen[rel] = pack
                files.append(rel)
        packed[pack] = sorted(files)

    # 孤儿：位于素材/运行库目录下、但没有任何包认领的文件
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
    init_stdout()
    repo = skill_root()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", default=str(repo), help="要读取的已安装 skill 根目录（默认为本仓库）")
    ap.add_argument("--out", default=str(repo / "dist"), help="zip 输出目录（默认 <仓库>/dist）")
    ap.add_argument("--manifest", default=str(repo / "assets.manifest.json"), help="清单写入路径")
    ap.add_argument("--repo", default="Nekobenzene/cyclone-track-animation-skill", help="用于拼下载地址的 owner/name")
    ap.add_argument("--tag", default="assets-v1", help="清单指向的 Release 标签")
    ap.add_argument("--only", default="", help="逗号分隔的包名，只处理这些")
    ap.add_argument("--compress", default="1", help="1 = 小文件用 deflate，0 = 全部 STORED")
    args = ap.parse_args()

    root = Path(args.skill).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    for required in ("single/scripts", "season/scripts", "assets/SMCY1.3"):
        if not (root / required).exists():
            print(f"错误：{root} 看起来不是 skill 根目录（缺少 {required}）", file=sys.stderr)
            return 2

    wanted = [p.strip() for p in args.only.split(",") if p.strip()] or list(PACKS)
    packed, orphans = collect(root)
    if orphans:
        print("错误：以下文件位于被打包目录内，但没有任何包认领：", file=sys.stderr)
        for rel in orphans:
            print(f"  {rel}", file=sys.stderr)
        print("请把它们加入 tools/pack_assets.py 的 PACKS 后重跑。", file=sys.stderr)
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
    # Partial releases keep unchanged packs at their original immutable URLs.
    previous = Path(args.manifest)
    if args.only and previous.is_file():
        old = json.loads(previous.read_text(encoding='utf-8'))
        for name, entry in old['packs'].items():
            entry = dict(entry)
            entry.setdefault('url', old['url_template'].format(repo=old['repo'], tag=old['tag'], file=entry['file']))
            manifest['packs'][name] = entry

    grand_files = grand_bytes = 0
    for pack in wanted:
        files = packed.get(pack) or []
        if not files:
            print(f"  {pack}：在 {root} 下没有找到文件，跳过")
            continue
        size = sum((root / rel).stat().st_size for rel in files)
        print(f"  {pack}：{len(files)} 个文件，{human(size)}，正在计算哈希")
        entries = [
            {"path": rel, "bytes": (root / rel).stat().st_size, "sha256": sha256_file(root / rel)}
            for rel in files
        ]
        zip_name = f"smcy13-{pack}.zip" if pack.startswith(("map", "icons", "fx", "font", "legacy")) else f"{pack}-win64.zip"
        if pack == "geo":
            zip_name = "geo-optional.zip"
        zip_path = out / zip_name
        print(f"  {pack}：写出 {zip_name}")
        stored, deflated = write_zip(root, zip_path, files, compress=args.compress != "0")
        zbytes = zip_path.stat().st_size
        print(f"  {pack}：{zip_name} {human(zbytes)}（STORED {stored} 个，DEFLATE {deflated} 个）")
        manifest["packs"][pack] = {
            "file": zip_name,
            "bytes": zbytes,
            "sha256": sha256_file(zip_path),
            "description": DESCRIPTIONS.get(pack, ""),
            "default": pack in DEFAULT_PACKS,
            "file_count": len(files),
            "uncompressed_bytes": size,
            "files": entries,
            "url": manifest['url_template'].format(repo=args.repo, tag=args.tag, file=zip_name),
        }
        grand_files += len(files)
        grand_bytes += size

    manifest["totals"] = {
        "packs": len(manifest["packs"]),
        "file_count": sum(p['file_count'] for p in manifest['packs'].values()),
        "uncompressed_bytes": sum(p['uncompressed_bytes'] for p in manifest['packs'].values()),
        "zip_bytes": sum(p["bytes"] for p in manifest["packs"].values()),
        "default_zip_bytes": sum(p["bytes"] for p in manifest["packs"].values() if p["default"]),
        "default_file_count": sum(p["file_count"] for p in manifest["packs"].values() if p["default"]),
    }
    Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n清单：{args.manifest}")
    print(f"包数 {manifest['totals']['packs']}，文件 {grand_files}，原始 {human(grand_bytes)}，压缩后 {human(manifest['totals']['zip_bytes'])}")
    print(f"默认安装：{manifest['totals']['default_file_count']} 个文件，需下载 {human(manifest['totals']['default_zip_bytes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
