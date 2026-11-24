# 单期制作约定

1. 先读[根规则入口](../AGENTS.md)、[制作手册](PRODUCTION.md)和[视听规范](STYLE_B_SILENT_VIBE.md)，再从本期的 `src/plan.md`（如有）、`beats.json`、`facts_and_sources.md` 和 `src/manifest.json` 接手。
2. 每次制作一条片，一集一个独立主会话（严禁在同一长会话连续渲染多片）。策划时确认题材、一手来源、素材授权和分幕，并检查图形/物理隐喻与原理方向一致；上屏论断须回溯到原始论文、官方文件、公版原著或其他一手出处。
3. 策划与渲染保持上下文隔离：支持子 Agent 编排的客户端按 `.agents/skills/` 由主对话自动拉起隔离的 Render 与只读 Verifier 子 Agent；其他客户端通过 `src/plan.md` 与 `tools/episode.py status` 做跨会话磁盘交接。
4. 源码先固定底座快照并从本期 `src/vendor/vibe/` 相对导入公共原语；单期渲染上下文禁止修改 `tools/`、`tools/profiles/`、`core/vibe/` 与 `examples/`。按绑定档案生成样片并保留取证，获导演确认 `review` 后才能制作全片。
5. 完成混音、六项验收、只读复验与归档后，由导演确认 `delivery`。按实际反馈登记签字和返工记录，严禁代导演签字。
