# 流水线参考 - 输入、配置 schema、素材映射、常见陷阱

## 1. 输入数据

### 1.0 文件夹结构

```
<work root>\
  res\SMCY1.3\                 共享素材包
  res\_cache\                  共享的解码后媒体
  single\<Storm>\
    sourcedata\                *.txt、landfall.txt、损失记录、卫星云图序列
    build\                     配置 + 中间产物
    output\                    成品 MP4 + 封面图
    旧版（无用）\               被取代的剪辑
```

配置中所有 track/卫星云图路径都**相对于 `sourcedata`**；
中间产物写入 `build\`，交付物写入 `output\`。

### 1.1 标准文件

每个输入都放在 `sourcedata\` 中，并且**按文件名查找**——配置
不必指名任何一个。

| 文件 | 列 |
|---|---|
| `DB.txt` `TC.txt` `RV.txt` `EX.txt` | `time  lon  lat  wind  pres`——每个文件一段，只包含该风暴实际拥有的段 |
| `Num.txt` | 三行：扰动编号、低压编号、UTC 命名时间戳（`90W` / `24W` / `20260916120000`）；保留空行，没有 JMA 编号行 |
| `hypo.txt` | `True`（虚构）或 `False`（真实）——覆盖 `storm.hypothetical` |
| `landfall.txt` | `name  UTC time  lon  lat` |
| `damage.txt` | `lon  lat  name  dead+missing  loss` |

长文件名（`2016_Typhoon_Meranti_BestTrack.txt`）仍然可用：两者同时
存在时短名 `TC.txt` 优先，因此文件夹可以逐个文件地迁移。**空的**
分段文件会被跳过，而不会计为一个零点分段，所以可以提前创建
占位文件。

### 1.1a 时间戳

两种写法在任何地方都被接受：

```
YYYYMMDDHHmmSS         20260915120000      <- 现行
YYYY-MM-DD-HH-MM-SS  2026-09-15-12-00-00   <- 旧版
```

紧凑形式是**14 位数字**，年份明确写成四位，包括 `16280813000000`
这样的历史年份。两位数年份会被单风暴渲染器拒绝；不使用世纪
基准点（century pivot）。

### 1.2 登陆清单（`landfall.txt`）

每行一次登陆，以空白字符分隔：

```
<Name>   <UTC time>   <lon>   <lat>        <- 现行
Chiba    20260921090000 140.12  35.60
Izu Peninsula  2026-09-21-12-00-00  138.90  34.60

<Name>   <M.D> <HHz>   <lat>   <lon>       <- 旧版
Itbayat  9.13 17z      20.79   121.84
```

* **现行格式经度在前**，与 track 文件相同；旧版格式纬度在前。解析器
  通过从右数第三个字段来区分二者——旧版月份带小数点，时间戳
  从不带。
* `<M.D>` 是 月.日，`<HHz>` 是 UTC 小时（`17z`）；`HH:MMz` 也能解析。
* 名称可以包含空格（`Izu Peninsula`）——解析器从右端读取四个
  固定字段。
* 名称只是一个键：配置中的 `data.landfalls` 块以大小写不敏感的方式
  与之匹配，并提供 `place`、`cat`、颜色和标签偏移。
* 年份取自序列起点，跨年时进位。
* 配置中缺少对应条目的登陆点仍会渲染，使用默认值。

### 1.3 Track 文本格式

渲染器使用的每个 track 文件都是纯文本，每行一个点，以空白字符
分隔，UTC 时间。间隔**从数据中读取**，因此 3 小时和 6 小时的
track 都可以用——但在同一个风暴内要保持统一：

```
20260908180000    143.8    13.2    20    1005
2016-09-08-18-00-00    143.8    13.2    20    1005
   timestamp            lonE     latN   wind_kt  pressure_hpa
```

分段文件会拼接成一个连续的生命史。**只要把它们命名为 `DB.txt` /
`TC.txt` / `RV.txt` / `EX.txt` 就够了**——`data.series` 是可选的，
仅在需要覆盖自动发现、重排阶段或应用跳过时才需要：

| 阶段键 | 含义 | 图标来源 |
|---|---|---|
| `DB` | 热带扰动 | `mainicon/disturbance/N-DB-aL.mp4` |
| `TC` | 热带气旋（即 best track 本身） | `mainicon/tc_sshws/N-TD-D / N-TC-*` |
| `RV` | 残余涡旋（再分析） | `mainicon/N-TC-X.mp4` |
| `EX` | 温带气旋 | `mainicon/extratropicals/N-EX-EX.mp4` |

提示
* 自动发现按生命史顺序 DB -> TC -> RV -> EX 进行，优先使用短名，
  回退到 `*_Disturbance.txt` / `*_BestTrack.txt` /
  `*_Remnant_Vortex.txt` / `*_Extratropical.txt`。
* `skip_first` / `skip_last` 是**计数**，只存在于显式的
  `data.series` 条目上。常见的两种布局：
  * *互斥分段*（Meranti、Dujuan）：每个文件已经只包含自己那一段，
    因此不跳过任何内容；
  * *主表 + 子集视图*（Hagibis）：best track 文件同时包含扰动段和
    残余涡旋段，因此用 `skip_first: 2, skip_last: 2` 把它们
    切出去。
  各段必须拼接成一个连续序列——把打印出的点数与源文档
  核对。
* 阶段边界会在 ±2.5 h 范围内自动混合，因此图标是交叉淡入淡出
  而不是突变。
* 在再分析阶段，**风速列可以是占位值**（有些机构不发布该阶段的
  风速）。使用约 15 kt，并在摘要中说明。

### 1.4 参考风暴（Meranti 2016）点数预算

36 点 / 210 h = 扰动（1）+ best track 去掉首点（27）
+ 残余涡旋（5）+ 温带气旋（3）。

---

## 2. 配置 schema

```yaml
paths:
  storm:      ..                     # 相对于 <storm>/build/ 中的 YAML（别名：workdir）
  assets:     ../../../res/SMCY1.3    # 相对于该 YAML 文件所在目录
  sourcedata: sourcedata              # 默认 "sourcedata"；回退到 paths.storm
  build:      build                   # 默认 "build"
  output:     output                  # 默认 "output"
  tag:        v8                      # 中间目录 icons_<tag>、fx_<tag>

output:
  mp4:    my_storm_animation.mp4      # 写入 paths.output
  poster: my_storm_poster.png

storm:
  id:          WP172016              # JTWC 编号，显示在 HUD + banner 上
  name_en:     MERANTI
  name_cn:     莫兰蒂                # 简称，用于 banner
  name_cn_long: 台风莫兰蒂           # HUD 副标题 + 开场
  hypothetical: true                 # 标记虚构情景，不改写显式文案
  title:       TYPHOON MERANTI       # HUD 右上角 + 开场 + 摘要页眉
  intro_title: hypoTC MERANTI        # 仅开场；未设置时沿用 title，原样显示
  subtitle:    2016 - WESTERN NORTH PACIFIC - WP172016
  source_line: JTWC BEST TRACK + JMA POST-ANALYSIS     # HUD 标题下方
  intro_line:  假想热带气旋莫兰蒂  -  2016  -  WESTERN NORTH PACIFIC
  intro_footer: JTWC BEST TRACK + JMA POST-ANALYSIS   |   HIMAWARI-8 B13   |   SMCY1.3
  credit_line: DATA  JTWC best track - ...             # 底部居中

data:
  series:                            # 顺序很重要
    - {file: disturb.txt, phase: DB}
    - {file: besttrack.txt, phase: TC, skip_first: true}
    - {file: remnant.txt,  phase: RV}
    - {file: extratrop.txt, phase: EX}
  reanalysis:                        # 校准后的强度，叠加应用
    set:    [{h: 108, pres: 890}, {h: 114, wind: 175, pres: 880}]
    insert: [{h: 111, wind: 162, pres: 886}]     # 6 小时以内的细节（例如一次下凹）
  ace_end_h: 162                     # ACE 到此为止（TC 阶段结束）
  rapid_intensification: true        # 跨 >=2 个等级 -> 直接做等级间混合
  ri_no_fx_bands: ['C1', 'C5+', 'C5++']   # 落到这些等级的跳变混合时不用
                                          # ERI 粒子 + 音效
  ri_blend_frac: 0.45                # 混合在该间隔的这一比例内完成，
                                     # 随后保持新等级
  plateau_ease: true                 # 等值连续段经由其中点平滑过渡，
                                     # 而不是画出平坦的台阶
  # 升格动效由进入 TS/SS 且风速增强自动触发，不需配置跳过阶段。
                                     # 不算 TS 升级

  # 每个局部极大值都计入，而不只是最强的两个：一个有四次
  # 增强过程的风暴会得到四个条目。1-2 个峰值保持固定的
  # 两行摘要节奏；3 个及以上切换为每峰值一行的紧凑块。
  peaks:
    - {h: 108.0, lon: 124.1, lat: 20.2, label: 'PEAK 1   165 kt / 890 hPa',
       color: [255,214,130], summary: '165 kt / 890 hPa - 09-13 06Z',
       graph: 'peak1 165/890', pano_dx: 152, pano_dy: -44, strong: '175 kt / 880 hPa'}
    - {h: 114.0, lon: 122.9, lat: 20.4, label: 'PEAK 2   175 kt / 880 hPa',
       color: [255,158,226], summary: '175 kt / 880 hPa - 09-13 12Z'}

  landfall_file: landfall.txt        # 时间 + 位置来自这里
  landfalls:                         # 仅用于呈现，以该名称作为键
    Itbayat: {fx: landing5, landed: landed5, place: Itbayat, Batanes, PH,
              cat: 5, off_y: 62, simple_dx: -52, simple_dy: 6, color: [255,150,220]}
    # fx/landed：landing|landed (C1) 或 landing5|landed5 (C5)
    # off_y：     跟随镜头视图中的标签 y 偏移
    # simple_dx/simple_dy：全景标签偏移（dx<0 -> 文字在左侧）
    # stamp 由文件推导得出；非必要不要覆盖
    # 不用 landfall_file 时，逐条内联 h/lon/lat（旧写法）仍然可用

  damage:                            # 每个受灾地点一条
    - {cn: 福建, en: Fujian, CN, lon: 118.08, lat: 24.48, dead: 18, lost: 11, loss: '74.9'}
    # loss 单位为亿 CNY；dead+lost == 0 -> 不弹出红色提示
    # 共享同一 `group` 的条目会合并为一个弹窗，事件落在
    # 受灾最重的那一条上——用于彼此靠近的地点，否则
    # 它们的数字会接连播放、互相淹没
    - {cn: 福島県, lon: 140.47, lat: 37.75, dead: 38, group: 東北 3 県}
    - {cn: 宮城県, lon: 140.87, lat: 38.27, dead: 22, group: 東北 3 県}

view:
  tracking_span_lon: 22.8            # 跟随镜头的视场（经度度数）
  landfall_tag_hold: 0               # 登陆名称标签在淡出前保持的秒数；
                                     # 0 = 一直保留。对于多次上岸的
                                     # 风暴，可设为几秒。
  panorama: auto                     # 让 track 适配到 banner 下方 ...
  warp: auto                         # 在真实峰值 / 登陆点暂停，
                                     # 而不是默认的 tau = 0.53 / 0.71
  wind_axis_max: 0                   # 0 = 自动（>=185 kt，向上取整超过峰值）
  ace_max: 0                         # 0 = 自动（>=40）
  # ... 或改为手动取景：
  panorama_span_lon: 52.0
  panorama_center:   [130.9, 25.6]

cloud:
  file: Meranti_2016_Himawari8_Infrared_B13.mp4
  extract_every: 4
  h0:     25.3333                    # 源帧 0 对应的数据小时
  step_h: 0.0416667                  # 每个源帧对应的数据小时
  segment1: [0, 2721]
  segment2: [2724, 3342]
  resume_h: 184.25
  extract_every: 4                   # 每第 N 个源帧保留一帧
  crop: 0                            # 对源图做中心裁剪，单位 px（0 = 全图）；
                                     # 宽幅产品只需要其中心部分
  banner: Summary-N-TC-C5.mp4        # 可选覆盖；默认情况下
                                     # banner 素材按 PEAK 等级选取

banner:                              # 打印在该素材上的文字，2 行，右侧 3/4
  headline: 'WP172016   TYPHOON MERANTI   莫兰蒂'
  loss: CNY 11.91 bn
  deaths: '30'
  # line2 默认是推导出来的——peak / ACE / loss / deaths 直接来自
  # 数据，因此不会漂移。仅在需要整行覆盖时才设置它。
  # line2: 'PEAK 175 kt / 880 hPa      ACE 29.06 x10^4 kt2  ...'

audio:
  landfall_h: 0                      # 0 = landfall.txt 中最后一条 -> weaken.ogg
  xt_h: 198.0
  weaken: true                       # false = 没有大陆减弱音床

# 浮动灾害数字的节奏控制（顶层，不在 data: 之下）
damage:
  min_gap: 0.50                      # 数字之间排队的间隔，秒
  popup_duration: 1.0                # 每个数字的停留时长（2.9 = 默认值）
  spread: 135                        # 相邻数字散开的幅度，px（0 = 关闭）

summary:                             # 预留的尾卡数据；不显示页面
  sources: JTWC - JMA (Digital Typhoon) - Himawari-8 B13
  phase2_label: EXTRATROPICAL
  phase2_value: Yellow Sea - 09-17 00Z
  damage_label: DAMAGE  死亡+失踪 / 经济损失
  damage_lines: ['中国大陆  29 死 15 失踪 - CNY117.1 亿', ...]

credits:                             # 尾卡底部，每项一行
  - 素材包   SMCY1.3   -   麦块姚是屑
  - 视频制作   Nekobenzene & DeepSeek V4.1 Flash
```

任何省略项都会回退到合理的默认值；`banner.line2` 和 `summary.note`
可以完全省略。`summary.*` 和 `credits` 为将来的改版而保留；当前的
尾卡钩子时长为零，不显示统计/致谢页面。全景卡片和 banner
仍然生效。

---

## 3. 测量卫星云图序列的时间映射

Digital Typhoon 的云图序列以**均匀**速率播放，但含有一个或多个
**跳变**，因此要实测而不要假设。

```powershell
$sel = (0..16 | ForEach-Object { "eq(n\,$($_*200))" }) -join '+'
ffmpeg -v error -y -i cloud.mp4 -vf "select='$sel',crop=300:18:2:2,scale=440:26,tile=1x17" -frames:v 1 stamps.png
```

从这条胶片带中读出烧录的时间戳。实做示例（Meranti）：

| 源帧 | 时间戳 | 增量 |
|---|---|---|
| 0 | 2016-09-09 19:20 | – |
| 200 | 2016-09-10 03:40 | 100 帧 = 4.1667 h |
| 1000 | 2016-09-11 13:00 | 均匀 |
| 2700 | 2016-09-14 11:50 | 均匀 |
| **2724** | **2016-09-16 10:15** | **跳变约 46 h** |
| 3300 | 2016-09-17 10:15 | 再次均匀 |

→ `step_h = 4.1667 h / 100 frames = 2.5 min = 0.0416667 h`，
`h0 = 25.3333`（相对序列 t0 的数据小时），`segment1 = [0, 2721]`，
`segment2 = [2724, 3342]`，`resume_h = 184.25`。小窗在间隙中淡出，
并在 `resume_h` 处淡入。

`extract_every` = 4 表示每 4 个源帧保留一帧（25 fps → 6.25 fps），
这已经足够，因为云图小窗的前进速度比 track 慢约 5 倍。

---

## 4. 素材映射（SMCY1.3）

| 配置 / 功能 | 素材 |
|---|---|
| 地图底图 | `map/sources/Blue_Marble_2002_bg21600_05.png` + `Graticule.png` + `RegionLine.png` |
| TC 图标 | `mainicon/tc_sshws/N-TD-D, N-TC-TS, N-TC-C1..C5.mp4` |
| 扰动 / 残余涡旋 / 温带气旋 | `mainicon/disturbance/N-DB-aL.mp4`、`mainicon/N-TC-X.mp4`、`mainicon/extratropicals/N-EX-EX.mp4` |
| 开场 Logo | `gui/TY-LOGO-N.mp4` |
| 登陆冲击 / 标记 | `landfall/[Landing]C1.mp4` / `Landed-C1.mp4`（以及 `…C5` 那一对） |
| TD→TS 闪光 | `particle/note_ts.mp4` |
| 灾害粒子 | `particle/sweep.gif` |
| ACE 色标 | `gui/ace/ace_color_1000.png` |
| 全景 banner | `summary/Summary-N-TC-<PEAK LEVEL>.mp4`——按风暴的峰值等级选取 |
| 第三方影像的署名 | 按客户要求——dapiya.cn 为 Dolphin 提供了黑白云图序列，必须在尾卡中署名 |
| SFX | `sound/random/note_ts.ogg`, `noice_category4.ogg`, `noice_170.ogg`, `weaken.ogg`; `landfall/sound.landfall.C1.ogg` / `…C5.ogg`; `sound/damages/sweep1.ogg` |

`extract_icons` 会把 60 fps 的图标序列抽减到 20 fps；登陆冲击
保持 60 fps（绝不要把它降速）。

---

## 5. 常见陷阱

0. **开场文案原样显示。** `storm.intro_title` 优先于 `storm.title`；两者都
   未设置时才按 hypothetical 默认显示 `hypoTC` 或 `CYCLONE`。
   `storm.intro_line` 未设置时为空。显式空字符串可隐藏对应文字。
   假想风暴请在配置中写好标识，渲染器不会追加“假想”或替换“台风”。
1. **地图投影。** 底图是**以太平洋为中心**的：`x = lonE/360*10800`，
   `y = (90-lat)/180*5400`。按 `-180..180` 处理会使一切偏移 180°，track
   会落到空旷洋面上。在信任某一帧之前，先用一个已知城市验证。
2. **非 ASCII 字形。** Consolas/Microsoft YaHei 对许多符号会渲染成豆腐
   块。屏幕上的文字保持 ASCII（外加中文），并让中文走 `mixed()`，
   使两种字体共享同一基线。
3. **镜头抖动。** 对放大 2-3 倍的地图做整数像素裁剪会产生 2-3 px 的
   步进。使用 `warpAffine` 的小数偏移和约 1.7 s 的平滑窗口。
4. **云图小窗。** 裁掉烧录的水印（650×650 帧的中心 500×500），做
   径向羽化并用 screen 混合，使方形边缘不可见。
5. **全景取景。** 所有注记都必须避开摘要 banner（顶部 235 px）。让
   track 保持在 `lat_top - 0.2315*span_lat` 以下。
6. **标签碰撞。** 间距很近的登陆点（金门/厦门在全景中相距约
   10 px）需要显式的 `simple_dy` 偏移；把它们合并会让计数
   看起来不对。
7. **零伤亡。** `dead+lost == 0` 不得产生红色的 "0人" 弹窗。
8. **ACE 采样 00/06/12/18 UTC 天气图网格。** 强度会在这些时刻重新
   采样，并在其上对 `v^2` 求和——这是 WMO 惯例，无论定位点间隔
   如何都成立，对于本来就落在网格上的 track，与普通离散求和结果
   一致。累计到 `ace_end_h`；进度条是*逐步显现*的，绝不拉伸，并且
   连续爬升，因此不会一阵一阵地跳。
9. **密集的 track 需要平滑曲线。** 在 3 小时定位点之间做线性插值，
   会把每个平台期变成平坦台阶、每次变化变成拐角——强度图看起来
   像楼梯。改用保形三次插值（shape-preserving cubic）；自然三次
   插值更糟，它会凭空造出峰值。**然后合并平台期**：一段等值序列
   在其中点处变成一个结点，因此 `50 55 60 60 60 60 60 65 70`
   会缓慢地经过 60，而不会画出台阶。风速和气压**各自独立**地
   合并与插值——气压的平台期不得把风速曲线一起拖住。
   设置 `data.plateau_ease: false` 可回到每个定位点
   一个结点。
10. **阶段边界由数据驱动。** 绝不要硬编码扰动变成热带气旋的
   那个小时，也不要硬编码残余涡旋和温带阶段开始的小时——
   要从序列推导出来，否则时间线落在别处的风暴会被涂成
   错误阶段的颜色。
11. **超强气旋登陆是自动的。** 高于 155 kt 时，C6 冲击片段和音效
   根据登陆时的强度选取，效果按 `1 + (min(wind,200) - 155) * 5 %` 缩放。
   高于 185 kt 时，主题色从深蓝继续延伸，到 200 kt 变为冷白紫色 #C6E8FF，之后按异常路线延伸至 500 kt；
   峰值高于 155 kt 会重新给全景 banner 着色。台风图标本身
   仍使用 C5 素材。
12. **灾害点很多，时间很少。** 一个紧凑的受灾区域（日本 13 个县）
   在约 2.5 s 的屏幕时间内就会达到最小间距。三种办法，按重要性
   排序：**用 `group` 合并相邻地点**（15 个事件变成 6 个），
   然后给它们排队（`min_gap`），再然后缩短时长
   （`popup_duration`）并散开（`spread`）。
13. **绝不要硬编码日期片段。** 时间轴小标签、峰值子标签和单元
   格文字都从 `S.t0` 推导年月；字面量 `2016-` 或 `SEP` 只对
   某一个风暴是正确的。
14. **多次登陆需要一个保持时长。** 登陆名称标签按设计会一直保留，
   让地图持续显示风暴上岸的位置。一个在 21 小时内六次穿越群岛
   的风暴会把它们堆成无法阅读的一团——应设置
   `view.landfall_tag_hold` 并把 `off_y` 散开。
   地图标记仍然保留。
15. **队列有截止时间。** 跟随镜头一直在移动，因此拖得太久的队列，
   最后几个数字会被挤出画面——或者压到 HUD 上。检查 `info`：
   整个队列应当在受灾区域仍处于良好位置时播完。宁可收紧
   `min_gap`，也不要让它一直拖下去。
16. **尾卡的 LIFETIME 只统计热带气旋阶段。** 扰动、残余涡旋和
   温带阶段也会被跟踪和着色，但它们不是风暴的生命期——窗口
   要从 `S.phase` 中的 `TC` 条目推导，绝不要用序列的起点
   和终点。
17. **快速增强的跳变看起来太突然。** 直接从源等级混合到目标
   等级，在该间隔的前约 45 % 内完成这次混合（`ri_blend_frac`），
   其余时间保持新等级；对于落在 `ri_no_fx_bands` 所列等级的
   跳变（默认 `C1`、`C5+`、`C5++`），抑制 ERI 粒子
   和音效。
18. **banner 素材跟随峰值等级。** 一个 C2 风暴却用着 C5 的 banner，
   说明硬编码的默认值漏了出来。应选
   `summary/Summary-N-TC-<peak level>.mp4`；`banner.asset` 可以覆盖它。
19. **强度图有两个坐标轴。** 气压刻度在左，风速刻度在右——
   等级网格线属于风速曲线，因此它们的数值放在
   右侧。
20. **每次增强进入 TS 或 SS 都有升格动效与音效。** 包括从任意其他类型变性进入，
   即使风速此前已经超过 34 kt。减弱或风速不变时不触发；SS 使用黄绿色。
21. **每一行可能含中文的文字都要走 `mixed()`。** 开场页脚
   （`假想情景`）、HUD 署名行（其中点名机构：`民政部`、
   `消防庁`、`应急管理部`）、banner 和摘要页眉。只用拉丁
   字体单独绘制时，每一行都会变成一排豆腐块——而这个问题
   在两个风暴的作品中都没被发现，因为那些占位方块乍看像文字。
   用 `mixed_w()` 居中，绝不要用 `anchor='mm'`。
22. **第三方影像必须署名。** 来自外部产品的卫星云图序列必须在
   尾卡（`credits`）和 `storm.credit_line` 中署名。把提供方
   烧录的水印裁掉是可以的，*前提*是署名出现在画面上——
   绝不要抹掉署名却什么也不留下。
23. **带地图的云图序列可以对照 track 检查。** 当影像带有海岸线时，
   风暴在某个已知时间戳相对陆地的位置可以独立验证帧到数据小时的
   映射：把 track 投影到该事件时刻的帧上，看风眼是否落在
   数据所给的位置。在信任一份手工制作的时间报告之前
   先做这件事。
24. **对 track 重新定时是数据修改，不是风格修改。** 要让风暴移动
   得更快而保持其轨迹，应压缩*时间戳*（`tau = integral of 1/speed`）
   ——绝不要丢定位点，那只会改变采样密度而不影响速度。让速度
   在约 15 h 内平滑升入和降出，使衔接处保持平滑，并在同一次
   处理中重新映射 landfall 文件、峰值时刻、`ace_end_h` 以及
   任何日期文字。定位点会脱离天气图网格，这正是第 8 条要重
   采样而不是过滤的原因。

## 预渲染总览

`python scripts/typhoon_anim.py --config <config> preview` 会以全局地图的
原生像素密度（60 px/度；对当前的 WPAC 窗口约为 8534x4800）写出
`<storm>/output/preview.png`，而不启动视频渲染。`render` 和 `all` 在构建
动画渲染器或启动视频编码器之前会先生成同一张静帧。预览失败会
中止视频渲染。`preview` 命令不会修改已有的 MP4。

这个自包含的单文件脚本内嵌了季节版第 1 遍的 `pick_basin`、
`basin_window` 和 `fit_aspect` 规则的本地副本，以及第 2 阶段总览的
世界地图裁剪和轨迹绘制。它按覆盖面积比例选择海盆，把其边界与
track 合并并加 5 度内边距（南侧 10 度），把窗口扩展到 16:9，
并采样 `map/basins/EARTH.png`。强度配色、阶段混合和残余涡旋虚线
轨迹与季节静帧一致。不绘制图标、定位点、HUD 或摘要卡片。
预览路径没有黑色描边，并使用其原始彩色描边宽度的 30%；
动画路径不变。共享代码以 `_preview_` 前缀复制，绝不从其他
skill 分支导入。这套取景只用于静帧；动画现有的镜头不变。

## 导出尺寸与当前数据源重渲染

`output.width` / `output.height` 可选地指定正的偶数输出尺寸。
默认是 1920x1080；2K120 导出使用 2560/1440。创作画布仍为
1920x1080，由 FFmpeg 用 Lanczos 缩放。实现细节见
[渲染性能](rendering-performance.md)。

基于更新后的输入重新渲染时，直接读取当前项目的 `sourcedata`。
不要用历史的 build 快照或内联序列替代。从当前表格重新计算
峰值时刻、位置、标签和总计；track 起点变化后，相对的峰值
小时就会失效。检查显式的 `data.reanalysis`、`data.damage`
和 `ace_end_h` 覆盖项是否与所要求的当前数据源运行相冲突。
除非任务明确以当前源表为准，否则保留有意的覆盖。把呈现设置
与旧的数值注记分开。当长时间后台渲染需要检测并发修改时，
在开始/结束时对输入文本文件
做哈希。

路径解析：`paths.storm`/`workdir`、`assets` 以及显式的 `cache` 相对于配置文件所在目录。`sourcedata`、`build` 和 `output` 相对于解析出的 storm 目录。绝对路径仍然支持。

## 仅 TC 的 ACE 与无遮挡的结尾取景

ACE 只包含 phase 为 `TC` 的 `data.series` 块在 skip_first/skip_last
之后、实际起止定位点时间之内的 00/06/12/18Z 天气图采样。其他
阶段（DB、RV、EX）一律不计入，即使高于 34 kt。现有的 34 kt
阈值、原始强度插值和 ace_end_h 截断保持不变。规则/数据变化时，
任何显式的 banner.line2 ACE 数值都必须更新。

项目结尾使用 `view.panorama: auto`。自动取景会把整条路径放进
两块 440 px 侧卡之间（外侧留白 40 px），与每块侧卡再留 40 px
间距、与顶部 235 px 的 banner 留出间距，底部留白 48 px。最小
经度跨度是 22.8 度。把 track 居中放在这个净空矩形内；不要把
这次适配限制在某个区域地图窗口内。主动画继续使用世界地图。
显式的手动全景配置仍然支持。

可选的地理数据打包在父 skill 的 `assets/geo/` 下，与项目工作区分离。正常渲染不需要它。

Path inputs: see [unified and legacy track rules](../../references/track-data.md). A type file may have time gaps occupied by other type files; merge fixes by timestamp, never by whole-file time ranges.
