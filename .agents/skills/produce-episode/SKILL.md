---
name: produce-episode
description: >-
  Orchestrates end-to-end single-window silent science video production in
  MakeYourVideo (evergreen_vibe). Use when the user starts a new episode,
  discusses topic/facts/beats/visual plan, hands off to Render, reviews
  preview/full artifacts, requests revisions, or finalizes delivery in one
  conversation without manually switching chats.
---

# MakeYourVideo 单窗口自动生产流（Coordinator + Architect）

本 Skill 用于在支持子 Agent 的客户端（如 Antigravity）中，用**单一主对话**完成整集 `evergreen_vibe` 无旁白科普短片的全流程制作：**主对话担任总控与 Architect**，编码渲染与终审复检由主对话自动拉起**独立隔离的满血 `self` 子 Agent** 执行，免去开两个窗口手动传话，同时严格守住上下文隔离与两处人工签字卡点。

## 开工前必读与硬边界

1. 先读仓库规范：`AGENTS.md`、`docs/AGENTS.md`、`docs/STYLE_B_SILENT_VIBE.md`、`docs/PRODUCTION.md`、`docs/prompt.md`。若接手已有单期目录，先执行：
   `python -B tools/episode.py status $ep`（如仓库使用虚拟环境，将 `python` 替换为 `.venv\Scripts\python.exe`）。
2. **单片单会话**：一个主对话只制作一部短片；本片完成 `delivery` 或中止后，下一片请导演新开会话。
3. **两处程序强制卡点**：`review`（带声样片确认）与 `delivery`（终审采纳）必须停等导演明确原话，严禁代签、预签或越权执行 `full` / `ship` / `finish`。
4. **上下文隔离**：主对话不直接编写单期 Remotion 业务代码或执行长渲染，一律交由隔离的 Render 子 Agent 在零聊天污染的上下文中完成。
5. **配乐与字体**：确认 `assets/fonts/` 已按 `assets/fonts/FONT-NOTICE.md` 备齐 4 族 8 个字体文件；使用自备且获授权的配乐时，按 `assets/bgm/README.md` 运行 `bgm_analyze.py` 并在清单写明 `bgm` 与 `licenseNote`。

---

## 流程 A：策划对齐与落盘（主对话担任 Architect）

1. 与导演明确本期目录（`output/evergreen_vibe/YYYY-MM-DD/NN_主题/`）、选题目标、光场（`studio_dark` / `keynote_light`）、节奏与素材限制（未明确前先沟通，不猜题）。
2. 完成事实与逻辑核查：
   - 全部上屏论断、年份、人物、文献、数值与公式回溯到一手来源（原始论文、官方文件、公版原著等），查不到出处则删去并告知导演。
   - 书面核对物理/几何/力学隐喻的方向与因果一致性。
   - 涉及外部图片、档案或配乐时，定稿前确定授权状态。
3. 规划完整分幕（起止整数帧、上屏短主句、核心视觉演化、左闭右开阅读窗、微音效时间、转场与高潮点），确定制作档案（默认 `vibe-3.3`；确需单幕时长例外时选用 `vibe-3.4` 并列出 `overrides`）。
4. 导演确认分幕方向后，直接将以下策划文件落盘到本期目录 `$ep`：
   - `facts_and_sources.md`（参考 `examples/diameter/facts_and_sources.md`）
   - `beats.json`（严格符合 `tools/contracts/beats.schema.json`）
   - `src/manifest.json`（初始清单，严格符合 `tools/contracts/manifest.schema.json`）
   - `src/plan.md`（完整单期制作方案：视觉世界观、色板、逐幕演法、常量与音色方案；位于 `src/` 内，不占用交付根目录七件白名单，也不改变内容指纹）
5. 向导演汇报落盘文件与关键核查结果，**停等导演确认「策划定稿，可以开渲」**。

---

## 流程 B：自动派发独立 Render 子 Agent（快审 `preview`）

收到导演开渲确认后：

1. 调用 `invoke_subagent` 启动隔离 Render 子 Agent：
   - `TypeName`: `"self"`（完整继承当前模型、全部工具与仓库规则/技能，且拥有全新干净上下文）
   - `Model`: `"inherit"`
   - `Role`: `"Episode Render Engineer"`
   - `Workspace`: `"inherit"`
   - `Prompt`（保持极简，严禁把前期策划聊天记录粘贴进去）：
     ```text
     你是本期短片的独立 Render 工程师。
     1. 先完整读取 `.agents/skills/render-episode/SKILL.md` 并严格按其中步骤与红线执行。
     2. 本期目录（$ep）：<单期绝对或相对路径>
     3. 当前任务：完成 core/vibe snapshot、单期 Remotion 源码/立体声 SFX/evidenceScript 实现、preflight 与 preview 快审渲染，并在回报前完成 preview_qc.json 与四张静图自检。
     4. 严禁越过 review 卡点执行 full/ship/finish，严禁代签 approve。完成后向我汇报产物路径与实测摘要并待命。
     ```
2. 记录返回的 `conversationId`（记为 `render_agent_id`），用于后续返工与放行 `ship`。
3. 结束本轮工具调用，等待系统自动推送完成消息（不轮询）。

---

## 流程 C：原地 `review` 审片与返工闭环

收到 Render 子 Agent 的快审汇报后：

1. 用 `read_file` 核对 `src/review/preview_qc.json` 的 `passed` 与核心实测项；若未通过或存在明显硬伤，先用 `send_message` 打回 Render 子 Agent 修完，再呈交导演。
2. 将 `src/review/preview.mp4`、`prop.png`、`trail.png`、`climax.png`、`phone.png` 路径与 QC 摘要呈交导演，**停等导演明确原话**。
3. 按导演原话分流：
   - **画面 / 动效 / 排版 / 音频返工**：
     1. 主对话执行 `python -B tools/episode.py handoff $ep --owner Render --scope <幕号或范围> --protect '<保护项>' --note '<导演原话>' --evidence src/review/preview.mp4`；
     2. 用 `send_message(Recipient=render_agent_id, Message=...)` 派回**同一个** Render 子 Agent 读取 `status $ep`、定点修复、重跑快审并用 `resolve` 关闭意见。（仅当原 `render_agent_id` 不可达时才新拉 `self` 子 Agent 接手磁盘记录。）
   - **事实 / 数值 / 隐喻 / 分幕改动**：
     1. 主对话（Architect）先修订 `facts_and_sources.md`、`beats.json`、`src/plan.md`（必要时同步 `src/manifest.json`）；
     2. 登记 `handoff` 后通过 `send_message` 通知 Render 子 Agent 同步修改并重新提交快审。
   - **导演明确给出 `review` 确认原话**：
     1. 主对话执行 `python -B tools/episode.py approve $ep --gate review --note '<导演确认原话>'`；
     2. 签字成功后，立即用 `send_message(Recipient=render_agent_id, Message=...)` 通知 Render 子 Agent 执行 `ship`（`full`、响度闭环、取证、`finish` 与 `verify`），严禁代签 `delivery`。

---

## 流程 D：独立只读复检与原地 `delivery` 终审

收到 Render 子 Agent 的 `ship` 完成汇报后：

1. 自动拉起独立只读 Verifier 子 Agent：
   - `TypeName`: `"self"`
   - `Model`: `"inherit"`
   - `Role`: `"Independent Read-Only Verifier"`
   - `Workspace`: `"inherit"`
   - `Prompt`：
     ```text
     你是本期成片的独立只读复检员。
     1. 先读取 `.agents/skills/verify-episode/SKILL.md` 并严格遵守全部只读禁令（严禁修改任何文件）。
     2. 对单期目录 <单期路径> 执行只读复检，汇报逐项结论与目视观察。
     ```
2. 收到 Verifier 汇报后：
   - 若有未通过项或明显缺陷：保留失败状态，按归属派回 Render 或由 Architect 修正后重验；
   - 若复检全绿：将交付根目录七件清单（`<主题>.mp4`、`cover.png`、`contact_sheet.png`、`bgm_mix_report.json`、`beats.json`、`facts_and_sources.md`、`src/`）与复检摘要呈交导演，**停等导演终审采纳原话**。
3. 收到导演明确采纳原话后：
   - 执行 `python -B tools/episode.py approve $ep --gate delivery --note '<导演终审采纳原话>'` 与 `python -B tools/episode.py status $ep`（确认 `nextGate` 为 `done`），本会话结案。
