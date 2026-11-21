# assets/fonts — 三档开源字库

本仓库**不附带字体文件**（体积大且应由使用者自行从官方渠道获取）。三套字体均为 **SIL Open Font License 1.1**，可免费商用。

## 三档分工（不跨层混用）

| 档位 | 用途 | 字体 | 字重 |
|---|---|---|---|
| ① 叙事大字 | 主句 / 辅行 | **寒蝉锦书宋 V2.0**（`ChillJinshuSong`）+ **Source Serif 4**（西文/数字） | 400 / 700；西文 400 / 600 |
| ② 盘面标注 | 中层标签、界面小字 | **Noto Sans SC** / Source Han Sans SC | 400 / 500 |
| ③ 公式与读数 | 等宽数字、公式 | **JetBrains Mono** | 400 / 500 |

## 官方来源

| 字体 | 发布页 | 许可 |
|---|---|---|
| 寒蝉锦书宋 V2.0（GBv2.0） | <https://github.com/Warren2060/ChillJinshuSong/releases/tag/GBv2.0> | OFL 1.1 |
| Source Serif 4（4.005R） | <https://github.com/adobe-fonts/source-serif/releases/tag/4.005R> | OFL 1.1 |
| JetBrains Mono（v2.304） | <https://github.com/JetBrains/JetBrainsMono/releases/tag/v2.304> | OFL 1.1 |
| Noto Sans SC | <https://github.com/notofonts/noto-cjk/releases> | OFL 1.1 |

## 放置位置

示例工程 `examples/nim_game/src/Fonts.tsx` 通过 Remotion 的 `staticFile('fonts/…')` 读取，即**仓库根的 `public/fonts/`**：

```bash
mkdir -p public/fonts
# 放入以下 6 个文件（文件名需与 Fonts.tsx 的 faces 表一致）
#   ChillJinshuSongRegular.woff      (400)
#   ChillJinshuSongBold.woff         (700)
#   SourceSerif4-Regular.ttf.woff2   (400)
#   SourceSerif4-Semibold.ttf.woff2  (600)
#   JetBrainsMono-Regular.woff2      (400)
#   JetBrainsMono-Medium.woff2       (500)
```

- 官方发布包若给的是 `.ttf/.otf`，用 `fonttools` 转成 `woff2`（推荐）或直接改名并在 `Fonts.tsx` 里把 `format` 改成 `truetype`；
- 项目内的长期归档放 `assets/fonts/`，渲染时再同步到 `public/fonts/`；
- 字体文件已被 `.gitignore` 排除，**不要提交**。

## 自检

页面加载时会逐个 `document.fonts.load()` 校验字重与字符样本；任一未命中会直接抛错（而不是静默回退到系统字体）。这样能在阶段 1 就发现「字没加载对」，避免成片出现 `Microsoft YaHei` / 宋体回退。

## 禁用

不绑定任何手机厂商定制字库；不使用来源不明的商用字体；不使用系统预装字体作为兜底。
