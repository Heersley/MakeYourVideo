---
name: render-episode
description: >-
  Executes the isolated Render engineer workflow for a single MakeYourVideo
  episode from its src/plan.md. Use inside an isolated Render subagent (or a
  standalone Render session) to run snapshot, implement Remotion visuals,
  stereo SFX, evidenceScript, preview QC, directed rework, and ship.
---

# MakeYourVideo 单期 Render 工程师开工手册（隔离执行）

本 Skill 面向**独立隔离的 Render 子 Agent**（`self` 类型），也兼容独立的 Render 会话直接读盘接手。

## 开工必读与边界禁令

1. 每次开工或返工，先读：
   - 规范文档：`AGENTS.md`、`docs/AGENTS.md`、`docs/STYLE_B_SILENT_VIBE.md`、`docs/PRODUCTION.md`
   - 本期真相文件：`$ep/src/plan.md`、`$ep/beats.json`、`$ep/facts_and_sources.md`、`$ep/src/manifest.json`
   - 运行一次：`python -B tools/episode.py status $ep`（若仓库使用虚拟环境则使用 `.venv\Scripts\python.exe`），查看 `nextGate`、未关闭 `pending` 意见与保护项。
2. **严格禁令**：
   - **仅修改本期 `$ep` 目录内的源码与素材**；严禁改动 `tools/`、`tools/profiles/`、`core/vibe/`、`examples/` 等公共目录。
   - **严禁代导演签字**（不自行运行 `approve --gate review` 或 `approve --gate delivery`），未获有效 `review` 批准前严禁执行 `full` / `ship` / `finish`。
   - 遇到事实/分幕与 `src/plan.md` 矛盾或档案硬门槛无解时，立即停止并向主 Agent（或导演）汇报，不得擅改事实或绕过验收。

---

## 任务 1：首次实现与带声样片（`preview`）

1. **固定共享底座快照**：
   - 运行 `python -B tools/episode.py snapshot $ep`，将 `core/vibe/` 复制并绑定到本期 `src/vendor/vibe/`；单期源码一律相对导入 `./vendor/vibe/...`（严禁直接 import 仓库根 `core/vibe/`）。
   - 确认 `assets/fonts/` 下的 4 族 8 文件离线字体与许可已复制到本期 `publicDir/fonts/`（参考 `examples/diameter/prepare.py` 与 `assets/fonts/FONT-NOTICE.md`）。
2. **实现单期源码与资产**（按 `src/plan.md` 与 `docs/STYLE_B_SILENT_VIBE.md`）：
   - 实现 `src/entry.tsx`（注册样片与全片两个 Remotion Composition，共用原生画幅，持久舞台状态机，阅读窗文字锁定整数像素、`transform: none; filter: none; opacity: 1`，顶部主句与底部读数移出摄影机容器）。
   - 生成与时间轴同源的 2 声道立体声微音效 WAV（参考 `examples/diameter/prepare.py` 中调用 `./vendor/vibe/sfx_engine.py` 的 `render_sfx`），确保峰值贴合制作档案 `sfxPeak`。
   - 编写 `src/evidence/frames.py`（调用 `tools/evidence_kit.py` 的 `main`，填写正式时间轴的 `cover_frame` 与 `still_frames={"prop": ..., "trail": ..., "climax": ...}`），并在 `src/manifest.json` 补全 `evidenceScript`、`bgm`、`licenseNote` 等字段。
3. **预检与快审渲染**：
   - 运行 `python -B tools/episode.py plan $ep --mode preview` 与 `python -B tools/episode.py preflight $ep --mode preview`，清零类型检查、契约、字体与依赖报错。
   - 运行 `python -B tools/episode.py preview $ep`（长任务可用 `--detach` 搭配 `job $ep --wait 30 --tail 20` 跟踪）。
4. **回报前强制自检**：
   - 用 `read_file` 读取 `src/review/preview_qc.json`，确认 `passed === true`、4 族 8 字体全部生效、阅读窗/接缝/光场全部达标。
   - 用 `read_file` 亲眼检查 `src/review/prop.png`、`trail.png`、`climax.png`、`phone.png`，核查无字压图、无越界、360px 缩略图线宽与标注清晰、画面纯净无杂音。
   - 发现未通过或视觉硬伤时，先在当前子 Agent 内修完重跑 `preview`，全部过关后再回报主 Agent。
5. **汇报并待命**：
   - 简洁汇报 `src/review/preview.mp4` 与四张静图路径、`preview_qc.json` 关键实测值及需导演关注处；随后静默待命。

---

## 任务 2：定向返工（收到返工指令时）

1. 运行 `python -B tools/episode.py status $ep`，读取 `pending` 意见 ID、`scope`、`protect` 保护项与导演原话。
2. 仅修改指定范围，守住保护项，核查相邻接缝、阅读窗与总时长。
3. 重跑受影响的 `preview`（仅调混音增益且母版未变时可用 `remix`），用 `read_file` 复核更新后的 `preview_qc.json` 与静图。
4. 用真实证据文件关闭意见：
   `python -B tools/episode.py resolve $ep --request <意见ID> --note '<实际验证结果>' --evidence <相对$ep的真实证据路径>`
5. 向主 Agent 汇报修改内容、关闭的意见 ID 与新快审产物路径，继续待命。

---

## 任务 3：全片交付（仅在获知 `review` 正式签字后）

1. 运行 `python -B tools/episode.py status $ep`，确认 `nextGate` 为 `"delivery"` 且无未关闭 `pending` 意见。
2. 运行一键交付链：
   `python -B tools/episode.py ship $ep --clean-abandoned`
   （如需中断续跑，按 `docs/PRODUCTION.md` 使用 `--work <run目录>` 续跑。）
3. `ship` 完成后，用 `read_file` 核查 `cover.png`、`contact_sheet.png`、`src/final_qc.json` 与 `bgm_mix_report.json`，确认 `verify` 通过且交付根目录七件齐全。
4. 向主 Agent 汇报最终产物路径、六项验收实测摘要与真实目视记录。**严禁自行执行 `approve --gate delivery`**。
