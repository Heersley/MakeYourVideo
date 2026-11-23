# assets/fonts — 4 族 8 文件离线字库（仅说明，不分发二进制）

共享底座 `core/vibe 1.2.0`（`Fonts.tsx` 的 `bundledFaces`）默认内置 **4 个字体族、8 个字体文件**；任一缺失会 `cancelRender` 报错，禁用静默回退到系统字体。本开源仓库**不附带任何字体二进制**（`.woff` / `.woff2` / `.otf`），使用者需自行从官方渠道下载并放入 `public/fonts/`。

## 4 族 8 文件清单（SIL OFL 1.1）

| 档位 | 字体族 | 字重 / 文件 |
|---|---|---|
| ① 叙事大字（西文/数字） | Source Serif 4 | 400 `SourceSerif4-Regular.ttf.woff2`、600 `SourceSerif4-Semibold.ttf.woff2` |
| ① 叙事大字（中文） | ChillJinshuSong（寒蝉锦书宋 V2.0） | 400 `ChillJinshuSongRegular.woff`、700 `ChillJinshuSongBold.woff` |
| ② 盘面标注 | Noto Sans SC | 400 `NotoSansSC-Regular.otf`、500 `NotoSansSC-Medium.otf` |
| ③ 公式与读数 | JetBrains Mono | 400 `JetBrainsMono-Regular.woff2`、500 `JetBrainsMono-Medium.woff2` |

共 **4 族 8 文件**，全部 SIL Open Font License 1.1，可免费商用。

## 官方来源

- Source Serif 4：<https://github.com/adobe-fonts/source-serif/releases>
- 寒蝉锦书宋 V2.0：<https://github.com/Warren2060/ChillJinshuSong/releases/tag/GBv2.0>
- Noto Sans SC：<https://github.com/notofonts/noto-cjk/tree/main/Sans/SubsetOTF/SC>
- JetBrains Mono：<https://github.com/JetBrains/JetBrainsMono/releases>

## 放置与自检

下载后把 8 个文件按上表文件名原样放入 `public/fonts/`（`public/` 不入库）。`Fonts.tsx` 通过 `staticFile('fonts/<file>')` 逐个 `document.fonts.load()` 校验，缺任一文件都会显式报错。

> **测试分工**：`tools/tests/test_vibe_core.py` / `tools/tests/vibe_core.cjs` 的「离线字体实装」检查仅在本地已下载 8 个字体二进制时执行完整加载校验；仓库内无字体二进制时自动降级为对本说明文件的契约检查（4 族 8 文件声明），并跳过真实 Chromium 渲染类测试。`tools/tests/test_seal.py` 若检测到无字体二进制会显式 skip 并给出准备说明。
