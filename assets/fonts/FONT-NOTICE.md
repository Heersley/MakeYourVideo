# 正式渲染字体

从下列发布方下载静态字体，保留对应的 SIL OFL 1.1 许可文件。圆周角示例从仓库根的 `assets/fonts/` 读取并复制到本期 `src/assets/fonts/`。自行制作时使用清单 `publicDir` 下的 `fonts/`。

| 字体 | 文件名 | 来源 |
|---|---|---|
| 寒蝉锦书宋 GB V2.0 | `ChillJinshuSongRegular.woff`、`ChillJinshuSongBold.woff` | [GBv2.0 发布包](https://github.com/Warren2060/ChillJinshuSong/releases/tag/GBv2.0) 的 GB 版本 WOFF 目录 |
| Source Serif 4 | `SourceSerif4-Regular.ttf.woff2`、`SourceSerif4-Semibold.ttf.woff2` | [4.005R 发布包](https://github.com/adobe-fonts/source-serif/releases/tag/4.005R) 的 WOFF2 / TTF 目录 |
| Noto Sans SC | `NotoSansSC-Regular.otf`、`NotoSansSC-Medium.otf` | [noto-cjk 的简体中文 SubsetOTF](https://github.com/notofonts/noto-cjk/tree/main/Sans/SubsetOTF) 中的 SC 目录 |
| JetBrains Mono | `JetBrainsMono-Regular.woff2`、`JetBrainsMono-Medium.woff2` | [v2.304 发布包](https://github.com/JetBrains/JetBrainsMono/releases/tag/v2.304) 的 `fonts/webfonts/` 目录 |

正式底座会校验 4 族 8 文件。Studio 的几何示例直接使用源代码绘制。
