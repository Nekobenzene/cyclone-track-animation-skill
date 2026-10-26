# 独立静态预览

从 skill 根目录运行 `scripts/track_preview.py`，不启动视频编码或素材特效提取。
single / season 原预览入口与独立脚本支持相同的底片、图层选项；本脚本复用原数据解析与配色定义，
静态合成、热力、图层顺序和命令入口在本脚本中独立实现。

```text
python scripts/track_preview.py single <单旋项目>
python scripts/track_preview.py season <全季项目>
python scripts/track_preview.py season <全季项目> --product overview
python scripts/track_preview.py season <全季项目> --product storms --only 22
python scripts/track_preview.py html <全季项目>
```

single 至少需要 `sourcedata/` 中一份有效路径，可指定 `--config <yaml>`。
未指定时读取唯一的 `build/*.yaml` / `*.yml`；没有配置时直接用源数据，
不要求先生成动画配置。全季沿用每旋一个资料目录的结构。
所有入口读取当前源数据，不读取 build 中的路径快照。

## 默认标准

- 当前取景按 EARTH.png 原始像素密度输出：21600×10800 的世界地图为 60 像素/度，
  2020WP 区域输出约 8535×4800；不把裁切区域强行放大成完整世界图尺寸。
- 路径完全不透明、无深色包边，沿强度配色；DB/aL、WV、MD、RV 为各自虚线，
  其余类型为实线。
- 图层从下至上为地图 → ACE 热力 → 路径；热力不改变路径颜色。
- 热力不透明度 40%，sigma=3°，每轴半径=15°，采样步长=30 分钟，
  标量计算宽度=960，最后逐像素插值标量后着色。
- 全季和各单旋热力独立计算，共享全季实际峰值四舍五入到 0.01 的上限，
  最小上限 0.01；筛选某一旋也要先计算全季参考值。
  独立 single 项目没有全季上下文时，以该项目峰值确定上限。
- 图片只留无刻度色标柱；数值写入 JSON。仅 TC 且 >=34 kt 的六小时样本计入 ACE。

## 常用选项

`--size native` 为默认；`--size 1920x1080` 等可快速试图。
`--out <目录>` 指定输出目录，相对路径以项目为基准。
`--assets <SMCY1.3目录>` 覆盖共享素材路径。
`--heat-parameters <json>` 使用 HTML 保存的参数。
两个选择互相独立，可自由组合为 9 种：

| 参数 | 可选值 | 默认 |
|---|---|---|
| `--background` | `map` 地图、`black` 黑底、`transparent` 透明底 | `map` |
| `--layers` | `both` 路径＋热力、`track` 仅路径、`heat` 仅热力 | `both` |

透明底保存 RGBA PNG，空白位置 alpha=0；热力保留素材 alpha×40%，路径完全不透明。
黑底和透明底只读取地图元数据，不解码整幅地图。仅路径不计算热力、不显示色标柱。

```text
python scripts/track_preview.py single <项目> --background transparent --layers track
python scripts/track_preview.py season <项目> --background black --layers heat
python single/scripts/launch.py <项目> preview --background transparent --layers both
python single/scripts/typhoon_anim.py --config <配置.yaml> preview --background map --layers heat
python season/scripts/season_overview.py overview --season <项目> --background black --layers both
```

`--plain` 是 `--layers track` 的便捷别名，`--black` 是 `--background black` 的别名。
HTML 页面也提供相同的两个选择器，PNG 导出保留当前底片与图层组合；参数 JSON
一并保存两项选择。显式命令行选项优先于保存的 JSON。

独立脚本默认输出：single 到 `output/preview/preview.png`，黑底为 `preview_black.png`；
season 到 `output/overview/overview.png` 和各单旋 `NNW.png`；HTML 为
`output/overview/ace_density_preview.html`。JSON 记录像素尺寸、标尺与积分。
原 single 渲染器入口保留 `output/preview.png` / `output/preview_black.png` 的位置。
工具日志和临时文件从一开始就放在项目 `build/` 中。

编译入口为 `bin/typhoon/typhoon.exe preview single|season|html <项目>`，参数与源码一致。两项选择仅用于静态预览，不改变动画底片。

## Season output selection

Use `--select` with either `season`, `all`, or space-separated identifiers:

```text
python scripts/track_preview.py season <project> --select season
python scripts/track_preview.py season <project> --select all
python scripts/track_preview.py season <project> --select 01W 202012
python season/scripts/season_overview.py --season <project> --select 01W 202012
```

`season` writes only `overview.png`. `all` writes the season overlay and every
individual cyclone. Identifiers write one `selected_<identifiers>.png` containing
all matched cyclones. Match JTWC identifiers against Num.txt row 2 and six-digit
JMA identifiers against row 4 (multiple JMA identifiers on that row are supported).
Folder names are never used for matching. Repeated matches are deduplicated;
missing or ambiguous identifiers are errors. `season` and `all` must appear alone.
Selected heat is calculated from only the matched cyclones, using the full-season
shared scale; paths remain above heat. Background/layer/native-size options apply.
The same `--select` option is available through compiled preview/season-overview
entries after rebuilding the executable.
