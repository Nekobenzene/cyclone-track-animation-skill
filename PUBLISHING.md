# 发布与维护（维护者文档）

面向要重新打包或重新发布这份 skill 的人。使用者只需要看 [README.md](README.md) 与
[DOWNLOAD.md](DOWNLOAD.md)（下载、镜像、排错）；本文件讲的是仓库与 Release 怎么维护。

`tools/` 下所有脚本的提示语均为中文：在中文控制台下按系统编码输出，被重定向或接管道时
自动改用 UTF-8，因此 CI 日志里也不会出现乱码。

## 1. 仓库与 Release 的分工

| 内容 | 位置 | 原因 |
|---|---|---|
| `single/` `season/` `scripts/` `tools/` 源码、`SKILL.md`、`README.md`、`references/`、`examples/` | **git** | 需要 diff、评审和版本历史 |
| `assets/SMCY1.3/`、`assets/geo/` | **Release 附件** | 1.6 GB，且多为第三方素材，不宜进历史 |
| `runtime/python/`、`runtime/bin/`、`bin/typhoon/` | **Release 附件** | 可由 pip / 上游 / `build_exe.py` 重建 |
| `runtime/platform.json`、`assets.manifest.json`、`requirements.txt` | **git** | 很小，是重建与校验的依据 |
| `_cache/`、`__pycache__/`、`build/`、`output/`、`dist/` | 忽略 | 派生物 |

`release` 不是 git-LFS，也不是子模块：素材是普通的 zip 附件，`assets.manifest.json`
记录了每个 zip 的 SHA-256 和内部每个文件的 SHA-256，`tools/fetch_assets.py` 负责还原。

为什么要这么切：单文件超过 100 MB 会被 GitHub 直接拒绝 push，而这份 skill 里有
`ffmpeg.exe`(212 MB)、`ffprobe.exe`(212 MB)、`EARTH.png`(204 MB)、`[GLOBAL].tif`(135 MB)。
Release 附件没有这个限制，所以大文件放在那边。

## 2. 素材包怎么切

`tools/pack_assets.py` 里的 `PACKS` 是唯一定义处，路径都是 **skill 相对路径**，
zip 内也按该相对路径存放，因此在 skill 根目录解压就能还原渲染器期望的结构。

| 包 | 内容 | 默认 |
|---|---|---|
| `map` | `map/basins/`、`map/basins.json` | ✅ 渲染必需 |
| `icons` | `mainicon/`、`summary/` | ✅ |
| `fx` | `landfall/` `particle/` `gui/` `resources/` `intensity/` `option/` `sound/` `评分表/` | ✅ |
| `font` | `font/`（Saira、思源黑体） | ✅ 字体路径锚定在 skill 内，必需 |
| `runtime` | `runtime/python/`、`runtime/bin/` | ✅ 源码模式必需；非 3.12 解释器要跳过 |
| `exe` | `bin/typhoon/` | 可选 |
| `geo` | `assets/geo/` | 可选，正常渲染不加载 |
| `legacy` | `timeline/`、`map/sources/`、`map/waterwave/`、`map/[GLOBAL]*` | 可选，当前脚本均未引用 |

打包时会做**覆盖检查**：`assets/`、`runtime/`、`bin/typhoon/` 下任何文件如果不属于任何包，
脚本报错退出并列出路径，避免新素材被悄悄漏掉。若确实新增了素材，把它加进 `PACKS`
（或确认它属于 `GIT_TRACKED` 的少量入库文件），再重新打包。

被有意排除的非素材文件：`__pycache__/`、`*.pyc`、`*.lnk`（作者的快捷方式）、
`desktop.ini`、`Thumbs.db`。

## 3. 重新打包

素材有任何改动（替换底图、补图标、换字体）都要重新生成包和清单：

```powershell
# 从原始安装目录读取，输出到仓库的 dist/
python tools\pack_assets.py --skill <原始 skill 目录> --out dist --manifest assets.manifest.json
```

脚本只读源目录，不修改它。媒体文件（mp4/png/otf/pyd…）按 STORED 存放，
只对文本和小于 4 MB 的文件做 deflate，所以打包很快、也不会因为重复压缩而变大。

**素材变了就要换 tag**：把 `--tag assets-v2` 写进清单（或改 `--tag` 后重新生成），
提交清单，再按新 tag 发一次 Release。否则已经装过旧素材的用户重跑
`fetch_assets.py` 会因为哈希不符而重新下载同一 tag 的内容。

## 4. 发布

需要一枚 GitHub token（细粒度 PAT，仓库 `cyclone-track-animation-skill`，
权限 **Contents: Read and write** 即可，够 push 和发 Release）。

```powershell
$env:GH_TOKEN = '<token>'          # 或 --token-file <path>

# 1) 代码
git add -A ; git commit -m '...' ; git push

# 2) 素材（会创建/更新 tag 对应的 Release 并上传 dist\*.zip）
python tools\publish_release.py --dry-run      # 先看要传什么
python tools\publish_release.py                # 真传
python tools\publish_release.py --pack fx      # 只补某个包
```

`publish_release.py` 走 REST API，不依赖 `gh` CLI；已存在且大小一致的附件会跳过，
所以断点续传是"重跑一次"。上传大文件耗时取决于上行带宽，单个附件不要超过 2 GB。

token 的三条来源（按顺序取）：`--token-file`、环境变量 `GH_TOKEN`、环境变量 `GITHUB_TOKEN`。
如果本机 Git Credential Manager 已经存过 GitHub 凭据（`git push` 不需要输密码就说明有），
可以直接取出复用，不必再新建一枚：

```powershell
$out = "protocol=https`nhost=github.com`n`n" | git credential fill
($out | Select-String '^password=').Matches.Groups[1].Value | Set-Content ..\.gh_token -NoNewline
python tools\publish_release.py --token-file ..\.gh_token
Remove-Item ..\.gh_token          # 用完即删，别留在工作区
```

企业网络下 GitHub 直连不通时，给 `--proxy` 传本地代理（`git push` 用
`git -c http.proxy=http://127.0.0.1:<port> push`）。

## 5. 发布前验收

在本机另建一个干净目录，走使用者路径，不要复用已有素材：

```powershell
git clone https://github.com/<owner>/cyclone-track-animation-skill D:\fresh\cta
cd D:\fresh\cta
python tools\fetch_assets.py                    # 真的从 Release 下载
python tools\fetch_assets.py --verify-only      # 全量哈希复核
bin\typhoon\typhoon.exe check                   # 期望 {"ok": true, ...}
python single\scripts\launch.py <最小项目> info
python single\scripts\launch.py <最小项目> preview
```

`preview` 是最省事的素材全链路检查：它会读 `map/basins/EARTH.png`、按盆地规则裁剪、
用 Saira 画经纬度标签并输出 `output/preview.png`。看一眼图就能确认底图、字体和
路径着色都正常；如果字体缺失会直接抛错，中文缺字会出现方框。

## 6. 已知坑

* **不要用 `Compress-Archive` 生成发布包。** 它按系统代码页写文件名，
  `assets/SMCY1.3/评分表/` 这类非 ASCII 名会乱码。只用 `tools/pack_assets.py`（Python `zipfile`）。
* **不要用 7-Zip / 资源管理器解包做验收。** 方括号名（`[GLOBAL].tif`、`[Landing]C1.mp4`）
  在 shell 通配里是保留字，手工解包容易漏文件。用 `fetch_assets.py`。
* **`runtime/python` 与解释器版本绑定。** 渲染器发现该目录存在就插到 `sys.path` 最前，
  3.10/3.14 解释器会在这里导入失败。清单和 README 都写明了这一点。
* **`TYPHOON_SKILL_ROOT`** 可覆盖 skill 根目录探测（脚本按自身位置上溯三层）；
  目录深度或 `single/scripts`、`season/scripts`、`runtime`、`assets/SMCY1.3` 的名字不要改。
* **exe 正在跑时不要重建或替换 `bin/typhoon/`**；源码改动必须 `python scripts/build_exe.py`
  重新打包才对 exe 生效（`bin/typhoon/source_manifest.json` 记录构建时的源码哈希）。
* **许可证分层**：代码 MIT（`LICENSE`），素材与字体各自授权（`NOTICE.md`）。
  换素材时同步更新 `NOTICE.md`。
