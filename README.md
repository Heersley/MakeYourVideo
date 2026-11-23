# MakeYourVideo

以 Remotion、Python 和 FFmpeg 制作原生 1440×2560、60 fps 的无旁白科普短片。每期以 `beats.json` 驱动画面，以程序微音效和配乐配合叙事。

## 🎬 成片演示 / Showcase

[在 B 站观看《为什么食盐是咸的》](https://www.bilibili.com/video/BV1VVy7zYEHZ/)

## 制作架构

```mermaid
flowchart TB
    U["Director<br/>两处人工卡点：review 样片确认、delivery 终审采纳"]
    A["Architect<br/>核查一手来源、设计分幕"]
    P["Render · preview<br/>带声样片与关键帧取证"]
    S["Render · ship<br/>原生 2K@60fps 流式编码、终混、六项验收与归档"]
    I["Infra & Verifier<br/>维护制作档案、共享底座与工具，独立复验"]
    O["交付物<br/>成片、封面、联系表与验收证据"]
    U -->|"确认选题"| A
    A -->|"提交事实与分幕"| U
    U -->|"策划定稿后制作样片"| P
    P -->|"提交样片"| U
    U -->|"review 样片确认后放行"| S
    S --> O
    O -->|"delivery 终审采纳"| U
    I -.->|"维护工具与档案"| P
    I -.->|"只读复验"| O
```

各角色的交接和返工方式见[协作流程](docs/PROCESS.md)。

## How to Use

可以先在 Remotion Studio 播放圆周角几何示例。要制作完整短片，则准备单期源码和素材，依次生成带声样片、确认 `review`、执行 `ship`、确认 `delivery`。

### 各份文档怎么用

| 文档 | 什么时候读、交给谁 |
| --- | --- |
| [`docs/AGENTS.md`](docs/AGENTS.md) | 开新工作会话时让每个 Agent 先读。这里规定单期工作边界、事实和素材要求、样片与交付的两次人工确认。 |
| [`docs/prompt.md`](docs/prompt.md) | 给一个新的 LLM 会话。填写选题、目标和本期目录，让它先熟悉项目，再整理分幕、事实和验收要求，写出可直接交给渲染 Agent 的提示词。 |
| [`docs/PROCESS.md`](docs/PROCESS.md) | 拆任务和交接时读。用于确认谁负责策划、谁写渲染、谁改工具，以及返工或复验怎么记录。 |
| [`docs/STYLE_B_SILENT_VIBE.md`](docs/STYLE_B_SILENT_VIBE.md) | 策划设计分幕、渲染编写画面、人工审片时读。这里定义画面、音效、阅读窗和视觉取证要求。 |
| [`docs/PRODUCTION.md`](docs/PRODUCTION.md) | 实际操作时打开。查单期目录、清单、快审、全片、验收和交付命令。 |
| [字体清单](assets/fonts/FONT-NOTICE.md)、[配乐说明](assets/bgm/README.md) | 准备素材时读。分别核对字体文件名、配乐授权、节拍分析和清单字段。 |
| [示例事实文件](examples/diameter/facts_and_sources.md) | 写自己的 `facts_and_sources.md` 时参考。逐项记录上屏论断、推导、一手出处和素材授权。 |

### 如何分配给 Agent

1. **策划 LLM（Architect）**。把 `docs/prompt.md` 和选题材料交给新会话。让它核查事实、规划分幕，并输出一段面向渲染 Agent 的任务提示词。交接时把提示词和本期的 `beats.json`、`facts_and_sources.md`、`src/manifest.json` 一起交给下一位。
2. **能力较强的编程 Agent（Render）**。用独立会话接收策划交接，负责单期 Remotion 组件、图形、逐帧动效、微音效和取证代码，实现后生成带声样片。样片获 `review` 后，由它运行 `ship` 制作全片。
3. **另一个 Agent（Infra & Verifier）**。把边界明确的辅助脚本、文档、依赖维护和回归测试交给它。常规小改可用较轻量的模型，并提供复现输入和验收条件。成片复验使用 `verify`。
4. **你（Director）**。决定选题、审看样片和成片，分别确认 `review` 与 `delivery`。单人也可以按职责分开使用几个会话，用单期文件和提示词交接。

### 1. 安装依赖并打开示例

安装 [Node.js](https://nodejs.org/)（`^20.19.0 || ^22.13.0 || >=24`），然后运行以下命令。已经克隆仓库时，从仓库根目录执行 `npm ci` 和 `npm run dev` 即可。

```powershell
git clone https://github.com/Heersley/MakeYourVideo.git
cd MakeYourVideo
npm ci
npm run dev
```

打开终端输出的 Studio 地址，在左侧选择 **Diameter**，播放[圆周角源码示例](examples/diameter/)的几何预览。制作带声样片时，在另一个 PowerShell 窗口进入同一个仓库根目录。

### 2. 准备正式渲染环境

- 使用支持 D3D11VA 的 Windows，并安装 Chrome 或 Edge。
- 安装 [Python 3.12.4](https://www.python.org/downloads/release/python-3124/)。
- 将 [FFmpeg 和 ffprobe 9.0.2](https://www.gyan.dev/ffmpeg/builds/#release-builds) 的两个可执行文件放在同一 `bin` 目录，并将该目录加入 PATH。
- 按[字体清单](assets/fonts/FONT-NOTICE.md)将 8 个字体文件放进 `assets/fonts/`。示例初始化会把字体复制到本期素材目录。

在仓库根目录创建 Python 环境。下面其余步骤沿用同一 PowerShell 窗口中的 `$python` 和 `$ep`。

```powershell
python -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
```

### 3. 生成一条带声样片

使用一个尚未存在的单期目录。圆周角示例会创建分幕、事实文件和渲染入口，生成配乐、节拍档案和立体声微音效，并固定本期的共享底座。

```powershell
$ep = "output/evergreen_vibe/$(Get-Date -Format yyyy-MM-dd)/01_diameter"
& $python -B examples/diameter/prepare.py $ep
```

初始化成功后，预检并制作样片。

```powershell
& $python -B tools/episode.py preflight $ep --mode preview
if ($LASTEXITCODE -eq 0) {
    & $python -B tools/episode.py preview $ep
}
```

示例会生成 30 秒、720×1280、30 fps 的带声样片。打开本期 `src/review/preview.mp4`，在同目录查看道具特写、文字尾迹、高潮静帧、手机缩略图和 `preview_qc.json`。

### 4. 换成自己的题材

在 `output/evergreen_vibe/YYYY-MM-DD/NN_主题/` 为每条视频创建独立目录。下面以示例初始化脚本生成可编辑的起点。把 `02_my_topic` 换成本期编号和主题，再按下表替换内容。

```powershell
$ep = "output/evergreen_vibe/$(Get-Date -Format yyyy-MM-dd)/02_my_topic"
& $python -B examples/diameter/prepare.py $ep
```

| 文件或目录 | 要准备的内容 |
| --- | --- |
| `beats.json` | 按[分幕格式](tools/contracts/beats.schema.json) 编排每幕的起止、阅读窗、上屏文字、音效时间与配乐高潮点。用正式帧率的整数帧对齐边界。 |
| `facts_and_sources.md` | 记录上屏论断、推导、一手出处和素材授权。 |
| `src/entry.tsx` | 实现图形、文字和动效，注册样片与正式片两个 Remotion Composition。两者共用原生画幅，帧率和长度分别对齐档案与分幕。 |
| `src/manifest.json` | 按[清单格式](tools/contracts/manifest.schema.json)填写入口、两个 Composition ID、样片帧数、制作档案、素材目录、音效和取证入口。示例绑定 [vibe-3.3](tools/profiles/vibe-3.3.json)。 |
| `src/assets/`、`src/sfx.wav` | 将静态素材和字体放入清单的 `publicDir`，默认是 `src/assets/`。修改分幕的音效节奏后，重新生成与时间轴匹配的微音效 WAV。程序合成可参考[示例初始化脚本](examples/diameter/prepare.py)中的 `render_sfx` 调用。 |
| `src/evidence/frames.py` | 更新封面、道具、文字尾迹和高潮的代表帧，让 `evidence_kit` 生成审片与全片取证文件。这里填写正式时间轴的帧号。 |

使用自备且获授权的配乐时，先分析节拍，再把对应的 `bgm` 路径和 `licenseNote` 填入本期清单。例如将 `bgm` 设为 `assets/bgm/track.wav`，并在 `licenseNote` 写明授权依据。配乐路径相对仓库根目录。

```powershell
& $python -B tools/bgm_analyze.py assets/bgm/track.wav
```

手工创建单期时，把 `$ep` 设为本期目录，再固定 `core/vibe` 快照，渲染入口应从本期 `src/vendor/vibe/` 导入。示例初始化已执行了快照步骤。

```powershell
& $python -B tools/episode.py snapshot $ep
```

文件准备好后，按第 3 步的命令预检并生成本期样片。

### 5. 确认样片并制作全片

样片通过取证且实际审看确认后，才登记 `review`。把命令里的占位文字换成真实确认意见。

```powershell
& $python -B tools/episode.py approve $ep --gate review --note '<实际样片确认意见>'
if ($LASTEXITCODE -eq 0) {
    & $python -B tools/episode.py ship $ep
}
```

`ship` 会流式编码正式片、校准终混响度、生成封面与联系表、执行 D3D11VA 对拍等验收，并归档证据。成功后，本期根目录会有正式 MP4、`cover.png`、`contact_sheet.png`、混音报告及事实文件，取证记录保存在 `src/`。分幕、源码、素材或配乐有改动时，重新生成样片并确认 `review`。

### 6. 复验与确认交付

在审看正式成片前，可以用 `verify` 只读复验归档结果，并用 `status` 查看当前卡点。

```powershell
& $python -B tools/episode.py verify $ep
& $python -B tools/episode.py status $ep
```

实际采纳成片后，登记 `delivery`。完成时，`status` 的 `nextGate` 为 `done`。

```powershell
& $python -B tools/episode.py approve $ep --gate delivery --note '<实际终审采纳意见>'
& $python -B tools/episode.py status $ep
```

路径规则、返工记录和命令参数见[制作手册](docs/PRODUCTION.md)。

## 许可

本项目源码与文档依 [MIT](LICENSE) 许可。Remotion 使用[独立许可](https://www.remotion.dev/license)，字体使用各发布方的 SIL OFL 1.1 许可。
