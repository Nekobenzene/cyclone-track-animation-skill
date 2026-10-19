# 下载与安装

这份仓库只跟踪**代码、文档和工具**。素材包、字体、便携运行库和可执行程序体积过大
（2.4 GB，其中 4 个文件超过 GitHub 的 100 MB 单文件限制），改为以 **GitHub Release 附件**发布，
不在 git 历史里。所以安装分两步：克隆仓库 → 装素材。

> 想改素材、重新打包或重新发版？看 [PUBLISHING.md](PUBLISHING.md)（维护者文档）。

## 1. 最快路径

```powershell
git clone https://github.com/Nekobenzene/cyclone-track-animation-skill
cd cyclone-track-animation-skill

python tools\fetch_assets.py --list      # 先看有哪些包、各多大（不下载）
python tools\fetch_assets.py --pack map,icons,fx,font,runtime,exe # 编译版完整安装
```

装完即可使用。建议立刻验一遍：

```powershell
python tools\fetch_assets.py --verify-only   # 按需选择已安装包进行哈希复核
bin\typhoon\typhoon.exe check                # 期望 {"ok": true, ...}
```

之后按 [README.md](README.md) 建项目开始渲染。

## 2. 环境要求

| 场景 | 需要什么 |
|---|---|
| 只跑编译版 | Windows x64，**无需另装** Python、字体、FFmpeg；装 `map,icons,fx,font,runtime,exe` |
| 跑 Python 源码 | **Windows x64 CPython 3.12**（`runtime` 包里的库是 3.12 的） |
| 只用 `fetch_assets.py` 下载 | 任意 Python 3.8+（不自带 Python 时，也可以走第 5 节手动下载） |

脚本本身是普通 Python，`fetch_assets.py` 用你系统里的解释器运行即可；
渲染器的依赖才与版本绑定（见第 4 节）。

## 3. 有哪些包

| 包 | 内容 | 大小 | 默认 |
|---|---|---|---|
| `map` | 底图 `map/basins/` 与 `basins.json` | 262 MB | ✅ |
| `icons` | 等级图标、概要条 | 417 MB | ✅ |
| `fx` | 登陆/粒子/GUI/ACE/音效/强度表 | 47 MB | ✅ |
| `font` | Saira 与思源黑体 | 105 MB | ✅ |
| `runtime` | 便携 CPython 3.12 库 + FFmpeg | 581 MB | ✅ |
| `exe` | 打包好的 `typhoon.exe`（自带解释器） | 200 MB | 可选 |
| `geo` | 备用地理数据（正常渲染不加载） | 66 MB | 可选 |
| `legacy` | 已废弃的地图纸张与未被引用的时间轴影片 | 677 MB | 可选 |

默认五个包合计约 **1.4 GB**，全部八个约 **2.3 GB**。渲染最少需要
`map` + `icons` + `fx` + `font`（`runtime` 只有在跑源码、或编译版需要 FFmpeg 时才必需）。

## 4. 按需安装

```powershell
# 编译版完整安装（runtime提供FFmpeg/FFprobe）
python tools\fetch_assets.py --pack map,icons,fx,font,runtime,exe

# 用系统 Python 跑源码，依赖自己装
python tools\fetch_assets.py --pack map,icons,fx,font
pip install -r requirements.txt

# 一次装齐（含 geo / legacy）
python tools\fetch_assets.py --all

# 只补某个包
python tools\fetch_assets.py --pack fx
```

> **`runtime` 包是 Windows x64 CPython 3.12 的库。**
> 渲染器只要发现 `runtime/python` 存在，就会把它插到 `sys.path` 最前面，
> 因此 3.10 / 3.14 解释器会在这里导入失败（`ModuleNotFoundError` / 无法加载 `.pyd`）。
> 如果你的 Python 不是 3.12，请用 `--pack map,icons,fx,font` 跳过该包，改用自己的依赖。
> 编译版 `bin/typhoon/typhoon.exe` 自带解释器，不受此影响。

## 5. 手动下载（不用 Python）

1. 打开 [Releases → assets-v1](https://github.com/Nekobenzene/cyclone-track-animation-skill/releases/tag/assets-v1)
2. 下载需要的 zip（至少 `map`、`icons`、`fx`、`font`）
3. 解压到 **skill 根目录**，即与 `single/`、`season/` 同级

zip 内部保存的就是 skill 相对路径（`assets/SMCY1.3/...`、`runtime/...`、`bin/typhoon/...`），
所以解压后结构与渲染器期望的完全一致——**不要再套一层文件夹**。

> ⚠️ 素材里有 `评分表/`（中文名）、`now playing.mp4`（空格）、`[GLOBAL].tif` 和
> `[Landing]C1.mp4`（方括号，是 shell 通配的保留字）。用资源管理器或 7-Zip 手工解压
> 容易漏文件或改名。更稳的做法是让工具解包已经下好的 zip：

```powershell
python tools\fetch_assets.py --base D:\Downloads\assets-v1 --pack map,icons,fx,font
```

`--base` 接受目录、`file://` 路径，也可以是镜像 URL。

## 6. 国内网络与镜像

GitHub Release 在国内可能很慢或断流。两种办法：

```powershell
# 1) 走本地代理（端口换成你自己的）
$env:HTTPS_PROXY = 'http://127.0.0.1:7890'
python tools\fetch_assets.py

# 2) 换镜像源：自己放到对象存储 / HuggingFace / 内网共享都行
python tools\fetch_assets.py --base https://huggingface.co/<user>/<repo>/resolve/main
python tools\fetch_assets.py --base \\nas\share\assets-v1
```

`git clone` 同理：

```powershell
git -c http.proxy=http://127.0.0.1:7890 clone https://github.com/Nekobenzene/cyclone-track-animation-skill
```

## 7. 校验、重装与清理

```powershell
python tools\fetch_assets.py --verify-only            # 复核已装文件（只读，不下载）
python tools\fetch_assets.py --verify-only --pack fx  # 只复核某个包
python tools\fetch_assets.py                          # 重跑 = 修复：缺什么补什么
python tools\fetch_assets.py --force --pack font      # 强制重下
python tools\fetch_assets.py --keep-zip --pack fx     # 保留下载的 zip（在 .dsh_assets/downloads/）
```

* 工具**先校验 zip 的 SHA-256，再逐个校验解包后的文件**，全部通过才移动到目标位置，
  因此中断或断网不会留下半装的 skill。
* 已经装好且哈希一致的包会显示 `skipped`（跳过），重复执行是安全的。
* 校验基准是 `assets.manifest.json`：里面记录了每个 zip 和其中每个文件的 SHA-256。
* 下载的 zip 默认装完即删；想留档就加 `--keep-zip`。
* 想卸载某个包，直接删对应目录即可（`assets/SMCY1.3/<子目录>`、`runtime/`、`bin/typhoon/`），
  然后 `--verify-only` 会如实报告缺失。临时目录 `.dsh_assets/` 可以随时删除。

### 常见问题

| 现象 | 原因与处理 |
|---|---|
| `ModuleNotFoundError: No module named 'numpy._core...'` 或 `.pyd` 无法加载 | 解释器不是 3.12 却装了 `runtime` 包。删掉 `runtime/python`，或用 `--pack map,icons,fx,font` 重装并 `pip install -r requirements.txt` |
| `无法将"ffmpeg"项识别为...` | 缺 `runtime` 包（FFmpeg 在 `runtime/bin/`），或改用系统 PATH 里的 ffmpeg（版本可能与实测的 9.0.1 不同） |
| 字体报错、中文显示成方框 | `font` 包没装或没装全。字体路径锚定在 skill 内，不能用项目 YAML 的 `paths.assets` 覆盖 |
| 下载中断 | 直接重跑同一条命令，已完成的包会跳过 |
| `SHA-256 check` 失败 | 下载损坏。工具会删掉坏 zip 并报错，重跑即可 |
| 代理不生效 | `--proxy http://127.0.0.1:<端口>`，或先设 `$env:HTTPS_PROXY` |
| 手工解压后 `--verify-only` 报错 | 用手工解压的文件名/编码被改动过，改用 `--base` 让工具解包 |

## 8. 装完之后

```powershell
bin\typhoon\typhoon.exe check                  # 环境自检
bin\typhoon\typhoon.exe single <项目目录> info   # 看数据统计
bin\typhoon\typhoon.exe single <项目目录> all    # 渲染成片
```

项目目录、数据格式和完整制作流程见 [README.md](README.md)；
single / season 两条流程各自的细节见 [single/SKILL.md](single/SKILL.md) 与 [season/SKILL.md](season/SKILL.md)。
