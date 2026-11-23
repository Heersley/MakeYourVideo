# 单片制作手册

在仓库根目录运行下列命令。环境与示例初始化见[快速上手](../README.md)。制作时遵循[单期约定](AGENTS.md)和[视听规范](STYLE_B_SILENT_VIBE.md)。下面的 `$python` 指安装了依赖的 Python 3.12.4，`$ep` 指本期目录。

## 项目结构

本期目录为 `output/evergreen_vibe/YYYY-MM-DD/NN_主题/`。可从[圆周角示例](../examples/diameter/)复制制作结构。

| 文件 | 内容 |
|---|---|
| `beats.json` | [分幕时间轴](../tools/contracts/beats.schema.json)，含光场、切镜、音效和音乐高潮点。分幕边界用正式时间轴的整数帧，阅读窗左闭右开。 |
| `facts_and_sources.md` | 上屏论断、推导、出处和素材授权。 |
| `src/manifest.json` | [单期清单](../tools/contracts/manifest.schema.json)，声明入口、两个 Composition、档案、素材、微音效和取证脚本。 |
| `src/entry.tsx` | 原生坐标的 Remotion 入口。快审与全片共用画幅，帧率及输出缩放由制作档案指定。 |
| `src/assets/` | 默认静态素材目录。字体放入实际 `publicDir` 下的 `fonts/`。 |
| `src/evidence/frames.py` | 指定原生代表帧，调用 `evidence_kit.main` 生成取证。 |

`entry` 相对单期 `src/`，`publicDir`、`sfx`、`evidenceScript` 相对单期目录。使用自备配乐时，在清单填写相对仓库根的 `bgm` 和实际授权说明 `licenseNote`，并预先[生成节拍档案](../assets/bgm/README.md)。

默认档案为 [vibe-3.3](../tools/profiles/vibe-3.3.json)。需要经审片确认的单幕时长例外时，选择 [vibe-3.4](../tools/profiles/vibe-3.4.json)，在 `overrides` 填写 `rule: "beat_duration"`、`scope`（例如 `B01`）、精确秒数 `value` 和 `reason`。环境覆盖可写入 `tools/env.local.json`，字段见[配置模板](../tools/env.example.json)。FFmpeg 按显式路径、本机配置、`FFMPEG_BIN`、WinGet 和 PATH 的顺序查找。

## 从样片到成片

```powershell
& $python -B tools/episode.py snapshot $ep
& $python -B tools/episode.py preflight $ep --mode preview
& $python -B tools/episode.py preview $ep
```

`snapshot` 固定公共原语。示例初始化已经执行这一步。样片、混音报告、关键静帧、手机缩略图及取证报告进入 `src/review/`。导演看完样片后，用实际确认意见登记 `review`。

```powershell
& $python -B tools/episode.py approve $ep --gate review --note '<实际样片确认意见>'
& $python -B tools/episode.py ship $ep
& $python -B tools/episode.py verify $ep
```

`ship` 生成全片候选、校准终混响度、调用取证脚本、执行验收并归档，最终停在 `delivery`。六项检查涵盖画幅与编码、光场、运动与阅读窗、布局与联系表、事实文件及硬解。事实来源、视觉判断和交付确认由导演复核。

交付目录包含成片、混音报告、分幕、联系表、封面、事实文件和 `src/`。验收报告和运行证据保存在 `src/` 和 `src/production/`。导演查看后登记终审。

```powershell
& $python -B tools/episode.py approve $ep --gate delivery --note '<实际终审采纳意见>'
& $python -B tools/episode.py status $ep
```

样片批准绑定本期内容，包括分幕、渲染源码、实际素材目录、底座快照、微音效、配乐与节拍、基准增益和档案。改动这些内容后重新提交样片。已有意见可用 `handoff` 和 `resolve` 登记及关闭。需要分步运行、继续已有候选或后台托管时，参数见 `python -B tools/episode.py --help`。
