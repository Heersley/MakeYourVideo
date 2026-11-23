# 单期协作流程

| 职责 | 交接内容 |
|---|---|
| Director | 在策划时确认选题、事实和分幕，在制作时登记 `review` 与 `delivery`。 |
| Architect | 核查一手来源与素材授权，提交 `beats.json`、`facts_and_sources.md` 和清单所需的制作参数。 |
| Render | 固定 `core/vibe 1.2.0` 随片快照，制作画面和微音效，用 `evidence_kit` 提交样片及正式取证。 |
| Infra & Verifier | 维护版本化档案、共享底座和工具，使用 `verify` 只读复验交付。 |

1. 策划定稿后，Render 以本期清单和分幕运行 `preview`，将带声样片、关键静帧、手机缩略图和取证报告交给 Director。
2. Director 看完样片后登记 `review`。批准绑定本期内容及已审样片的摘要。分幕、源码、素材或配乐变更后递交新样片。
3. Render 运行 `ship`，依次完成全片渲染、响度校准、取证、验收和归档。复验后本期等待 `delivery`。
4. Director 核对成片和交付物后登记 `delivery`。返工意见用 `handoff` 和 `resolve` 留档，记录受影响的内容与复验证据。

命令、相对路径和单期文件结构见[制作手册](PRODUCTION.md)。
