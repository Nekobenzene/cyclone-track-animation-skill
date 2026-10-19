#!/usr/bin/env python3
"""从上游自行构建 `runtime/`，而不下载便携运行库包。

适用场景：不想承担便携运行库的再分发责任，或你的解释器不是打包用的
Windows x64 CPython 3.12。

  python tools/build_runtime.py                  # 为当前解释器安装依赖到 runtime/python
  python tools/build_runtime.py --ffmpeg C:\\tools\\ffmpeg\\bin   # 从目录复制 ffmpeg/ffprobe
  python tools/build_runtime.py --ffmpeg https://.../ffmpeg.zip  # 或从压缩包
  python tools/build_runtime.py --cross 3.12     # 只为 3.12 取 wheel，不在本机导入

渲染器会把 `runtime/bin` 放进 PATH，所以 FFmpeg 与 FFprobe 必须落到那里。
缺了它们，渲染器会退回使用系统 PATH 里的 ffmpeg，编码默认值可能与实测版本不同。
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
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_support import skill_root, python_command

# 官方发布的 runtime 包里带的是 ffmpeg-9.0.1-full_build。
FFMPEG_HINT = "https://www.gyan.dev/ffmpeg/builds/  （ffmpeg-release-full.7z / -full-shared.zip）"


def init_stdout() -> None:
    """面向控制台时用系统编码；被重定向或接管道时改用 UTF-8，避免日志乱码。"""
    try:
        if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run(cmd: list[str]) -> int:
    print("  $ " + " ".join(cmd))
    return subprocess.call(cmd)


def install_deps(repo: Path, cross: str | None, python=None) -> int:
    target = repo / "runtime" / "python"
    target.mkdir(parents=True, exist_ok=True)
    req = repo / "requirements.txt"
    base = python_command(python) + ["-m", "pip", "install", "--upgrade", "--target", str(target), "-r", str(req)]
    if cross:
        base += ["--python-version", cross, "--implementation", "cp", "--platform", "win_amd64", "--only-binary=:all:"]
        print(f"  正在为 CPython {cross} win_amd64 获取 wheel（这些包在当前解释器里无法导入）")
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
                print(f"  已复制 {candidate.name} -> {target}")
                found += 1
        return found

    if source.startswith(("http://", "https://")):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ffmpeg-download"
            print(f"  下载 {source}")
            urllib.request.urlretrieve(source, archive)
            if zipfile.is_zipfile(archive):
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(Path(tmp) / "x")
                found = 0
                for folder in (Path(tmp) / "x").rglob("*"):
                    if folder.is_dir():
                        found += take(folder)
            else:
                print("  ! 只自动解压 .zip；7z 请手动解开后把目录传给 --ffmpeg")
                return 2
            if not found:
                print("  ! 压缩包里没有找到 ffmpeg/ffprobe")
                return 2
        return 0

    if source.lower() == "path":
        which = shutil.which("ffmpeg")
        if not which:
            print("  ! PATH 里没有 ffmpeg")
            return 2
        return take(Path(which).parent)

    folder = Path(source)
    if not folder.is_dir():
        print(f"  ! 不是目录：{folder}")
        return 2
    return 0 if take(folder) else 2


def main() -> int:
    init_stdout()
    repo = skill_root()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(repo), help="要构建到哪个 skill 根目录（默认为本仓库）")
    ap.add_argument("--cross", default=None, help="为其他 CPython 版本取 wheel，例如 3.12")
    ap.add_argument("--ffmpeg", default=None, help="目录、zip 下载地址，或 'path'（从系统 PATH 复制）")
    ap.add_argument("--skip-deps", action="store_true", help="跳过 pip 安装")
    ap.add_argument("--python", help="External Python executable for pip")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    print(f"构建 runtime：{root}")

    if not args.skip_deps:
        version = sys.version_info
        print(f"  当前解释器：{version.major}.{version.minor}.{version.micro}（{sys.platform}）")
        if cross := args.cross:
            print(f"  交叉目标：{cross}")
        elif sys.platform != "win32" or version[:2] != (3, 12):
            print("  注意：发布的脚本针对 Windows x64 CPython 3.12；"
                  "为当前解释器构建的 wheel 可能与那个运行库不一致。")
        if install_deps(root, args.cross, args.python) != 0:
            print("  ! pip 失败；runtime/python 不完整", file=sys.stderr)
            return 1

    if args.ffmpeg:
        if copy_ffmpeg(root, args.ffmpeg) != 0:
            return 1
    else:
        print("  未提供 --ffmpeg，runtime/bin 保持原样。")
        print(f"  实测版本为 ffmpeg 9.0.1-full_build：{FFMPEG_HINT}")

    print("\n完成。可这样验证：  python single/scripts/launch.py <项目目录> info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
