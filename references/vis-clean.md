# VIS_CLEAN 云图裁切与融合

这个工具把带倾斜白边、海蓝色或黑色背景的 VIS_clean PNG 转为云层素材，
用于 single 右侧云图的滤色叠加。原图保持不变；日夜使用同一组固定亮度曲线，
避免逐帧自动曝光造成闪烁。默认从 `sourcedata/frames_VIS_clean` 读取
`29W_VIS_YYYYMMDDHHmmSS.png`，文件名时间为 UTC。

## 离线调节

```powershell
& $Exe vis-clean tune $SingleProject --background 'D:\path\actual_track_frame.png'
```

生成 `output/vis_clean_tuner.html`。在普通浏览器打开即可使用，不需要服务器或网络。
页面内嵌当前下载快照的八张抽样图；可以加载更多原图，并更换路径视频背景。
默认识别项目 `build/video_modes_preview/opening_track_2s.png`；其他项目应显式提供
一帧实际路径视频。背景按 1920×1080 显示，云图中心为 (1640,620)，直径 420 px，
与当前 single 布局一致。预览背景的时间文字不会自动改为云图观测时间。

1. 拖动原图改变中心，调整放大与旋转，使主体合适、边缘文字离开有效区域。
2. 在昼间海蓝底和夜间黑底之间切换检查。海蓝底抑制去除蓝色海面；黑场阈值
   只需消除残留底色，过高会损失薄云。亮度、白场和 Gamma 控制云层纹理。
3. 羽化宽度、融合半径控制自然消隐；原图边界柔化用于裁切碰到有效图像边缘时
   缓和遮罩。外缘连通的近白色区域会自动排除，孤立亮云保留。
4. 导出参数 JSON，保存到项目 `build/vis_clean.json`。也可直接导出当前帧的
   透明 PNG 或黑底滤色 PNG。页面预览用最长边 1024 px 的内嵌样本，批处理使用
   全分辨率原图；精细纹理以命令行预览为准。加载本地原图可检查全分辨率效果。

处理后的云层 RGB 为淡冷白，明暗纹理存入 alpha；径向平滑羽化与原图有效区域
共同约束 alpha，四边精确为零。透明 PNG 可以普通 alpha 叠加；黑底 PNG/MP4
必须用 Screen／滤色叠加。不要对已经乘过 alpha 的黑底素材再乘一次遮罩。

## 单帧与批处理

```powershell
& $Exe vis-clean preview $SingleProject --frame 29W_VIS_20261014124730.png `
  --config "$SingleProject\build\vis_clean.json" --background 'D:\path\actual_track_frame.png'

& $Exe vis-clean export $SingleProject --config "$SingleProject\build\vis_clean.json" `
  --start 20261014124730 --end 20261014151730 --size 512 --fps 30 --step-seconds 150
```

`preview` 输出 `output/vis_clean_preview/` 下的 RGBA、滤色底片、实际背景合成图和参数。
`export` 输出 `output/vis_clean/` 下的 MP4 和同名 JSON 报告。
`--source` 可选其他原图目录，`--out` 可选输出目录；这些显式路径相对于命令启动目录。
不传起止时刻则取当前源文件快照的有效首尾范围。批处理前应确认下载完成；
导出中途新增文件不会加入本次快照。源目录没有 UTC 文件或存在重复 UTC 时会报错。

`--step-seconds` 为每个视频帧对应的真实观测间隔，默认 150 秒；`--fps` 为素材
视频的播放速率，两者独立。缺帧和无效占位图保持上一张实际观测，不插值生成云层，
并在报告记录观测清单、保持帧数与排除文件。首帧不能用未来观测补齐；末尾裁至
最后有效观测，报告中的 `last_grid_utc` 是实际导出末时刻。没有新增观测时，
路径脚本沿用最后一帧。白底、黑底纯色占位图和损坏图会被排除。

`--png` 另外保存直通 alpha PNG 序列到每个素材独立的 `_rgba` 子目录；
该目录非空时拒绝覆盖，应换 `--out`，防止混入旧序列。
普通 MP4 及 JSON 同名导出会更新。支持 UTC 的14位时间或带时区 ISO 时间，
没有时区的 ISO 时间也按 UTC 解释。

## 接入 single

导出报告 `cloud` 字段提供可复制的 YAML 参数：

```yaml
cloud:
  file: ../output/vis_clean/VIS_clean_screen_20261014T124730Z.mp4
  format: screen
  extract_every: 1
  h0: 90.7916666667
  step_h: 0.0416666667
  segment1: [0, 60]
  segment2: [0, 0]
  resume_h: 0
```

上例数字仅说明结构，实际使用生成报告的值。`h0` 从最早路径点计时；优先读取
`track.txt`，否则读取标准的各类型路径文件。自定义路径文件需用 `--track-start UTC`
明确提供路径起时；未找到路径时 `h0` 为 null，接入前必须补齐。
工具不会改写项目 YAML，审核参数后替换原来的 `cloud` 块。

`format: screen` 使用完整处理帧，跳过旧版中心裁切、灰度曲线和二次羽化。
普通云图不填 `format` 时沿用 `legacy` 处理。切换源视频、文件内容或抽帧参数
会使云图抽帧缓存失效；只清理工具生成的数字命名 JPG，保留其他文件。
MP4 不含 alpha，编码产生的极暗残留在路径脚本读取时归零。

源码入口为 `python scripts/vis_clean.py tune|preview|export <项目>`。
图像来源与署名由制作者核实；导出报告保留 dapiya.cn VIS_clean 来源说明，
取景可能裁掉原图角落文字，发布成片时应保留适当来源标注。
