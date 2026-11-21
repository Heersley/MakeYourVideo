# assets/fonts — 开源字库的下载与放置

本仓库**不附带字体文件**（体积大且应由使用者自行从官方渠道获取）。示例工程用到的字体均为 **SIL Open Font License 1.1**，可免费商用。

## 档位分工（不跨层混用）

| 档位 | 用途 | 字体 | 字重 | 是否被示例引用 |
|---|---|---|---|---|
| ① 叙事大字 | 主句 / 辅行 | **寒蝉锦书宋 V2.0**（`ChillJinshuSong`）+ **Source Serif 4**（西文/数字） | 400 / 700；西文 400 / 600 | ✅ 4 个文件 |
| ② 盘面标注 | 中层标签、界面小字 | **Noto Sans SC** / Source Han Sans SC | 400 / 500 | ❌ 预留档位 |
| ③ 公式与读数 | 等宽数字、公式 | **JetBrains Mono** | 400 / 500 | ✅ 2 个文件 |

> **关于 ② 档**：`examples/nim_game/src/Fonts.tsx` 目前**只加载 ①③ 两档共 6 个文件**，Noto Sans SC 是规范预留的标注档，示例并未引用。跑通示例**不需要**下载它；做新片要用 ② 档时，需自己在 `Fonts.tsx` 的 `faces` 表里补一条并放入对应文件。

## 官方来源

| 字体 | 发布页 | 需要的资产 | 许可 |
|---|---|---|---|
| 寒蝉锦书宋 V2.0（GBv2.0） | <https://github.com/Warren2060/ChillJinshuSong/releases/tag/GBv2.0> | `ChillJinshuSong_v2.0.zip`（**约 246 MB**） | OFL 1.1 |
| Source Serif 4（4.005R） | <https://github.com/adobe-fonts/source-serif/releases/tag/4.005R> | `source-serif-4.005_WOFF2.zip`（**直接给成品 woff2**） | OFL 1.1 |
| JetBrains Mono（v2.304） | <https://github.com/JetBrains/JetBrainsMono/releases/tag/v2.304> | `JetBrainsMono-2.304.zip`（内含 `fonts/webfonts/`） | OFL 1.1 |
| Noto Sans SC | <https://github.com/notofonts/noto-cjk/releases> | 按需自取（示例不需要） | OFL 1.1 |

## 取文件（逐字符对照）

**6 个文件里有 4 个可以直接从官方包里原样取出**，只有寒蝉锦书宋需要挑子目录：

```bash
# ① Source Serif 4：官方 WOFF2 包内就是成品文件名，直接取
unzip -j source-serif-4.005_WOFF2.zip \
  "source-serif-4.005_WOFF2/TTF/SourceSerif4-Regular.ttf.woff2" \
  "source-serif-4.005_WOFF2/TTF/SourceSerif4-Semibold.ttf.woff2" -d public/fonts

# ③ JetBrains Mono：官方包内 fonts/webfonts/ 下就是成品 woff2
unzip -j JetBrainsMono-2.304.zip \
  "fonts/webfonts/JetBrainsMono-Regular.woff2" \
  "fonts/webfonts/JetBrainsMono-Medium.woff2" -d public/fonts

# ① 寒蝉锦书宋：246 MB 包里只有 GB 子目录的 woff 是对的
#   路径：寒蝉锦书宋v2.0/寒蝉锦书宋GB/woff/
#   ⚠️ 不要取 寒蝉锦书宋Pro/ 下的 Pro_Regular.woff —— 同 family 名但字形不同，
#      字体校验不会报错，成片字形会与规范不一致。
unzip -j ChillJinshuSong_v2.0.zip \
  "寒蝉锦书宋v2.0/寒蝉锦书宋GB/woff/ChillJinshuSongRegular.woff" \
  "寒蝉锦书宋v2.0/寒蝉锦书宋GB/woff/ChillJinshuSongBold.woff" -d public/fonts
```

> 寒蝉包较大，弱网下容易下成截断的坏 zip（`unzip` 报 `End-of-central-directory signature not found`）。
> 用 `curl -C -` 断点续传重试，或先 `curl -sIL <url> | grep -i content-length` 核对字节数（应为 `246849093`）。

## 放置位置

示例工程 `examples/nim_game/src/Fonts.tsx` 通过 Remotion 的 `staticFile('fonts/…')` 读取，即**仓库根的 `public/fonts/`**（`public/` 不在仓库里，需要自己建）：

```bash
mkdir -p public/fonts
# 放入以下 6 个文件（文件名需与 Fonts.tsx 的 faces 表逐字符一致，含大小写与双后缀）
#   ChillJinshuSongRegular.woff      (400, format: woff)
#   ChillJinshuSongBold.woff         (700, format: woff)
#   SourceSerif4-Regular.ttf.woff2   (400, format: woff2)  ← 注意 .ttf.woff2 双后缀
#   SourceSerif4-Semibold.ttf.woff2  (600, format: woff2)
#   JetBrainsMono-Regular.woff2      (400, format: woff2)
#   JetBrainsMono-Medium.woff2       (500, format: woff2)
```

- **只放 `public/fonts/` 就够了**：渲染（`Fonts.tsx`）与示例 QC（`bounds.py`）都会读这里。`bounds.py` 的查找顺序是 `public/fonts/` → `assets/fonts/` → `examples/nim_game/src/assets/fonts/`，放任意一处都能被找到。
- `assets/fonts/` 是**可选的**长期归档位（与 `public/fonts/` 内容一致即可），不影响运行。
- 字体文件已被 `.gitignore` 排除，**不要提交**。
- 若官方包只给 `.ttf/.otf`（例如换了版本），可用 fonttools 转 woff2：`python -m fontTools.ttLib.woff2 compress <in.ttf>`，转换后仍需保持上表文件名。

## 自检

页面加载时会逐个 `document.fonts.load()` 校验字重与字符样本；任一未命中会直接 `cancelRender` 抛错（而不是静默回退到系统字体）。这样能在阶段 1 就发现「字没加载对」，避免成片出现 `Microsoft YaHei` / 宋体回退。

快速验证字体确实生效：

```bash
# 临时移走字体后渲染 1 帧，应当失败并打印 6 个 404 + NetworkError
mv public/fonts public/fonts_hidden
npx remotion still examples/nim_game/src/entry.tsx NimCinema out/negctl.png --frame=200
mv public/fonts_hidden public/fonts
```

## 禁用

不绑定任何手机厂商定制字库；不使用来源不明的商用字体；不使用系统预装字体作为兜底。
