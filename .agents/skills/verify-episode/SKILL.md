---
name: verify-episode
description: >-
  Runs an independent, strictly read-only verification audit on a finished
  MakeYourVideo episode before Director delivery sign-off. Use inside an
  isolated Verifier subagent to check tools/episode.py verify, seven delivery
  artifacts, cover/contact_sheet/phone visuals, and fact sources without
  modifying any files.
---

# MakeYourVideo 单期独立只读复检手册（Verifier）

本 Skill 用于在导演签字 `delivery` 前，以**全新独立、严格只读**的上下文复检本期交付产物，避免 Render 编写者盲区。

## 严格只读禁令

- **严禁**新建、修改、移动或删除仓库内任何文件（不调用写/改文件工具，不运行会写盘的命令）。
- **严禁**执行 `approve`、`finish`、`ship`、`preview`、`full`。
- 发现任何问题如实取证并向主 Agent 汇报，不得静默忽略。

## 复检清单

1. **程序只读复验**：
   - 运行 `python -B tools/episode.py status $ep`，确认 `pending` 为空且 `nextGate == "delivery"`。
   - 运行 `python -B tools/episode.py verify $ep`，核对 `passed: true`，记录媒体 SHA-256、集成响度、真峰值、硬解对拍结果与归档制作档案版本。
2. **交付根目录七件白名单检查**：
   - 核对 `$ep` 根目录只包含七项：`<主题>.mp4`、`bgm_mix_report.json`、`beats.json`、`contact_sheet.png`、`cover.png`、`facts_and_sources.md`、`src/`；确认 `src/plan.md` 与 `src/sfx_only.wav` 均在 `src/` 内。
3. **目视核查（必用 `read_file` 实际看图）**：
   - 检查 `cover.png`、`contact_sheet.png` 与 `src/review/phone.png`：画面纯净无杂音、主句排版清晰无压图、安全区无越界、360px 缩略图下主结构与辅助线清晰可辨。
4. **事实与出处核对**：
   - 读取 `facts_and_sources.md` 与 `beats.json`，核对上屏关键论断、年份、数值、公式与素材授权均有清晰记录，无明显口径矛盾。

## 回报格式

向主 Agent 输出简洁的结构化结论：
- **总体结论**：`PASS（可呈交导演 delivery 终审）` 或 `FAIL（须打回返工）`
- **程序校验摘要**：`verify` 结果、响度/真峰值、硬解对拍、七件白名单状态
- **目视核查记录**：对 `cover.png`、`contact_sheet.png`、`phone.png` 的实际观察
- **问题列表（如有）**：按「归属（Render / Architect）+ 具体幕号或文件 + 实测证据」逐条列出
