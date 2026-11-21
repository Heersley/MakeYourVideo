# MakeYourVideo

> **0 人声 · 原生 2K@60fps 的 Vibe 知识大赏类短视频生产框架**（Remotion + Python + FFmpeg）

**MakeYourVideo** is a production framework for silent, cinematic 9:16 explainer shorts. One `beats.json` timeline drives the whole film; Remotion handles motion and typography, Python handles beat-aligned scoring and hardware-decode acceptance. No voice-over, no subtitle band — just type, geometry, light and sound.

```bash
git clone https://github.com/Heersley/MakeYourVideo.git
cd MakeYourVideo
```

---

## 它解决什么问题

- **0 人声**：不配音、不做逐词字幕，靠 `beats.json` 连续时间轴 + 大字 + 图形演化 + 微音效 + 配乐。
- **原生 2K**：`1440×2560 @ 60fps`、H.264 `High@5.1`（`Level 4.2/5.0` 的宏块上限装不下 864,000 宏块/秒）。
- **程序验收**：6 项硬指标，其中 D3D11VA 硬解对拍专门拦「电脑能播、手机灰屏」的编码事故。
- **可复现**：仓库只有源码、依赖清单与规范；字体、配乐、成片全部不入库。

> `examples/nim_game/` 是一条 184 秒 / 31 幕的完整参考实现，**1080p 时代产物**：学状态机写法与验收脚本，不要把它的 `-level:v 4.2` 照抄到 2K 新片。

---

## 四方协作架构

| 角色 | 定位 | 核心职责 |
|---|---|---|
| **决策者（人）** | 导演 / 最终决策 | 选题、事实口径、快审、交付四处拍板 |
| **编导** | 事实核查 / 提示词架构 | 一手核查、隐喻自检、分幕与气口、写执行指令 |
| **成片工程** | 生产侧 | 源码、两阶段渲染、6 项验收、混音、清理临时目录 |
| **基建维护** | 规范 / 工具 / 运维 | 文档与 `tools/` 维护、目录与磁盘 |

角色是职责而不是产品名，可由任意等效工具承担；关键是四种职责不合并到同一个会话。完整流水线、角色 × 阶段矩阵、交接物与返工路径见 [`docs/PROCESS.md`](docs/PROCESS.md)。

---

## 目录

```text
MakeYourVideo/
├── README.md · LICENSE · .gitignore · .gitattributes
├── package.json                 Remotion 4.0.545 / React 19
├── requirements.txt             numpy / opencv / pillow / scipy / fonttools / playwright
├── docs/
│   ├── PROCESS.md               协作流程与四个卡点
│   ├── AGENTS.md                生产执行规范（目录、交付白名单、硬规则）
│   ├── STYLE_B_SILENT_VIBE.md   视觉与验收规范（2K、节奏、排版、编码、6 项验收）
│   └── PROMPT_TEMPLATE.md       分阶段执行指令模板
├── tools/
│   ├── bgm_common.py            FFmpeg 定位 / PCM 解码 / 时长探测
│   ├── bgm_analyze.py           测拍 → beats.json（BPM / 小节 / Drop）
│   ├── mix_bgm.py               卡 Drop + 前段铺底 + 断层自检 + 唯一成片
│   ├── decoder_check.py         硬解 vs 软解 NV12 对拍 + 编码档位审计
│   └── style_brief.py           从成片反推底色 / 色板 / 字阶
├── assets/
│   ├── bgm/README.md            自备 CC0 / 已授权配乐
│   └── fonts/README.md          三套 SIL OFL 1.1 字体的下载与放置
└── examples/nim_game/           可复现示例（纯源码，无产物）
```

---

## 环境依赖

| 依赖 | 要求 | 校验 |
|---|---|---|
| Node.js | `^20.19` / `^22.13` / `>=24` | `node -v` |
| Python | 3.11+（开发用 3.12） | `python -V` |
| FFmpeg / ffprobe | **9+**，含 `libx264`；硬解验收需 `d3d11va`（Windows） | `ffmpeg -version` |
| 磁盘 | 2K 成片 18–65 MB / 条，渲染中间物另需 1–2 GB | — |

> 硬解对拍只在 Windows D3D11VA 下有效；macOS / Linux 会退化为软解一致性与编码档位审计，属预期行为。

---

## 从零复现

```bash
# 1) Node 依赖
npm install

# 2) Python 依赖
python -m venv .venv
. .venv/Scripts/activate            # Windows；macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 3) 开源字体 → assets/fonts/（下载地址见 assets/fonts/README.md）
mkdir -p assets/fonts public/fonts
#   把 6 个字重文件放进 assets/fonts/，渲染前同步到 public/fonts/（Remotion staticFile 根）

# 4) 自备配乐 → assets/bgm/
cp <your-cc0-track>.m4a assets/bgm/
python tools/bgm_analyze.py assets/bgm/<your-cc0-track>.m4a

# 5) 生成示例的程序化道具并渲染（184s；先试 5 秒可加 --frames=0-300）
cd examples/nim_game && python src/gen_stones.py && cd ../..
cp examples/nim_game/src/assets/stone_v*.png public/
npm run render:example

# 6) 混音成唯一成片 + 硬解验收
python tools/mix_bgm.py \
  --video out/nim-cinema.mp4 \
  --bgm assets/bgm/<your-cc0-track>.m4a \
  --output out/nim.mp4 \
  --align-climax 122 \
  --sfx-out out/sfx_only.wav

python tools/decoder_check.py --video out/nim.mp4 --output out/decoder_check.json --strict
```

> 严格对齐 `docs/STYLE_B_SILENT_VIBE.md` §5.0 的 `-g 120 / -level:v 5.1` 时，用 Remotion 的 `--x264-params` 传入（不同版本参数名略有差异，以 `npx remotion render --help` 为准）。核心是**不要用 `slice-max-mbs`、多 slice、全 I 帧**——这三样会让 D3D11VA 解出纯灰块。

---

## 规范地图

| 想知道 | 去读 |
|---|---|
| 一条片怎么从选题走到交付、卡在哪 | `docs/PROCESS.md` |
| 目录、交付白名单、六条硬性规则 | `docs/AGENTS.md` |
| 2K 画幅、节奏、排版、线宽、编码、6 项验收 | `docs/STYLE_B_SILENT_VIBE.md` |
| 怎么给编码代理下指令 | `docs/PROMPT_TEMPLATE.md` |
| 工具参数 | `python tools/<script>.py --help` |

---

## 许可

- **本仓库代码与文档**：MIT，Copyright (c) 2026 **Heersley**。
- **Remotion**：自有许可，个人 / 小团队免费，**公司 ≥4 人需购买 Company License**；商用前阅读 <https://www.remotion.dev/license>。
- **字体**：Source Serif 4、寒蝉锦书宋 V2.0、Noto Sans SC、JetBrains Mono 均为 **SIL OFL 1.1**，可免费商用；字体文件不随仓库分发。
- **配乐**：仓库不含任何音频。请使用 **CC0 / 已获商用授权**的曲目；`tools/mix_bgm.py` 只做对齐与混音，不授予任何音乐版权。
- **示例内容**：`examples/nim_game/facts_and_sources.md` 中的事实与出处仅用于演示「一手 URL 闭环」的写法。

---

## 边界

这是**生产规范 + 工具链**仓库，不是成品视频仓库：不含成片、字体、配乐、QC 日志与任何个人环境配置。渲染产物、中间帧、验收 JSON 默认被 `.gitignore` 排除。
