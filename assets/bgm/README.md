# assets/bgm — 配乐槽位

本仓库**不附带任何音频**。请自备 **CC0 / 已获商用授权**的曲目，放到本目录。

## 支持格式

`.m4a` / `.mp3` / `.wav` / `.flac`（解码由 FFmpeg 完成，采样率与声道自动转换到 48kHz 立体声）。

## 两步用法

```bash
# 1) 生成永久节拍档案（BPM / 小节 / Drop），产物为同目录 <同名>.beats.json
python tools/bgm_analyze.py assets/bgm/<your-track>.m4a

# 2) 混音时指定同一首曲子
python tools/mix_bgm.py \
  --video out/<中间片>.mp4 \
  --bgm assets/bgm/<your-track>.m4a \
  --output out/<主题>.mp4 \
  --align-climax <高潮秒数>
```

> `tools/bgm_common.py` 的默认槽位是 `assets/bgm/bgm.*`（`mix_bgm.py` 不传 `--bgm` 时自动找它）。
> 用别的文件名时，**每次都要显式传 `--bgm`**，否则会提示找不到默认槽位。

## 节拍档案里有什么

`bpm` / `bar_sec` / `bar_times` / `beat_times` / `drops`（含 `t` 与 `rise_db`）/ `quiet_spans`。
写分镜前先读 `drops`：把画面高潮安排在某个 `drops[i].t` 上，`mix_bgm.py --align-climax` 就能把 Drop 精确对到该秒（误差 ≤0.03s）。

## `mix_bgm.py` 会做什么

1. 按 `--align-climax` 反推 BGM 起始偏移；
2. **正偏移时自动铺底**：从同曲挑 4/8/16 整数小节的最低能量段，等功率循环填满前段（比主高潮低 5 dB，默认 2400Hz 低通，0.4s 淡入），不再留白；
3. 反转点前 0.45s 余弦洼谷；
4. 与视频里的微音效轨混合，`alimiter` + `ebur128` 实测，真峰值 ≤ −1.0 dBTP；
5. **全片断层自检**：`[0.5s, total−2.0s]` 内不得出现 `>1.5s` 的空白，结果写入 `bgm_mix_report.json`；
6. `-c:v copy` 封装，画面零损；可 `--sfx-out` 导出轻量 `sfx_only.wav` 备换乐。

## 许可

`bgm_analyze.py` / `mix_bgm.py` 只做分析与混音，**不授予任何音乐版权**。商用前请自行确认曲目授权；商单换乐时用 `sfx_only.wav` + 新曲重混，不要重渲画面。
