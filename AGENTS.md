# AGENTS.md — MakeYourVideo 工程入口约定

开工先读本文件，再按需阅读 [单期制作约定](docs/AGENTS.md)、[协作流程](docs/PROCESS.md)、[视听规范](docs/STYLE_B_SILENT_VIBE.md) 与 [制作手册](docs/PRODUCTION.md)。

## 1. 核心红线

- **单片单会话隔离**：每次制作一条无旁白科普短片（`output/evergreen_vibe/YYYY-MM-DD/NN_主题/`）；严禁在同一个长会话连续渲染多条全片，下一期请新开会话。
- **两处强制人工卡点**：程序强制停等导演实际确认 `review`（带声样片确认）与 `delivery`（终审采纳）。严禁代导演签字，严禁在未获有效 `review` 批准前执行 `full` / `ship` / `finish`。仓内 [`.agents/hooks.json`](.agents/hooks.json) 的 `PreToolUse` 安全钩子会对 `episode.py approve` 强制触发宿主 `force_ask` 人工确认弹窗（无视自动放行缓存），并对 `git gc` / `git prune` 直接 `deny` 拦截。
- **入口预检与静态 Lint**：`preflight` 通过 [`tools/check_entry.cjs`](tools/check_entry.cjs) 执行 TypeScript 类型检查与高精度 AST 静态 Lint（硬拦截禁用系统字体 `Microsoft YaHei` / `SimSun` / `SimHei` / `STZhongsong` 及未显式设置 `overshootClamping: true` 的 Remotion `spring()` 调用；动态变量引用报 Warning）。
- **模型能力要求**：建议使用具备强推理、多模态看图（核查静帧/联系表）与子 Agent 编排能力的旗舰模型，不绑定特定厂商或版本号。
- **事实与素材前置**：上屏年份、人物、文献、数值、公式须回溯一手出处并写入 `facts_and_sources.md`；素材与配乐使用前确认授权；图形/物理隐喻方向须与命题一致。
- **底座快照隔离**：单期源码先运行 `python -B tools/episode.py snapshot $ep`，并从本期 `src/vendor/vibe/` 相对导入公共原语；禁止直接 import 仓库根 `core/vibe/`。
- **职责边界**：单期渲染上下文禁止修改 `tools/`、`tools/profiles/`、`core/vibe/`、`examples/`；公共基建升级另开独立维护会话并跑通 `tools/tests/` 回归。

## 2. 推荐协作架构：单窗口多 Agent 自动流

仓库在 `.agents/skills/` 内置三份标准 Agent Skills，支持子 Agent 编排的客户端（如 Antigravity）克隆后打开仓库根即可自动发现，实现**一集只开一个主对话、免手动跨窗口粘贴提示词**，同时保持策划与渲染的上下文物理隔离：

1. **主对话（总控 + Architect）** — [produce-episode](.agents/skills/produce-episode/SKILL.md)：与导演对齐选题、核查一手来源与隐喻，将 `facts_and_sources.md`、`beats.json`、初始 `src/manifest.json` 与单期制作方案 **`src/plan.md`** 直接落盘；导演确认后自动拉起隔离的 `Render` 子 Agent，统一管理 `handoff` / `approve` 与审片呈报。主对话不直接编写单期 Remotion 业务代码或执行长渲染。
2. **Render 子 Agent（隔离满血 `self` 上下文）** — [render-episode](.agents/skills/render-episode/SKILL.md)：以零历史聊天污染的独立上下文读取 `src/plan.md` 与规范，完成 `snapshot`、单期源码/立体声 SFX/取证脚本实现、`preview` 与静图自检、同会话定向返工（主对话通过 `send_message` 复用同一子 Agent）及 `ship`。
3. **Verifier 子 Agent（独立只读上下文）** — [verify-episode](.agents/skills/verify-episode/SKILL.md)：`ship` 完成后自动拉起，执行严格只读 `verify`、目视核查 `cover.png` / `contact_sheet.png` / `src/review/phone.png` 及事实口径复核，全绿后呈交导演确认 `delivery`。

> 不支持子 Agent 的客户端或网页对话，同样可借助落盘的 **`src/plan.md`** 与 `tools/episode.py status` 做双会话磁盘交接（见 [策划模板](docs/prompt.md) 与 [协作流程](docs/PROCESS.md)）。
