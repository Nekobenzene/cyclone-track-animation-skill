# 直接叠加云图视频

生产实现是可编译 Python 子脚本 `single/scripts/cloud_video.py`，由 single 在渲染
路径视频时调用。统一编译入口 `typhoon.exe cloud-video` 提供配置、PNG 检查帧和
视频信息检查，不需要网页，不生成处理后的云图视频，也不预先抽出图片序列。

## 配置

```powershell
& $Exe cloud-video configure $SingleProject --video 'D:\path\VIS_clean.mp4' `
  --start-utc 20261014124730 --end-utc 20261025124500 `
  --center 0.5 0.5 --zoom 1.15 --rotation 0 --blue-removal 1.1 --feather 0.42
```

首末时间均指视频实际首帧、末帧的观测 UTC，可照画面时间标注填写。
连续且等间隔的序列按 `(末时刻 - 首时刻) / (总帧数 - 1)` 自动计算观测间隔，
路径起点由 single 的实际数据决定，无需手算 h0 或根据播放速率猜测。
输入可以是14位时间或 ISO UTC。经过删帧、剪辑跳时的视频使用下文的手动分段映射。

生成 `build/cloud_video.json`（裁切、去底、羽化参数）和
`build/cloud_video_setup.json`（可复制到项目 YAML 的 cloud 块），例如：

```yaml
cloud:
  file: VIS_clean.mp4
  format: vis-clean-video
  start_utc: '20261014124730'
  end_utc: '20261025124500'
  processing_file: ../build/cloud_video.json
  fade_out_seconds: 0.5
```

`file`、`processing_file` 相对 `sourcedata`，也接受绝对路径。
可用 `processing: {zoom: 1.15, feather: 0.42}` 内联参数代替 processing_file。
不要同时设置两种参数来源。配置命令会更新参数 JSON 和片段，不改动现有项目 YAML。
所有参数和 `--out`、`--video` 等显式命令行路径相对启动目录。

## 调整与检查

```powershell
& $Exe cloud-video probe $SingleProject --video 'D:\path\VIS_clean.mp4'
& $Exe cloud-video preview $SingleProject --video 'D:\path\VIS_clean.mp4' `
  --at 0 30 60 --zoom 1.2 --black-level 0.035 --gain 1.12 `
  --background 'D:\path\actual_track_frame.png'
```

preview 的时间是源视频播放秒数，可一次检查多帧。结果进入 `output/cloud_video_preview`，
包含叠加在实际路径背景上的 PNG 和检查记录。该背景不会自动改动自身 HUD 时间文字。
预览参数只影响本次检查；确认后用相同参数运行 configure，或直接编辑 JSON。
路径渲染直接读取该 JSON。无需启动独立云图处理或视频转码任务。

使用与 VIS_CLEAN 图像工具相同的视觉处理：取景中心、放大、旋转、海蓝底抑制、
固定黑白场、Gamma、亮度、半径和羽化。与外边连通的近白色区域排除，独立亮云保留；
边缘精确为零，处理结果用 Screen／滤色叠加，跳过旧中心裁切和二次羽化。
在昼夜样本上检查，避免过高黑场阈值损失薄云。

## 解码和缓存

只在当前路径画面需要时解码、处理源帧，重复观测复用内存缓存。
缓存上限默认 24 MiB；顺序推进用同一解码器，跳到远处或倒序检查时做视频定位。
结束或切换项目时释放解码器。不写 JPG/PNG 云图缓存，也不编码中间云图 MP4。
视频仍需解码；实际耗时取决于输入分辨率、编码和路径渲染成本。
源视频必须有可靠的帧数/帧率信息；损坏帧会明确报错，不能静默套用其他帧。

## 手动分段

旧式 h0、step_h、segment1、segment2、resume_h 仍可用于直接视频，帧号指原视频帧。
`extract_every` 省略或设 1；裁切放在 processing 参数中，不用旧 crop 字段。
UTC 首末模式和手动分段模式不能混用。第一段可从非零帧开始，段间无观测则隐藏云图，
最后片段结束后，用 `fade_out_seconds`（默认 0.5 成片秒）淡出并退场，
淡出过程中沿用末帧；设 0 可直接退场。同一观测时刻之间保持上一帧，不提前显示未来观测。
原云图格式 legacy 和已处理底片 screen 保持原有行为。

源码命令等价于 `python scripts/cloud_video.py configure|preview|probe <项目> ...`。
