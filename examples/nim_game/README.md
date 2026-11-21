# examples/nim_game — 完整参考实现（1080p）

一条 184 秒、31 幕的无声科普片，用来演示**持久舞台状态机怎么写、验收脚本怎么跑**。

> ⚠️ **这是 2K 规范升级前的产物**：`1080×1920 @ 60fps` / `High@4.2` / 双版交付。
> 现行规范已升至 `1440×2560 @ 60fps` / `High@5.1` / 唯一成片（见 `docs/STYLE_B_SILENT_VIBE.md`）。
> **学结构可以，编码参数不要照抄**：新片必须把 `-level:v` 改成 `5.1`，并按 §5.0.1 流式直出。

## 元数据

| 项 | 值 |
|---|---|
| 标题 | 尼姆博弈 |
| 时长 / 帧数 | 184.0s / 11,040 帧 @60fps |
| 光场 | `studio_dark` |
| 资产层 | `vector` + `2.5d_parallax` |
| 分幕 | 31 幕；10 个走子动作；25 个音效事件 |
| 高潮对齐 | `alignClimaxSec = 122.0` |
| 时长档 | `long`（140–240s） |

## 目录

```text
examples/nim_game/
├── README.md
├── beats.json                  # 31 幕连续时间轴（分幕 / 气口 / 硬切 / 音效 / 走子）
├── facts_and_sources.md        # 一手 URL 闭环示例
└── src/
    ├── entry.tsx               # registerRoot：NimCinema / NimReview / NimStoneCloseup
    ├── Nim.tsx                 # 顶层：按 frame 驱动的持久舞台
    ├── Game.tsx                # 石子堆、卡爪、台座、精灵预加载
    ├── Proof.tsx               # 二进制权重矩阵与证明段
    ├── Narration.tsx           # 四段式文字生命周期与尾迹
    ├── Type.tsx / Fonts.tsx    # 字阶、滚字、`@font-face` 加载与校验
    ├── Epilogue.tsx / stage.tsx / Motion.ts / preview_layout.tsx
    ├── gen_stones.py           # 程序化石子精灵（2× 超采样）+ stone_geometry.json
    ├── gen_sfx.py              # 程序合成微音效 → sfx_mix.wav
    ├── bounds.py               # Playwright 版面边界 / 碰撞检查
    ├── preview_qc.py           # 快审片：帧差、静止窗、光场
    ├── full_qc.py              # 全片 QC：死帧、接缝、文字框、编码
    └── assets/
        ├── stone_geometry.json # gen_stones.py 的产物（保留以便直接编译）
        └── fonts/headline_metrics.json  # 字阶测量数据
```

## 从零复现

```bash
# 0) 在仓库根目录装依赖
npm install
pip install -r requirements.txt
playwright install chromium         # 只有要跑下面的 QC 脚本才需要

# 1) 字体 → public/fonts/（见 assets/fonts/README.md；public/ 不在仓库里，要先建）
mkdir -p public/fonts

# 2) 程序化道具：生成 4 个石子精灵 + 几何数据
cd examples/nim_game
python src/gen_stones.py            # 输出到 src/assets/stone_v0..3.png 与 stone_geometry.json
cp src/assets/stone_v*.png ../../public/

# 3) 微音效（混音阶段要显式传给 mix_bgm.py --sfx，不传就不会进成片）
python src/gen_sfx.py               # 输出 src/sfx_mix.wav（约 35 MB，已被 .gitignore 排除）

# 4) 渲染（184s 全片；先试 10 秒用 --frames=0-599）
cd ../..
npm run render:example              # → out/nim-cinema.mp4（已内置 --color-space=bt709）

# 5) 混音成唯一成片（注意 --sfx）
python tools/bgm_analyze.py assets/bgm/<your-track>.m4a
python tools/mix_bgm.py --video out/nim-cinema.mp4 --bgm assets/bgm/<your-track>.m4a \
  --sfx examples/nim_game/src/sfx_mix.wav \
  --output out/nim.mp4 --align-climax 122 --sfx-out out/sfx_only.wav

# 6) 验收
python tools/decoder_check.py --video out/nim.mp4 --output out/decoder_check.json --strict
```

> **本示例的渲染中间片没有音轨**：`entry.tsx` 的三个 composition 都没有挂 `<Audio>`，`sfx_mix.wav` 不会自动混进去。必须用 `--sfx` 显式指定，否则成片只有 BGM（`--sfx-out` 会是近似静音母带，工具会打 warning）。
>
> **`--frames` 是闭区间**：`--frames=0-599` = 600 帧 = 10.0 s @60fps；`0-299` 才是 5.0 s。
>
> **自己手写渲染命令时**：务必带 `--pixel-format=yuv420p --color-space=bt709`，否则 Remotion 默认输出 full-range `yuvj420p`，`decoder_check.py` 的 `yuv420p` 基线会判失败。

### 版面 / 快审 QC 怎么跑

```bash
cd examples/nim_game

# 锁定输入自检（不跑浏览器，最快）
python src/preview_qc.py --verify-locks

# 版面自检（31 幕 DOM 边界 + 字体平台采样，需要 public/fonts 已就位）
python src/preview_qc.py .work/lay --layout-only
python src/full_qc.py .work/fq --layout-only
python src/bounds.py --work .work/bounds
```

> `full_qc.py` 的完整流程需要一份**原生 PNG 序列**（`<work>/frames/element-*.png`，11040 帧）。
> 仓库不提供该序列，也没有内置导出命令；需要时自己用 `remotion render ... --sequence --image-format=png`
> 生成后再跑，否则会报 `No native Remotion PNGs were found in <work>/frames`。
>
> 三个 QC 脚本的 `work` 目录必须位于 `examples/nim_game/.work/` 之内（脚本会校验）。
> 快审视频流程还依赖 `examples/nim_game/review/stone_closeup_check.png` 这类 Stage 1 留存产物，
> 干净克隆下没有，因此 `preview_qc.py` 的**完整**（非 `--layout-only`）模式跑不通，属预期。

## 与现行 v3.3 的差异

| 项 | 本示例（v3.2 时代） | 现行 v3.3 |
|---|---|---|
| 画幅 | 1080×1920 | **1440×2560** |
| 编码档 | `High@4.2` | **`High@5.1`** |
| 交付 | `_cinema_clean` + `_with_bgm` 双版 | **唯一 `<主题>.mp4`** |
| 快审 | 540×960 / 1080×1920 静音或单轨 | **720×1280@30 带 BGM+SFX** |
| 死帧口径 | 全屏 `delta<0.15`、≤1.20s | **ROI `y:720–1866`、`roi_delta<0.05`、≤1.80s** |
| 文字 | 三段式（入场/定格/出场） | **四段式（含幕首气口 + 幕尾余白）** |
| 线宽 | 未分级 | **L1/L2/L3 分级** |

> `beats.json` 里的 `preview` 字段仍记录 540×960@30，属历史值；脚本清单中的 `full_qc.py` 也仍按旧的双版命名（`*_cinema_clean.mp4` + `sfx_mix.wav`）工作——**它们是参考实现，不是现行交付流程**。

## 已知缺口（按 `.gitignore` 未入库）

- 字体、石子 PNG、`sfx_mix.wav`、各类 `*_qc.json` / `bounds.json`、渲染成片；
- **原生 PNG 帧序列**（`full_qc.py` 的输入）：仓库不含，也没有内置导出命令，需自行
  `remotion render examples/nim_game/src/entry.tsx NimCinema <work>/frames/element --sequence --image-format=png`；
- **Stage 1 留存产物**（`review/stone_closeup_check.png`、`review/text_exit_*.png` 等）：
  `preview_qc.py` 的完整模式（非 `--layout-only`）依赖它们做帧差与尾迹对比，干净克隆下必然缺失；
- `publish_stage2.py` 与 `render*.ps1` 未包含：前者绑定旧双版交付，后者是本地渲染编排。

> 三个 QC 脚本（`bounds.py` / `preview_qc.py` / `full_qc.py`）已跨平台化：FFmpeg 走
> `FFMPEG_BIN → PATH → WinGet` 兜底，Chromium 优先用 Remotion 自带的 `chrome-headless-shell`、
> 缺失时回落 Playwright 自带浏览器。但 `full_qc.py` 的编码审计仍按 Windows D3D11VA 口径设计，
> macOS / Linux 上只能得到软解一致性结论。

## 读代码的顺序

1. `entry.tsx` → 看三个 composition 的尺寸与帧数；
2. `Nim.tsx` → 看全局 `frame` 如何驱动整条时间轴（状态机入口）；
3. `Narration.tsx` → 看文字四段式与尾迹包络（本片仍是三段式，可对照 `docs/STYLE_B` §3.2 升级）；
4. `Game.tsx` → 看程序化精灵、接触投影、卡爪四段曲线；
5. `full_qc.py` → 看程序验收怎么把「感觉」变成数字。
