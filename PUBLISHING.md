# 构建与发布

源码、文档、示例、模板和清单进 Git；大素材、字体、便携依赖与编译程序通过
GitHub Release 分发。入口、工作流和数据格式见 [README](README.md)，安装见
[DOWNLOAD](DOWNLOAD.md)。全部保留 Python 源码。

## 整理、测试与编译

在工作副本修改；用户项目的数据与结果独立保存。临时文件和日志放 `build/`。

```powershell
python -m unittest discover -s tests
python scripts/build_exe.py
bin/typhoon/typhoon.exe check
bin/typhoon/typhoon.exe preview --help
bin/typhoon/typhoon.exe fetch-assets --list
```

用 Windows x64 CPython 3.12 构建，pip 临时安装固定版本 PyInstaller。
所有生产入口编入一个 `bin/typhoon/`，共用 `_internal/`，不为每个脚本复制运行库。
`source_manifest.json` 记录 single/season/scripts/tools 所有源码及 HTML 模板哈希。
不要在该目录的 exe 运行时替换它。源码编辑后重新构建；外部素材和模板按清单同步。
测试脚本不作为产品入口，备用 geo 工具保留在可选素材包中。

编译版也提供 `build-exe --python <外部python.exe>` 和
`build-runtime --python <外部python.exe>`；这两个构建动作仍需外部 Python/pip。
其他编译入口无需系统 Python。参数见各入口 `--help`。

## 打包与清单

`tools/pack_assets.py` 的 PACKS 是包边界定义：map、icons、fx（含gui/ace_heat.png）、
font、runtime为默认包；exe、geo、legacy为可选包。覆盖检查拒绝遗漏文件。
ZIP 使用 skill 相对路径，保留 Unicode 文件名；缓存、日志和构建中间文件不发布。

```powershell
python tools/pack_assets.py --skill <完整副本> --out dist --manifest assets.manifest.json --tag assets-v2 --only fx,exe
```

`--only` 更新指定包并保留原清单中其他包；每包的 `url` 固定到所属 Release，
未变大包可以继续引用旧 Release，不必重复上传。省略 `--only` 则重建所有包。
新包内容使用新 tag，避免覆盖旧版本资源。每个包记录压缩包与所有内部文件的SHA-256。

## 发布与验证

```powershell
git add -A
git commit -m '...'
git push
python tools/publish_release.py --pack fx,exe --dry-run
python tools/publish_release.py --pack fx,exe
```

发布使用环境变量 `GH_TOKEN` / `GITHUB_TOKEN` 或 `--token-file`，需要仓库 Contents
写权限。不要把凭据放进版本库或日志；使用系统凭据时在进程内传递。
支持 `--proxy`。上传前校验ZIP哈希；已存在附件按SHA-256判定，内容变化时替换。

验证源码测试、全部编译入口帮助、check、真实源数据的single/season PNG与HTML、
透明PNG alpha和冷缓存素材初始化。新资源必须从发布附件重新下载并按清单复核，
不能只验证开发目录的历史素材。核对远端commit、Release下载哈希与构建清单后，
同步安装skill；确认安装版可用再删除临时副本，先解除目录链接并保留链接目标。
许可证与素材来源见 [NOTICE](NOTICE.md)；分发保留字体许可证。
