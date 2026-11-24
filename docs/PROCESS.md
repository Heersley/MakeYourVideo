# 单期协作流程

| 职责 | 交接与边界 |
|---|---|
| Director | 在策划时确认选题、事实和分幕，审看样片与成片并分别登记 `review` 与 `delivery`。 |
| Architect（主对话总控） | 核查一手来源、物理隐喻与素材授权，将 `beats.json`、`facts_and_sources.md`、初始 `src/manifest.json` 与单期制作方案 **`src/plan.md`** 直接落盘；在单窗口自动流中负责拉起与调度隔离的子 Agent，并统一登记 `handoff` / `approve`。 |
| Render（隔离执行） | 在零历史聊天污染的独立上下文中读取 `src/plan.md`，固定 `core/vibe 1.2.0` 随片快照，编写 Remotion 画面与立体声微音效，用 `evidence_kit` 提交样片及全片取证，完成定向返工与 `ship`。不在单期渲染内改动 `tools/`、`tools/profiles/`、`core/vibe/`。 |
| Verifier（独立只读复检） | `ship` 完成后以全新只读视角运行 `tools/episode.py verify`、核查交付七件白名单并目视复核封面、联系表与手机缩略图；严格只读，不修改任何文件。 |

公共工具、版本化制作档案与共享底座按需在单独的基建维护会话中迭代并跑通 `tools/tests/` 回归，不再常驻独立的运维 Agent。

## 两种运行方式

- **单窗口自动流（推荐，支持子 Agent 的客户端如 Antigravity）**：一集只开一个主对话，通过仓库内置的 [`produce-episode`](../.agents/skills/produce-episode/SKILL.md)、[`render-episode`](../.agents/skills/render-episode/SKILL.md) 与 [`verify-episode`](../.agents/skills/verify-episode/SKILL.md) 三份 Skill 自动串联：主对话完成策划落盘 → 导演确认后自动拉起满血隔离的 `Render` 子 Agent 完成 `preview` → 导演在同一窗口审片，返工时主对话登记 `handoff` 并直接通过 `send_message` 发回**同一个待命中的 `Render` 子 Agent**（保留代码上下文）→ `review` 签字后放行 `ship` → 自动拉起只读 `Verifier` 子 Agent 复检 → 导演在同一窗口确认 `delivery`。
- **多会话磁盘交接（通用兼容模式）**：不支持子 Agent 的工具可先用[策划模板](prompt.md)完成策划并落盘 `src/plan.md` 等文件，再新开独立的 Render 会话直接读盘开工，交付前另开只读会话运行 `tools/episode.py verify` 复检。若会话中途关闭或切换，新会话通过 `tools/episode.py status` 从磁盘读取下一卡点与未关闭意见无缝续接。

## 单期推进顺序

1. 策划定稿并落盘 `src/plan.md`、`beats.json`、`facts_and_sources.md` 与 `src/manifest.json` 后，Render 运行 `preview`，将带声样片、关键静帧、手机缩略图和取证报告交回 Director。
2. Director 看完样片后登记 `review`。批准绑定本期内容及已审样片的摘要；分幕、源码、素材或配乐变更后须重新递交样片。
3. Render 运行 `ship`，依次完成全片渲染、响度校准、取证、验收和归档；随后由独立只读 Verifier 执行 `verify` 与目视复检，本期停在 `delivery`。
4. Director 核对成片和交付物后登记 `delivery`。返工意见用 `handoff` 和 `resolve` 留档，记录受影响的范围、保护项与复验证据。

命令、相对路径和单期文件结构见[制作手册](PRODUCTION.md)。
