# 单片接手与复验

从工程根运行 `python -B tools/episode.py --help`。每次指定一个单期目录。新会话先运行 `status`，从 `pending` 和 `history` 读取导演原话、幕号、保护项、已有证据和下一角色。命令负责本地交接，与聊天软件的唤醒、账户及外部消息无关。

程序只强制两处人工签字：`review`（样片确认，签后放行 `full` / `ship`）与 `delivery`（终审采纳）。选题与事实在策划对话中确认，工具不再要求 `approve --gate topic|facts`；旧单期已写入的这两类记录原样保留，只作历史留痕，`status.nextGate` 依次为 `review` → `delivery` → `done`。

## 单期目录与选题

在 `output/evergreen_vibe/YYYY-MM-DD/NN_主题/` 工作，日期取首次交付日，同日两位编号递增。一张选题卡对应一部片。卡片在 `inbox/evergreen_vibe/`，frontmatter 必填 track、lighting、asset_layers、cut_mode、status、date、duration_tier。track 取 evergreen_vibe，lighting 取 studio_dark 或 keynote_light，素材层可组合 vector、3d、2.5d_parallax；cut_mode 取 cinema 或 rhythmic，长片须显式声明 long。缺项交回 Architect 与导演确认。

交付根目录七项为 `<主题>.mp4`、`bgm_mix_report.json`、`beats.json`、`contact_sheet.png`、`cover.png`、`facts_and_sources.md` 与 `src/`。源码目录包含清单、实现、三个 QC 报告及 `sfx_only.wav`。快审和交接分别放在 `src/review/`、`src/reviews/`；临时运行放本期 `.work/`。

## 制作清单

保留现有七件交付结构。单期在 `src/manifest.json` 声明路径与 Composition，选题相对 `inbox/evergreen_vibe/`，入口相对单期 `src/`，微音效和素材目录相对单期，另选 BGM 的路径相对工程根。默认配乐按本机授权规则使用。示例中的文件名和 Composition ID 由单期替换。

```json
{
  "version": 1,
  "topic": "04_主题.md",
  "entry": "entry.tsx",
  "previewComposition": "Review",
  "fullComposition": "Cinema",
  "previewFrames": 900,
  "profile": "vibe-3.3",
  "publicDir": "src/assets",
  "sfx": "src/sfx_mix.wav"
}
```

分幕只在 `beats.json` 维护，格式见 `contracts/beats.schema.json`。起止边界以整数帧校验，阅读窗为左闭右开区间。两个 Composition 共用 `profile.hard.video` 的原生坐标。快审使用 previewFps 与 previewScale，全片使用 fps；`samplePlan.reading` 中的帧号始终按正式时间轴解释。Python 依赖沿用项目解释器，契约检查另使用 jsonschema、PyYAML。

## 参数由谁维护

| 需要改什么 | 改哪里 | 生效范围 |
|---|---|---|
| 画幅、编码、响度、安全区、阅读窗、总时长档位 | Infra 在 `tools/profiles/` 新建版本并登记到 `registry.json`，保留已登记版本的原始字节 | 选用该版本的新期。省略 `profile` 的清单沿用 [`vibe-3.3`](../tools/profiles/vibe-3.3.json)。 |
| 路径和渲染并发 | 按需将 `tools/env.example.json` 复制为 `tools/env.local.json`，只填写本机需要覆盖的键 | 并发按命令行 `--concurrency`、本机配置、旧清单中的 `concurrency`、模板默认值的顺序取值。正整数有效，超过 4 提示内存压力。改变并发保留审批。 |
| 本期素材、分幕和节奏 | Render 与 Architect 共用单期 `src/manifest.json` 和 `beats.json` | `review` 绑定入口、两个 Composition、实际 `publicDir` 路径和文件集合、渲染源码、快照、SFX、BGM 本体及节拍档案、基准 `bgmGainDb`、分幕、档案及例外。改动或删除参与绑定的文件会使样片失效。`tools/`、`evidenceScript`、`concurrency` 和 `previewFrames` 属于执行或取证配置。 |

`ffmpegDir` 可填绝对目录；工具定位顺序为工具自身的显式路径参数、本机配置、环境变量 `FFMPEG_BIN`、安装目录自动发现。FFmpeg 与 ffprobe 必须同目录且均为 9.0.2。`pythonPath` 可声明解释器绝对路径，preflight 核对当前进程；项目要求 Python 3.12.4。硬解使用 D3D11VA。本机文件由 Git 和基建恢复包共同排除。

## 单期复用 core/vibe

准备好清单后、开渲前，从工程根执行 `python -B tools/episode.py snapshot $ep`。命令在单期写锁内将 [五类原语](../core/vibe/) 安装到 `src/vendor/vibe/`，把收据的 SHA-256 写入清单的 `coreSnapshot`；再次执行会核验已绑定版本。使用相对导入，例如单期入口导入 `./vendor/vibe/clock`。快照文件本身参与 `review` 绑定，换底座会要求重签；只改清单里的 `coreSnapshot` 字段而快照未变则不失效。已有清单可继续用原实现。

| 原语 | 单期如何接入 |
|---|---|
| clock.ts | 根 Composition 传入同一 `score`、`profile`，用全局帧和当前 Composition 的 fps 调用 frameClock。返回正式时间轴帧、幕内进度、阅读窗、高潮帧、非硬切首帧与上幕末帧。跨幕实体的姿态连续性由单期维护。 |
| TextLifecycle.tsx | 传 clock 和两行以内的主句。可指定主行、文字色、强调色及整数位置。阅读窗须容纳于入场结束与尾迹开始之间，快审前核对；DOM 框采集选择 `[data-vibe-static-text][data-holding="true"]`。 |
| Fonts.tsx | 自底座 1.1.0 起，仓库默认分发 4 字族 / 8 个字体文件，含 Noto Sans SC Regular（400）和 Medium（500）。将 `assets/fonts/` 的字体与许可复制到单期 publicDir 下的 fonts 目录，用 `<Fonts folder="fonts">` 包裹舞台即可。单期可用 `extraFaces` 追加本地字体（每项依次为字族、字重字符串、文件名）；原有 `notoMedium` 可指定替代的 Medium 文件。任一声明文件加载失败会取消渲染并报告路径。 |
| StageBase.tsx / tokens.ts | 调用 `stageTokens(profile, score.lighting)`，将结果和 headline、stage、readout 三槽传给 StageBase；cameraTransform 只作用于中层纯几何。定型的中层标注传给独立静止层 labels。 |
| sfx_engine.py | 自底座 1.2.0 起直出 2 声道立体声 WAV：单声道音色按等幅 `L = R` 铺开，自带声道的音色原样保留，并按立体声实际峰值归一化到档案 `sfxPeak` 中值（默认 `-14.0 dB`）。`mix_bgm` 以立体声读取，衰减为 `0.0 dB`；1.1.0 的单声道母带经 FFmpeg `-ac 2` 上混会掉 `-3.01 dB`，容易误触 `-16 dB` 下限。已快照的单期仍用其自带 1.1.0 副本。 |

`plan` 和 `verify` 核对单期快照，核验使用清单和交付收据中的摘要，离线可重放。题材几何、相机语言、关键词选择、声部波形属于单期。底座的字阶、线宽、底色随代码快照版本发布；安全区、ROI 与音效目标峰值读取本期档案。

## 导演指定某一幕的节奏

三档常规幕长见本期档案的 `defaults.beatDurationSec`。确需超出时，Architect 在本期清单选用 [`vibe-3.4`](../tools/profiles/vibe-3.4.json)，列出幕号、精确秒数及导演理由。下面的例子要求 `beats.json` 中第 1 幕实际为 3.5 秒。

```json
{
  "profile": "vibe-3.4",
  "overrides": [
    {"rule": "beat_duration", "scope": "B01", "value": 3.5, "reason": "开场只呈现一个动作，导演希望立即切入推理"}
  ]
}
```

例外在方案里写明幕号、精确秒数与理由，随样片一并复核；`review` 签字时把清单中的 `overrides` 记入 `acceptedOverrides`，不再单独设卡点。`status.requested_overrides` 可随时查看申请，签字后 `status`、`plan` 与最终报告均列出 `applied_overrides`。每项只能匹配一个实际超界的幕长。总片长、硬切次数、阅读窗、编码、音频、光场和安全区仍执行原门槛。

## 导演与接手人

以下为 PowerShell 命令。变量 `$ep` 为本次真实目录。在已经收到明确批准时才执行相应 `approve`；用导演实际意见替换示例文字。签字后 `status.nextGate` 依次推进 `review` → `delivery` → `done`。

```powershell
python -B tools/episode.py status $ep
python -B tools/episode.py handoff $ep --owner Render --scope B12 --protect 'B11、B13、母带和片长' --note '第12幕退场慢一点' --evidence src/review/preview.mp4
python -B tools/episode.py resolve $ep --request <意见ID> --note '说明实际验证内容' --evidence src/review/B12对照.png
python -B tools/episode.py approve $ep --gate review --note '<样片确认原话>'
python -B tools/episode.py approve $ep --gate delivery --note '<终审采纳原话>'
```

`handoff` 和 `resolve` 追加记录。关闭交接需要对应的证据文件。任何未关闭意见会拦住全片和交付。`beats.json`、单期源码、素材、SFX、BGM 或档案变化时，`status` 把已签 `review` 判为失效；`tools/` 与调度字段的变化不影响签字。记录用于协作与失效检测，人工确认的真实性依靠记录人的实际授权。

## 从快审到成片

| 动作 | 命令及结果 |
|---|---|
| 检查计划 | `plan $ep --mode full` 输出确定性参数、阅读窗及 seam 清单。`preflight $ep --mode full` 还核对 Python、Node、Remotion、同目录 FFmpeg/ffprobe 和资产。选题卡在策划对话中确认。 |
| 快审 | `preview $ep` 产出 `src/review/preview.mp4`、混音报告与来源摘要。本期 Render 负责按规范另做 2K 道具、文字尾迹、高潮静帧及 360px 缩略条，分别存为 `src/review/{prop,trail,climax,phone}.png`。 |
| 快审证据 | `preview_qc.json` 保存本次媒体摘要、`passed`、`fonts/reading/seams/lighting` 实测和四张静图的摘要。导演看完后执行 `approve $ep --gate review --note ...`，命令核对快审媒体、收据、QC 及当前内容指纹，再登记原话和所审样片摘要。 |
| 全片候选 | `full $ep` 先核验 `review` 和当前内容。Remotion 输出 PNG 缓冲区，按帧号送入 FFmpeg，仅保存抽样计划内的 PNG。独立 run 位于本期 `.work/<id>/`。独立 `full` 后可手动调用单期取证脚本。 |
| 混音返工 | `ship $ep --work <run绝对路径>` 可按实测响度重试。按已审基准重混时，用 `remix $ep --mode full --work <run绝对路径>`。手动改基准增益须将新值写进清单，重新生成及确认快审。 |
| 单期视觉证据 | 本期在 run 目录生成 `cover.png`、`contact_sheet.png`、`layout.json`。后者含 `picture_sha256`（绑定 picture.mp4）、`passed:true`、`issues:[]`、`boxes`。boxes 按原始帧号列出所有实测静态文字框，例如 `{"120":[[220,320,920,424]]}`。采用真实 DOM 测量，保留题材专项检查细节。 |
| 汇总及提交 | `finish $ep --work <run绝对路径> --note '<实际联系表、安全区与线宽目视结果>'`。逐项复验真实候选，通过后迁出并校验，保留源与运行证据于 `src/production/<id>/`，清理该成功 run。失败 run 留在原地可重试。 |
| 最终人工确认 | `verify $ep` 只读重新核验。导演确认后执行 `approve $ep --gate delivery --note ...`。 |

全片与快审使用独立 run。写锁位于 src/reviews，成功 run 与其匹配的快审 run 在复验后清理，其他未验收 run 保留。七件正式产物在 `.work` 外。多文件提交以内容摘要和最后写入的 `final_qc.json` 为准，中断时重试原 run 的 `finish`。交付核验不代替导演判断，也不会触发下一期。

非硬切 `seam` 由三条同时成立的容差判定：全帧平均绝对差 `seam_delta ≤ 0.01`、单通道最大差 `max_pixel_delta ≤ 2`、变动像素占比 `changed_pixel_ratio ≤ 0.0001`。`reading_qc.json` 的每条记录如实保留 `seam_delta`、`max_pixel_delta`、`changed_pixels`（另附 `changed_pixel_ratio`）；出现元素跳动、边框残留或大面积偏移时至少一条超标，立即失败。阅读窗静态文字框仍按 `maxTextDelta = 0` 判绝对零差，该容差不适用于文字。仅记录 `seam_delta: 0` 的早期报告按零差等价解释，仍可通过复验。

## 后台托管与一键终审

耗时动作 `preview`、`full`、`ship`、`finish`、`verify` 可加 `--detach`：在独立进程组启动自身，父进程立即返回 `jobId`、`pid` 与日志路径；状态写入本期 `.work/active_job.json`（`status`、`stage`、`runDir`、`exitCode`、`error`），日志追加到 `.work/<jobId>.log`。用 `job $ep --wait 30 --tail 20` 短轮询：任务结束立即返回，未结束则干净返回 `running` 与最新进度。初始记录在拉起前落盘；随后由外层轻包装托管，子进程启动异常或非零退出码必写回 `status: failed` 与真实 `exitCode`、`error`，不会停在 `running`。

`ship $ep [--work <run>] [--note '<目视备注>'] [--clean-abandoned]` 串联 `full → 响度闭环 remix → evidenceScript → finish → verify`，要求有效 `review` 且无未关闭意见，最终停在 `delivery`。续跑须有原始 `picture-receipt.json`，收据须与已审批内容、画面母版和定点 PNG 匹配。正式混音响度超限时返回非零，在候选目录写 `mix_diagnostic.json`。`ship` 按实测 LUFS 与档案中值修正增益，最多在同一画面上重试两轮，有真峰值超限时也向下修正。留档 `sfx_only.wav` 默认跟随输入声道。

清单可选 `evidenceScript`（相对单期目录的 `.py` 或 `.cjs`）。`preview` 和 `ship` 自动以 `--mode preview|full --episode <ep> --work <run>` 调用它。独立 `full` 后可手动执行同一取证入口。自选配乐在预检前用 `python -B tools/bgm_analyze.py <音频>` 生成相邻 `.beats.json`。

### 通用取证

新期把入口存为 `src/evidence/frames.py`，并将该路径填入 `evidenceScript`。由工程根运行，帧号均按本期正式时间轴填写。

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "tools"))
from evidence_kit import main

main(cover_frame=240, still_frames={"prop": 30, "trail": 210, "climax": 360})
```

[`evidence_kit.py`](../tools/evidence_kit.py) 也可从命令行直接传 `--cover`、`--prop`、`--trail`、`--climax`。它在正式 Composition 采集原生 DOM 框、核验素材根 `fonts/` 下的四族八字体。快审生成三张静帧、360px 瓦片拼图和 QC。全片复用母版定点 PNG，生成封面、任意幕数的联系表和布局 JSON。Python 入口可传 `phone_frames`，或传 `check(dom_frames, full_plan)` 校验以 `data-vibe-evidence` 标记的题材节点。

渲染通道默认 `auto`，开渲前做 200ms 回环自测，被 AppX 拒绝时切到 `cdp-pipe`。管道渲染和取证共用 Chrome 启动逻辑，禁用 Crashpad，配置与临时文件写到各自工作目录内的 `chrome_tmp/`。浏览器退出码和 stderr 落到 `chrome-launch.json` 与 `chrome-stderr.log`。

## 交付后的复验

`finish` 将所选档案原始字节与导演的内容批准记录归档到 `src/production/<run>/`（1.2.0 起为 `content-approval.json`，记录 `review` 签字；旧单期为 `facts-approval.json`，复验同样接受），在 `src/final_qc.json` 保存档案版本、两份文件的 SHA-256 和批准 ID。混音和硬解报告分别带档案摘要。`verify` 用归档档案解释这次产物，核对分幕、批准和报告的关联。混音工具实测最终媒体响度，交付端按同一档案独立判断报告中的测量值；硬解使用独立软硬解对拍。未引入制作档案的早期协议按原默认值解释。旧尼姆样片可单独做 1080p 编码与硬解兼容诊断。

## 回归

```powershell
python -B -m unittest discover -s tools/tests -v
node --check tools/render_episode.cjs
```

回归在临时夹具运行。既有影片可只读运行 `decoder_check.py --strict --video <路径>`。历史报告及旧期源码按其原始版本解释。
