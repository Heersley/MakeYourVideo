# assets/bgm — 配乐槽位

本仓库**不附带任何音频**。请自备 **CC0 / 已获商用授权**的曲目，放到本目录。

## 支持格式

`.m4a` / `.mp3` / `.wav` / `.flac`（解码由 FFmpeg 完成，采样率与声道自动转换到 48kHz 立体声）。

## 两步用法

```bash
# 1) 生成永久节拍档案（BPM / 小节 / Drop），产物为同目录 <同名>.beats.json
python tools/bgm_analyze.py assets/bgm/<your-track>.m4a

# 2) 混音时指定同一首曲子（顺带把微音效母带也传进去）
python tools/mix_bgm.py \
  --video out/<中间片>.mp4 \
  --bgm assets/bgm/<your-track>.m4a \
  --sfx examples/nim_game/src/sfx_mix.wav \
  --output out/<主题>.mp4 \
  --align-climax <高潮秒数>
```

> **默认槽位与命名**：`tools/bgm_common.py` 的默认槽位是 `assets/bgm/bgm.*`，按 `.m4a → .mp3 → .wav → .flac` 顺序探测。
> 也就是说，**只有把曲子命名成 `bgm.m4a`（或 `bgm.mp3` 等）时才能省略 `--bgm`**；用任意别的文件名，每次都必须显式传 `--bgm`，否则会提示找不到默认槽位。
> 想省事就直接 `cp <your-cc0-track>.m4a assets/bgm/bgm.m4a`。

## 节拍档案里有什么

`bpm` / `bar_sec` / `bar_times` / `beat_times` / `drops`（含 `t` 与 `rise_db`）/ `quiet_spans`。
写分镜前先读 `drops`：把画面高潮安排在某个 `drops[i].t` 上，`mix_bgm.py --align-climax` 就能把 Drop 精确对到该秒（误差 ≤0.03s）。

## `mix_bgm.py` 会做什么

1. 按 `--align-climax` 反推 BGM 起始偏移；
2. **正偏移时自动铺底**：从同曲挑整数小节（默认 16/8/4 自适应，可用 `--fill-bars` 指定）的最低能量段，等功率循环填满前段（比主高潮低 5 dB，默认 2400Hz 低通，0.4s 淡入），不再留白；
   - 曲目偏短、可用连续小节不足时会**自动降档**到 8/4/2 小节，并按可用长度放宽曲尾/Drop 保护边距，同时在 stderr 打 `[fill][warn]` 说明，**不会直接退出**；
3. 反转点前 0.45s 余弦洼谷；
4. 与微音效轨混合，`alimiter` + `ebur128` 实测，真峰值 ≤ −1.0 dBTP；
5. **全片断层自检**：`[0.5s, total−2.0s]` 内不得出现 `>1.5s` 的空白，结果写入 `bgm_mix_report.json`；
6. `-c:v copy` 封装，画面零损；可 `--sfx-out` 导出轻量 `sfx_only.wav` 备换乐。

## 微音效轨从哪来

`--sfx` 的优先级高于输入视频自带音轨：

| 情况 | 行为 |
|---|---|
| 传了 `--sfx <wav>` | 以该 WAV 为微音效母带，按输入视频实际时长裁剪/补零对齐（10s 冒烟片、Stage 1 快审片都适用） |
| 没传 `--sfx`，但中间片有音轨 | 从渲染中间片无损提取 |
| 都没传且中间片无音轨 | 按静音基线处理，`--sfx-out` 会额外打 warning 提示母带近似静音 |

> `examples/nim_game` 的 Remotion 合成里没有挂 `<Audio>`，所以 `npm run render:example` 出来的中间片**是无音轨的**。想让成片带那 25 个微音效，必须显式 `--sfx examples/nim_game/src/sfx_mix.wav`。

## 许可

`bgm_analyze.py` / `mix_bgm.py` 只做分析与混音，**不授予任何音乐版权**。商用前请自行确认曲目授权；商单换乐时用 `sfx_only.wav` + 新曲重混，不要重渲画面。
