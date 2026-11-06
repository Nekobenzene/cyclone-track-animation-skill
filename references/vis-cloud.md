# VIS 云图小工具组件

编译入口为 `typhoon.exe vis-cloud fetch|build|run PROJECT`，源码为
`scripts/vis_cloud.py`。它复用 VIS_CLEAN 图像处理算法，提供下载、处理和合成流水线，
不依赖网页。原有 `vis-clean` 单帧调节和 `cloud-video` 视频直接叠加入口继续可用。

```powershell
& $Exe vis-cloud fetch $Project --url https://data.dapiya.cn/history/30W/VIS_clean/ --year 2026
& $Exe vis-cloud build $Project --end 20261105180000 --size 512 --fps 30 --step-seconds 150
# run 相当于依次执行 fetch 和 build；可以用 --config 传入裁切/去底/羽化 JSON。
& $Exe vis-cloud run $Project --url https://data.dapiya.cn/history/30W/VIS_clean/ --year 2026
```

`fetch` 将目录快照、下载进度、失败清单放入 `build/vis_cloud/`，PNG 原图进入
`sourcedata/frames_VIS_clean/`。仅接受指定目录内、指定年份且带 14 位 UTC 的 VIS PNG；
重复运行会校验并复用已完成文件。每个失败文件最多重试三次，任何未完成下载均明确报错，
排查失败报告后重跑，不会把不完整下载当成成功。
遇到 HTTP 429 会停止后续网络请求，保留已下载文件，并在报告中记录服务器的
`Retry-After` 和每日流量额度；应等待服务器允许的时间后续传。已有请求可正常结束，
未下载项明确标为 deferred。不要通过反复重试或变换地址规避每日额度。

`build` 默认生成 512×512、30 fps 黑底滤色素材，每帧对应 150 真实秒；播放 fps
和真实观测间隔是独立参数。日夜共用固定裁切、蓝底抑制和羽化参数，不自动逐帧曝光。
缺测槽保持上一真实观测，末尾裁到最后有效观测；无效占位和损坏图记录在导出报告。
`--source`、`--out`、`--config` 的显式路径相对启动目录。参数调节见 [VIS_CLEAN](vis-clean.md)。

结果 MP4 和完整报告在 `output/vis_cloud/`；可复现处理配方及参数在
`build/vis_cloud/recipe.json`、`processing.json`。`cloud_config.json` 提供项目 YAML
可用的 `cloud` 块（`format: screen`），按实际路径起点推导 h0，不覆盖用户 YAML。
路径渲染跳过重复裁切和二次羽化，末帧后默认 0.5 成片秒淡出。

先检查昼间、夜间、峰值和边缘融合，再把 `cloud_config.json` 合入项目 YAML，
检查全部峰值、命名时刻、灾损和音效区间后渲染完整片。
