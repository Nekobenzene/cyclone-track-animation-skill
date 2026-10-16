# 气旋路径动画 Skill 使用指南

这份 skill 将气旋路径和强度资料制作成 SMCY1.3 风格的地图动画，供使用者或具备文件、终端操作能力的各类 agent 使用。它包含两个制作模式：

| 模式 | 用途 | 画面与产物 |
|---|---|---|
| **single** | 制作一个气旋的完整动画 | 跟随镜头、强度着色路径、旋转等级图标、风压曲线、ACE、登陆与增强特效、灾情提示、结尾全路径及概要条；输出 MP4 和静态预览 |
| **season** | 制作一个季节的多气旋动画 | 全季与逐气旋路径图、统一镜头的动画底片，以及叠加在底片上的季节数据卡和时间轴 |

**最小输入是至少一份有效路径数据。** 可以只有 DB、TC、RV、EX 中任意一个阶段，也可以组合多个阶段；**TC.txt 不是必需文件**。其他类型气旋按实际阶段准备路径，不需要人为补造热带气旋段。

英文和数字使用 Saira，中文使用思源黑体。地图、字体、图标、音效、渲染依赖和可执行程序均随 skill 提供，Python 源码完整保留。

## 0. 从 GitHub 取得素材（先做这一步）

本仓库只跟踪**代码、文档和工具**。素材、字体、便携运行库和可执行程序体积过大
（共 2.4 GB，其中 4 个文件超过 GitHub 的 100 MB 单文件限制），改为以
**GitHub Release 附件**发布，不进入 git 历史。克隆之后先装素材，否则渲染器找不到地图和字体：

```powershell
git clone https://github.com/Nekobenzene/cyclone-track-animation-skill
cd cyclone-track-animation-skill
python tools\fetch_assets.py --list          # 看有哪些包、各多大
python tools\fetch_assets.py                 # 默认包，约 1.4 GB
```

装完验一遍：

```powershell
python tools\fetch_assets.py --verify-only   # 全量哈希复核
bin\typhoon\typhoon.exe check                # 期望 {"ok": true, ...}
```

默认会装 `map`、`icons`、`fx`、`font`、`runtime` 五个包。工具**先校验 zip 的 SHA-256，
再逐个校验解包后的文件**，全部通过才落盘，所以中断或断网不会留下半装的 skill；
重复运行会跳过已就绪的文件，也可以当修复命令用。

想按需安装、手动下载、走镜像/代理、排错，或想知道每个包里有什么：
**见 [DOWNLOAD.md](DOWNLOAD.md)**（下载与安装完整说明）。

> **`runtime` 包是 Windows x64 CPython 3.12 的库。** 渲染器只要发现 `runtime/python` 存在就会把它
> 插到 `sys.path` 最前面，所以 3.10 / 3.14 解释器会在这里导入失败。如果你的 Python 不是 3.12，
> 请用 `--pack map,icons,fx,font` 跳过该包，改用自己的依赖：
> `pip install -r requirements.txt`。编译版 `bin/typhoon/typhoon.exe` 自带解释器，不受此影响。

## 1. 安装与目录约定

### Skill 目录：工具和共享资源

将整份 skill 放在任意可读写的位置。编译版适用于 **Windows x64**，无需另外安装 Python、字体、FFmpeg 或 Python 库。

```text
cyclone-track-animation-skill/
  README.md                     本使用指南
  SKILL.md                      agent 的总入口
  DOWNLOAD.md                   下载与安装（素材包、镜像、排错）
  PUBLISHING.md                 维护者：重新打包与发布
  NOTICE.md                     第三方素材与字体的授权说明
  requirements.txt              源码运行所需 Python 依赖
  assets.manifest.json          素材包清单（文件名、大小、SHA-256）
  tools/
    fetch_assets.py             下载并校验素材包
    pack_assets.py              维护者：切分素材包并生成清单
    build_runtime.py            维护者：自行构建 runtime/
  bin/typhoon/
    typhoon.exe                 single / season 的统一可执行入口
    _internal/                  编译程序运行库
    source_manifest.json        构建对应的源码哈希
  assets/
    SMCY1.3/                    single / season 共用素材与字体
    geo/                        备用地理数据与预处理工具
    _cache/                     运行时生成的共享图标和特效缓存
  runtime/
    python/                     直接运行源码所需的库
    bin/                        FFmpeg、FFprobe
    platform.json               源码运行库的平台信息
  single/
    scripts/                    单气旋渲染器、项目启动器
    references/                 配置、数据和样式说明
    examples/                   配置参考
  season/
    scripts/                    底片、数据层和总览渲染器
    references/                 流程、数据和样式说明
    examples/                   季节制作参考
  scripts/
    typhoon_app.py              统一入口源码
    build_exe.py                重新构建可执行程序
```

保留完整目录结构。single 和 season 共用素材与运行环境，渲染逻辑分别维护。

Agent 使用时先读取 `SKILL.md`，再按任务选择 `single/SKILL.md` 或 `season/SKILL.md`。命令从实际安装位置调用，不依赖某个 agent 产品的配置目录。

### 项目目录：输入、过程与结果

项目放在 skill 目录之外，位置和名称自定。两种模式都使用 `sourcedata → build → output` 的组织方式：

```text
Projects/
  SingleProject/                一个气旋
    sourcedata/
      EX.txt                    示例：只有温带阶段也可以
      Num.txt                   以下辅助文件按需添加
      hypo.txt
      landfall.txt
      damage.txt
    build/
      storm.yaml                single 启动器生成的项目配置
      ...                       中间画面、音频、检查帧等
    output/
      ...                       成片、地图预览、海报

  SeasonProject/                多个气旋，每个气旋一个子目录
    sourcedata/
      WP01_StormA/
        EX.txt                  每个子目录至少一份任意阶段路径
        Num.txt
      WP02_StormB/
        DB.txt
        TC.txt
        RV.txt
        damage.txt
    build/
      season_names.txt          可选中文名表
      ...                       时间计划、画面和音频中间文件
    output/
      overview/                 全季和逐气旋路径图
      ...                       动画底片与合成成片
```

| 目录 | 用途 |
|---|---|
| `sourcedata` | 真实输入；普通渲染流程读取原数据 |
| `build` | 项目配置和制作中间文件，供重复渲染使用 |
| `output` | 最终结果及可查看的预览 |

新建项目只需准备 `sourcedata`；其余目录按制作步骤生成。可选的 `season_names.txt` 需要自定义中文名时再建立。

### 设置命令入口

本文示例使用 PowerShell，所有路径都替换成自己的实际位置：

```powershell
$SkillRoot = 'D:\Tools\cyclone-track-animation-skill'
$Exe = Join-Path $SkillRoot 'bin\typhoon\typhoon.exe'
$SingleProject = 'D:\Projects\SingleProject'
$SeasonProject = 'D:\Projects\SeasonProject'
& $Exe check
```

`check` 检查运行库、素材、字体和 FFmpeg 工具。后续各节沿用这几个变量。

## 2. 准备数据

single 的输入在 `<project>/sourcedata/`；season 的输入在 `<project>/sourcedata/<气旋目录>/`。每个气旋采用相同的基本文件格式。

文本使用 **UTF-8、无 BOM**，列之间用空格或制表符。时间为 **UTC**，新数据统一采用 **14 位 `YYYYMMDDHHmmSS`**，例如 `20260913120000`；年份始终写四位。

### 2.1 路径数据：至少一份

| 文件 | 阶段 | 是否必需 |
|---|---|---|
| `DB.txt` | 扰动 | 四种路径任选至少一种 |
| `TC.txt` | 热带气旋 | 四种路径任选至少一种 |
| `RV.txt` | 残余涡旋 | 四种路径任选至少一种 |
| `EX.txt` | 温带气旋 | 四种路径任选至少一种 |

只提供实际存在的阶段。每个有效路径点占一行，固定五列数量（注释可删）：

```text
# UTC时间          经度    纬度    风速kt  气压hPa
20260913000000    140.0   35.0    45      990
20260913060000    141.5   36.0    50      985
20260913120000    143.0   37.5    55      980
```


| 列 | 含义与单位 |
|---|---|
| UTC 时间 | `YYYYMMDDHHmmSS` |
| 经度 | 十进制度；东经为正，西经为负 |
| 纬度 | 十进制度；北纬为正、南纬为负 |
| 最大持续风速 | kt，节 |
| 中心最低气压 | hPa |

每个气旋建议至少两个按时间排列的有效点，并提供可用风速、气压。多阶段可按 DB → TC （→ RV） → EX 的生命史顺序衔接，记录不重叠。采样间隔由实际时间决定，常见 3 小时和 6 小时资料都可使用。

single 支持通过 YAML `data.series` 指定其他文件名及阶段；例如自定义路径文件 `Cyclone.txt`：

```yaml
data:
  series:
    - file: Cyclone.txt
      phase: EX
```

若使用其他文件名，需要先建立明确配置并通过 `single-config` 启动；无需配置的自动启动采用表中的标准文件名。season 的三个脚本统一使用标准短文件名。

风速的平均时长、资料来源和机构口径应由制作者统一或注明，工具不会自动转换不同机构的风速口径。

### 2.2 编号与属性：可选

`Num.txt` 固定三行：扰动编号、热带低压编号、命名时间。缺失项保留空行。

```text
90W
24W
20260916120000
```

`hypo.txt` 写一行 `True` 表示假想，或 `False` 表示真实。single 读取此文件作为真假标记；也可通过项目配置提供相关属性。

### 2.3 登陆事件：可选

`landfall.txt` 每行一次事件：

```text
# 名称           UTC时间         经度    纬度
Chiba            20260921090000  140.12  35.60
Izu Peninsula    20260921120000  138.90  34.60
```

顺序为 **名称、时间、经度、纬度**；名称可含空格。single 可用 YAML 的 `data.landfalls` 设置对应的显示名和标注选项。无登陆事件可不提供该文件。

### 2.4 灾情：可选

`damage.txt` 每行一个地点：

```text
# 经度  纬度   地点    死亡失踪合计  损失金额
121.50  29.90  Ningbo  12            120000
```

地点推荐使用不含空格的名称以兼容所有流程；人数为死亡与失踪合计，金额使用数值。

| 模式 | 金额单位 |
|---|---|
| single | 由 YAML 的 `data.damage_loss_unit` 决定：`yuan` 为人民币元（默认）、`wan` 为万元、`yi` 为亿元 |
| season | 人民币万元 |

跨模式复用时，建议统一用万元，并在 single 配置中写 `damage_loss_unit: wan`。上例按万元解释时，`120000` 表示 12 亿元。工具不进行币种或汇率转换。

### 2.5 卫星云图：可选，single 使用

将视频放在 `sourcedata`，在 YAML 的 `cloud` 块配置视频文件名、抽帧间隔，以及视频帧与路径时间的对应关系。气旋小时轴从最早路径点开始计算。

云图不属于最小输入；启用时按实际视频设置 `h0`、`step_h`、`segment1`、`segment2`、`resume_h` 等参数。具体字段见 [单气旋数据与配置说明](single/references/storm-pipeline.md)。

## 3. single 制作流程

### 第一步：检查数据并建立项目配置

准备好至少一份路径后运行：

```powershell
& $Exe single $SingleProject info
```

启动器读取 `build` 下唯一的 YAML；尚无配置时生成 `build/storm.yaml`，使用 skill 内置素材、自动结尾取景及 **1920×1080 / 120 fps**，并选取一个主峰值。只有非 TC 路径时，也可正常建立项目。

检查输出的点数、时间跨度、强度和事件，再编辑 YAML 的名称、标题、署名、峰值和灾情单位。现有配置会保留，数据更新后按制作需要同步调整其中的人工设置。

常用配置项示例：

```yaml
storm:
  id: MyCyclone
  title: MY CYCLONE
  name_en: MY CYCLONE
  name_cn: 示例气旋
view:
  panorama: auto
output:
  width: 1920
  height: 1080
  fps: 120
  mp4: MyCyclone_1920x1080_120fps.mp4
data:
  damage_loss_unit: wan
```

上面是需要编辑的字段片段；在生成配置上修改，保留其路径、峰值及其他必要字段。输出宽高为正偶数，帧率支持 1–120 fps。

single 的 ACE 仅计算 TC 段内 00/06/12/18 UTC 且风速 ≥34 kt 的采样，累加 `wind²/10000`。只有非 TC 阶段时 ACE 为零，路径和其他适用元素仍正常制作。

### 第二步：预览与调整

```powershell
& $Exe single $SingleProject preview
& $Exe single $SingleProject test
& $Exe single $SingleProject poster
```

| 命令 | 查看内容 |
|---|---|
| `preview` | 按原地图像素密度输出完整路径静态图，尺寸可能大于视频 |
| `test` | 关键时刻的动画检查帧 |
| `poster` | 峰值附近的代表画面 |

检查路径、取景、字体、时间和事件位置。结尾 `panorama: auto` 自动把路径放在两侧卡片之间、顶部概要条下方。

### 第三步：渲染与交付

```powershell
& $Exe single $SingleProject all
```

`all` 顺序完成素材准备、画面渲染、效果音和音画合成。中间文件进入 `build`，成片进入 `output`。声音为效果音，不附带背景音乐。

需要分步制作时可使用 `assets`、`render`、`audio`、`mux`。明确选择某份 YAML 时使用：

```powershell
& $Exe single-config --config "$SingleProject\build\storm.yaml" info
& $Exe single-config --config "$SingleProject\build\storm.yaml" all
```

## 4. season 制作流程

season 分为三个连续制作环节：**路径总览 → 动画底片 → 数据层与最终合成**。各环节读取同一项目的源数据，不使用 single 的 YAML。

当前发行版本的季节时间轴、标题和月刻度以 **2020 年西北太平洋**为基准。制作其他年份或海盆时，agent 或制作者应先调整相关年份、时间轴和标识，再构建对应版本；`--season` 负责选择项目目录。以下命令以该基准季节为例。

季节目录中的每个气旋仍只需至少一份任意阶段路径。为适配数据层发现规则，子目录采用 `WP01_StormA`、`WP02_StormB` 这样的名称。可选中文名写入 `build/season_names.txt`：

```text
WP01_StormA 示例气旋甲
WP02_StormB 示例气旋乙
```

### 第一步：路径总览

```powershell
& $Exe season-overview info --season $SeasonProject
& $Exe season-overview all --season $SeasonProject --size 1920x1080
```

检查所有气旋的路径覆盖范围。全季图和逐气旋图写入 `output/overview`。

### 第二步：动画底片

```powershell
& $Exe season-plate season-info --season $SeasonProject --size 1920x1080 --fps 120
& $Exe season-plate season-render --season $SeasonProject --size 1920x1080 --fps 120
```

底片包含地图、路径、等级图标、特效和效果音。`season-info` 准备必要素材并输出时间计划；`season-render` 编码整片。

尺寸和帧率按制作目标显式设置：single 默认 1920×1080/120 fps；season 底片默认 21600×10800/60 fps，数据层默认 1920×1080/60 fps。上述命令已统一指定为 1920×1080/120 fps。

需要先做短试渲时可指定区间与帧数：

```powershell
& $Exe season-plate season-render --season $SeasonProject --size 960x540 --fps 30 --from 2020-10-28 --to 2020-11-01 --limit 1 --audio 0 --out 'build\test.mp4'
```

考虑到可能有运镜缩放等路径动画的剪辑需求，本skill将动画底片和数据层分开处理。

### 第三步：数据层与合成

先检查统计值，再预览某个时刻：

```powershell
& $Exe season-cards info --season $SeasonProject --size 1920x1080 --fps 120
& $Exe season-cards preview --season $SeasonProject --base black --size 960x540 --at 2020-11-01 --out 'output\cards_preview.png'
```

以实际底片或剪辑版本为底，输出最终合成：

```powershell
& $Exe season-cards render --season $SeasonProject --base 'output\edited_plate.mp4' --size 1920x1080 --fps 120 --out 'output\season_final.mp4'
```

将 `edited_plate.mp4` 换成自己的底片文件。数据层读取帧时间叠加统计，不自动理解剪辑工程，因此底片剪辑须保持对应时序，即动画总时长不应改变。`--base black` 为黑底数据层，`--base map` 为静态地图，视频路径为叠加合成。

season 使用自身的统计实现，应结合 `info` 核对结果及资料口径。

## 5. 路径与资源管理

| 引用 | 相对路径基准 |
|---|---|
| single 项目参数、season `--season` | 命令启动目录；season 默认项目为当前目录 |
| single YAML 的 `paths.storm`、`paths.assets`、显式 `paths.cache` | YAML 所在目录 |
| single YAML 的 `paths.sourcedata`、`paths.build`、`paths.output` | 项目目录 |
| single 的路径数据文件、`cloud.file` | `sourcedata` |
| season 显式 `--assets`、`--out`、pass 1 的 `--cache` | 选中的 season 项目目录 |
| season pass 2 的视频型 `--base` | 选中的 season 项目目录 |
| 内置素材、字体和运行库 | skill 安装目录 |

支持绝对路径。single 启动器生成相对素材引用；项目与 skill 相对位置变化时，更新 YAML 相应路径。

共享图标和特效抽取到 `assets/_cache`，每个项目不再复制一套。项目云图和音视频中间结果保存在 `build`；渲染进行中应保留这些文件。最终成片在 `output`，同名任务重新运行会更新对应文件。

`assets/geo` 提供备用城市、国家边界和衍生地名数据。它不参与普通渲染，需地理预处理时由 agent 或制作者单独使用相关辅助工具。

## 6. 修改与维护

### 修改源码

- single：`single/scripts/typhoon_anim.py`、`single/scripts/launch.py`。
- season：`season/scripts/season_pass1.py`、`season_pass2.py`、`season_overview.py`。
- 统一可执行入口：`scripts/typhoon_app.py`。

源码执行和构建使用 **Windows x64 Python 3.12**，从 skill 的共享运行库加载依赖：

```powershell
python "$SkillRoot\single\scripts\launch.py" $SingleProject info
python "$SkillRoot\season\scripts\season_pass2.py" info --season $SeasonProject
```

### 更新可执行程序

源码修改完成并检查后运行：

```powershell
python "$SkillRoot\scripts\build_exe.py"
```

构建使用 pip 和网络下载临时打包工具，更新 `bin/typhoon` 并记录源码哈希；构建前结束使用该 exe 的任务。已构建 exe 使用构建时的代码，源文件改动通过重新构建生效。

素材、字体和地理数据位于外部共享目录，通常无需重编译。字体分发时保留 Saira 与思源黑体的许可证及版权说明，其他素材按各自来源授权使用。

### 详细参考

- [下载与安装](DOWNLOAD.md)
- [single 使用约定](single/SKILL.md)
- [single 数据与完整配置](single/references/storm-pipeline.md)
- [season 使用约定](season/SKILL.md)
- [season 制作规则](season/references/season-workflow.md)
- [season 数据层](season/references/season-cards.md)
