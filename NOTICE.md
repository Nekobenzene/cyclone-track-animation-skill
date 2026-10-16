# 第三方素材与授权说明

本仓库的**源代码**采用 MIT 许可证（见 `LICENSE`），覆盖范围仅限
`single/`、`season/`、`scripts/`、`tools/` 下的代码。
SMCY1.3 素材包、便携运行库和字体**不在 MIT 覆盖范围内**，它们作为
GitHub Release 附件单独发布，各自遵循原有条款。

## 字体

| 字体 | 位置 | 许可证 |
|---|---|---|
| 思源黑体 SC（Source Han Sans SC） | `assets/SMCY1.3/font/SourceHanSansSC/` | SIL Open Font License 1.1（该目录内含 `LICENSE.txt`） |
| Saira | `assets/SMCY1.3/font/_saira_master/` | SIL Open Font License 1.1（`_saira_master/OFL.txt`） |

思源黑体的官方下载地址与 SHA-256 记录在
`assets/SMCY1.3/font/SourceHanSansSC/source.json`，因此也可以直接从 Adobe 的
发布页获取，而不必从本仓库下载。

OFL 要求许可证文本与版权声明必须随字体文件一起分发。再分发时请勿删除两个字体目录下的
`LICENSE.txt` / `OFL.txt`，也不要单独售卖字体。

## FFmpeg / FFprobe

`runtime/bin/ffmpeg.exe` 与 `runtime/bin/ffprobe.exe` 是来自 gyan.dev 的
`ffmpeg-9.0.1-full_build`，属于 GPL（`--enable-gpl --enable-version3`）构建，
在此原样分发，作为渲染流程的构建输入。

* 上游项目：<https://ffmpeg.org/>
* 构建提供方：<https://www.gyan.dev/ffmpeg/builds/>
* 对应源码：见构建提供方的源码页，或 <https://ffmpeg.org/download.html>

如果不希望承担 FFmpeg 的再分发责任，可以直接从发布包中删除 `runtime/bin/`，
改由用户通过 `tools/build_runtime.py --ffmpeg <目录>` 自行获取。

## Python 运行库

`runtime/python/` 是来自 PyPI 的未修改 wheel：

| 包 | 版本 | 许可证 |
|---|---|---|
| NumPy | 2.3.5 | BSD-3-Clause |
| Pillow | 12.3.0 | MIT-CMU |
| opencv-python-headless | 5.0.0.93 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |

每个包各自保留许可证元数据，位于其 `*.dist-info` 目录内。

## 地图与特效美术素材

`assets/SMCY1.3/` 收录了两个渲染器共用的地图纸张、等级图标、登陆特效、粒子、
GUI 图版与音效；`assets/geo/` 是可选的地理预处理数据。
这些是已编译整理的美术素材，本仓库**不对其重新授权**。
任何人重新发布素材包时，需自行确认拥有相应的再分发权利。

`assets/geo/` 内含 GeoNames 地名数据（`cities500.txt`、`cities500.zip`）——
GeoNames 采用 CC BY 4.0（<https://www.geonames.org/legal/>）——以及简化国界轮廓，
其上游压缩包 `shapes.json.zip` 与派生文件 `shapes_simplified_low.json` 放在一起。
再分发该包时请标注 GeoNames；广泛发布前请再确认轮廓数据的来源与条款。
