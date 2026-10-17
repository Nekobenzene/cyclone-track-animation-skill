# 季节流水线

什么进、什么出，以及每个阶段各自负责什么。请与
`season-workflow.md` 一起阅读：规则在那个文件里，本文件讲的是管道。

---

## 链条

    sourcedata/                     stage 1  hand-filled best-track text
        |
        +--> season_overview.py     stage 2  overview.png + NNW.png
        |
        +--> season_pass1.py        stage 4  the plate (one silent-then-muxed mp4)
                    |
                    v
              edited plate          stage 5  by hand, outside this folder
                    |
                    v
              season_pass2.py       stage 6  the cards + timeline, over the plate
                                             (or over `black`, standalone)

阶段 2、4 和 6 彼此独立，都直接读取 `sourcedata/`。
阶段 3（`examples/<year>.md`）由人工阅读，用来改变脚本被要求做什么；
它不会被解析。

阶段 6 只读取帧索引，别的什么都不读，因此它可以在阶段 5 之前或之后运行，
而无需知道是哪一种：`--base black` 只给出数据层，
`--base <cut>.mp4` 把它叠加到完成的剪辑之上。**阶段 5 不得改变时长**，
因为阶段 6 的时间轴是钉在帧时钟上的。

## 季节应有的文件夹结构

    <season>/                       e.g. work/season/2020WP
      Overview.xlsx                 the operator's own tally - not read by anything here
      sourcedata/
        INDEX.txt                   one line per storm
        WP01_Vongfong/              one directory per storm, named NN_Name
          Num.txt TC.txt DB.txt RV.txt EX.txt
          hypo.txt landfall.txt damage.txt
      build/                        work area
        tmp/                        scratch and audio
        pass1_backups/              optional rollback copies of the scripts
        render_*.log                render logs
      output/                       finished products
        overview/                   stage 2 stills
        *.mp4                       stage 4 plates

脚本从不写入 `sourcedata/`。阶段 1 属于操作者，
渲染绝不能有破坏它的可能。

## 路径绑定

三个脚本都从文件夹而非配置文件解析季节。
共享资源位于 `<work>/res/SMCY1.3`，缓存在 `<work>/res/_cache`：

    season_pass1.py    SEASON_ROOT / SEASON_ASSETS / SEASON_CACHE constants near
                       the top of Section B
    season_overview.py --season / --assets / --out
    season_pass2.py    --season / --assets / --out

overview 和 pass 2 默认使用 `<work>/season/2020WP` 和
`<work>/res/SMCY1.3`；pass 1 的常量使用这些相同的路径。

`_bind_paths()` 还会在资源包旁边派生出一个共享缓存
（`<pack>/../_cache`），而不是放在它里面：`SMCY1.3` 是只读的事实来源，
绝不能在其中堆积派生帧。提取出的图标和特效片段就放在那里，
并跨风暴、跨多次运行复用。

## 资源包

`SMCY1.3/` 是只读的，由本技能的每个文件夹共享。

| 路径 | 说明 | 使用者 |
|---|---|---|
| `map/basins.json` | 每个 sheet 的窗口与尺寸 | 两个 pass 1 脚本 |
| `map/basins/*.png` | 唯一的地图来源 | 两个 pass 1 脚本 |
| `mainicon/` | 旋转的等级图标素材 | pass 1 |
| `landfall/` | 登陆冲击片段与登陆音效 | pass 1 |
| `particle/` | `note_ts` 升级闪光、`ERI.gif` | pass 1 |
| `sound/random/` | ERI、170 kt 与 category-4 底音、升级提示音 | pass 1 |
| `summary/` | 总结横幅素材 | pass 2 的每风暴总结横幅 |
| `timeline/` | 月份条与 ACE 圆点片段 | 脚本不使用 |
| `font/` | Saira，以及标签所需的 CJK 字体 | 全部三个脚本 |
| `gui/ace/ace_color_1000.png` | ACE 色带 | pass 1 的 ACE 条**和** pass 2 的标尺 |
| `mainicon/tc_sshws/N-TC-*.mp4` | 强度图标，以视频形式 | 计数颜色的**来源** |
| `resources/acerate.png` | ACE 速率色带 | pass 2，但按节点表读取，而非按位图读取 |

除 `basins/` 之外，`map/` 下的任何内容都不得读取。
原因见工作流手册。

pass 2 的条目中有两项值得说明。
`gui/ace/ace_color_1000.png` 与 pass 1 共用，因此替换它会同时改变两个 pass，
替换之前渲染的 plate 将无法匹配替换之后渲染的 cards。
而 `resources/acerate.png` 是按 14 个固定颜色节点加线性插值读取的，不是按位图采样：
采样会把色带绑定到条带的 776 行长度以及 PNG 量化上，
而这些节点才是设计本身。

## 产物

### 阶段 2 - `season_overview.py`

    output/overview/overview.png     1920x1080 by default
    output/overview/NNW.png          one per storm, JTWC-numbered

`--size` 会同时改变两者。`--ss` 对地图裁切做超采样；宽裁切会受益，
窄裁切则不需要。

### 阶段 4 - `season_pass1.py`

    output/season_pass1_<from>_<to>_<W>x<H>_<fps>fps.mp4

或者 `--out` 指定的任何名字。视频先以静音写出，
然后构建特效音频并混流进去，因此文件大小会变化两次。
`--audio 0` 会在静音阶段之后停止。

### 阶段 6 - `season_pass2.py`

    output/season_pass2_<base>_<W>x<H>_<fps>fps.mp4     or whatever --out says

数据层画在自己的画布上，再合成到 base 之上，
因此它的每帧开销不取决于输出尺寸：`render_w` 为 `min(3840, max(1920, W))`，
在 8534 宽的输出下，该层以 3840 绘制并放大 2.22 倍。
该放大已在 1:1 和 2-3 倍缩放下检查过，不可见；在 8K 下原生渲染的代价是 177 ms/帧，
而上述做法为 29 ms，16K 则要 1033 ms，
因此正是这个上限让 16K 成为可能。

cards、它们的模型和数字格式见 `season-cards.md`；
冻结的常量见 `season-style-spec.md` §11。

早先的一个 `season_pass2.py` 已丢失，只有它的字节码留存下来。
此后它已根据那份字节码自身的常量重建，重建后的源码就是本文件夹现在发布的版本。
**旧字节码仅作为历史记录保留**，
使用一个 Python 永远不会加载的名字：

    scripts/__pycache__/season_pass2.original-20261009.pyc   the lost original (source size 228298)
    scripts/__pycache__/season_pass2.cpython-310.pyc         the CURRENT build, in step with the .py

本技能下的每个 `__pycache__` 条目都是其旁边 `.py` 的普通缓存，
并在源码变更后用 `python -m py_compile <script>` 重建；
`original-*` 文件是唯一一个属于数据而非缓存的条目。

## 正式渲染前先计时

先跑 `info` —— 它会打印海盆、窗口、每个风暴的屏幕秒数、活动区块和精确帧数，
而不渲染任何东西。

然后在候选尺寸下做一次真实的一帧或几帧运行：

    python scripts/season_pass1.py season-render --size 8534x4800 --fps 120 \
        --from 2020-10-28 --to 2020-11-01 --limit 1 --audio 0 --out <tmp>.mp4

为此请选择季节中**最密集**部分的窗口。
平静时段的样本运行速度快一个数量级，给出的估计毫无用处。

## 日志

长时间渲染应重定向到文件，
因为进度行是唯一能判断运行还活着的方式：

    1/34661  0.0%  4.50 fps  eta 2:08:16

`python -u` 很重要：没有它，管道会缓冲，日志会一连几分钟空着，
看起来就像卡死了。

Path inputs: see [unified and legacy track rules](../../references/track-data.md). A type file may have time gaps occupied by other type files; merge fixes by timestamp, never by whole-file time ranges.
