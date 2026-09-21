---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'f81d512d-17ef-4d4a-826a-06f6bb5f6f25'
  PropagateID: 'f81d512d-17ef-4d4a-826a-06f6bb5f6f25'
  ReservedCode1: '3bb5a2e1-6371-4607-8af7-2f02ca7b1d85'
  ReservedCode2: '3bb5a2e1-6371-4607-8af7-2f02ca7b1d85'
---

# 龙战士4 (Breath of Fire IV) 简体中文汉化项目

> PlayStation 1《Breath of Fire IV - うつろわざるもの》(日版) 简体中文汉化工程：
> 全量文本提取、全量重译、字库像素布局逆向、字模生成与镜像写入工具链。
> 本仓库包含全部译文、工具、破解文档，供后续接手者完整复现。

## 当前状态 (2026-09-22)

| 模块 | 状态 | 说明 |
|------|------|------|
| 文本提取 | ✅ 完成 | 17,676 条 / 270 文本段 / 262 个 EMI 文件 |
| 全量重译 | ✅ 完成 | 15,049 条非空文本 100% 译完，24 批 TSV 定稿 |
| **译文精校** | ✅ **全量完成** | **17,676 条逐批逐条校对走完（v0.8.4）：换行/控制码/分隔线/同文族/繁体字五维全 0** |
| 字库布局逆向 | ✅ 完成 | 21 列网格 + 低 nibble 在左（经 VRAM 转储逐字节验证） |
| **字库容量** | ✅ **已解决** | 4 套 1bpp CLUT 分页（路径 E 已实施，v15 全量构建落地） |
| **全量汉化镜像** | ✅ **已生成** | v15 全量（对话/剧情）+ v16e 系统文本回填，实测通过 |
| 系统文本回填 | ✅ v16e | 62 条存档/读档/设置/命名译文实测通过；其余 1,138 条已译，待回填 (v16f) |
| 字模方案 | ✅ 完成 | XP 宋体 12px 点阵；描边 8 邻域环（v16e 实证修正） |
| 模拟器验证 | ✅ 通过 | v16e 命名界面白字芯+暗描边清晰可读，标题/立绘图形无回归 |

> **v0.8.4 全量精校里程碑**：17,676 条逐批逐条校对全部走完，并完成四项终裁
> （"王女さま"→统一公主、下取り系→让店里收购/回收、009501/009629 去语气词），
> 全库 4,459 个同 src 族译文 100% 一致，繁体/异体字 0 残留。详见
> [CHANGELOG.md](CHANGELOG.md) v0.8.4。

当前基线镜像 `bof4_chinese_v16e.bin`（740,731,544 B，SHA256 eeada38a…）：
v15 全量汉化（对话/剧情/4 套字库分页）+ v16e 系统文本回填（DEMO seg2 62 条译文 +
SYSTEM 字库 V1 描边/V9 白芯打包 + INIT win0[9] 白化）。构建方法见下文
「构建全量汉化镜像 (v15/v16e)」；v16 技术定案见
[docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md) 与
[CHANGELOG.md](CHANGELOG.md) v0.8.2。

## 字库容量问题（已解决：路径 E，4 套 CLUT 分页，v15 实施）

原版字库架构（21 列布局实测值）：

| 项 | 数值 |
|----|------|
| 全局共享槽（所有场景字库段一致） | 330（索引 0-329） |
| 场景专属槽 | 28672B 段 48 / 30720B 段 58 / 32768B 段 111 |
| 无字库段系统文件（7 个） | 只能用全局槽 |

全量重译后的实测压力（`tools/check_capacity.py` 输出）：

| 指标 | 数值 |
|------|------|
| 译文唯一字符并集 | **2,087**（全局槽仅 330，超限 1,757） |
| 7 个无字库系统文件用字并集 | **1,134**（超限 804，最严重瓶颈） |
| 独立超标文件（用字数 > 段容量） | 15 |
| 贪心全局分配后场景槽超标文件 | 124 |

**根因**：日文假名走小字库只占 1 字节且不需要主字库槽位，而中文全部汉字都要走主字库占 2 字节，
容量模型必须重新设计。可行路径（按侵入性递增）：

- **路径 A**：最小可玩版——仅汉化对话剧情场景，系统界面保持日文
- **路径 B**：精简用字后零搬移——翻译时限制字符集（如限用 1,500 常用字）
- **路径 C**：扩容搬移——字库段扩到 53,248 字节/段（工具 `emi_expand.py` 已就绪，镜像会变大）
- **路径 D**：定位小字库字形资源（可再 +225 槽，但仍不足以覆盖 685 需求，需与其他路径组合）
- **路径 E★（已实施）**：多套字形共享像素（CLUT 分页）——四套字形打包同一 12×12 槽，
  运行时用游戏原生的 `{色XX}` 调色板窗口切换（64 窗口）决定可见套。静态逆向已证实
  渲染链路无预光栅化缓存、逐字 CLUT 字段运行时可变、调色板内容来自我们可控的 EMI CLUT 段
  → **容量 ×4，零搬移吃下全量译文**。详见 `docs/clut_banking_design.md`；
  **v15 起已在全量镜像中落地**（4 套架构：全局池 330×4 + 场景区 (cap-330)×4 +
  原生色码强制套 + 套切换码，v15 构建脚本 `tools/bof4_v15_full_build.py`）

## 项目结构

```
bof4-chinese/
├── README.md                    # 本文件
├── README_EN.md                 # 英文说明
├── CHANGELOG.md                 # 变更日志 (v0.1~v0.8.2)
├── LICENSE                      # MIT
├── translation_workbook.json    # 翻译工作簿 (17,676 条, 已含全量定稿译文)
│
├── texts/                       # 文本资产
│   ├── tsv/                     # ★ 24 批翻译 TSV (定稿译文, 翻译协作主载体)
│   │   ├── batch_01~24.tsv      #   id / file / seg / src(日文) / tgt(中文)
│   │   ├── SPEC.md              #   翻译规范 (假名禁用/音译表/术语表/控制码表)
│   │   ├── TSV_README.md        #   TSV 使用说明
│   │   └── system_text/         #   ★ 系统文本 (62 条已回填 v16e + 1,138 条已译待回填 v16f)
│   ├── review_jp_cn_full.html   # ★ 全量中日对照审校文档 (18,876 条, 搜索/文件过滤/只看问题)
│   ├── review_jp_cn_system.html #   系统文本中日对照审校文档 (1,200 条)
│   ├── original_japanese.txt    # ★ 原文解码全文 (多页版, 零占位符, v0.6 重建)
│   ├── translated_chinese.txt   # 译文对照全文 (JP/CN 逐条)
│   └── original_hex_comparison.txt  # hex+解码逐条对照 (多页版, v0.6 重建)
│
├── tools/                       # 全套工具 (Python 3.8+)
│   ├── lib/bof4lib.py           # 共享库: ISO 读写 / EMI 解析 / 21列字库布局 / 文本编解码
│   ├── merge_tsv.py             # ★ TSV 译文合并回工作簿 (含全量格式校验)
│   ├── check_capacity.py        # ★ 译文字符容量审计 (各文件用字 vs 段容量)
│   ├── patch_bin.py             # ★ 一键导入: 工作簿+字体 → 汉化镜像
│   ├── export_text.py           # ★ 文本导出 (多页+场景字库映射, v0.6 修复)
│   ├── dump_font.py             # 原版字库提取 → PNG + meta.json
│   ├── import_font.py           # 原版字库还原 (round-trip 验证)
│   ├── scan_fonts.py            # 扫描全部 297 个字库段
│   ├── check_text_size.py       # 文本段空间预检查
│   ├── rebuild_emi.py           # EMI 段替换/扩容重建
│   ├── emi_expand.py            # EMI 扩容 + ISO 文件搬移 (路径 C 用)
│   ├── move_file_in_iso.py      # ISO9660 文件搬移
│   ├── analyze_font_usage.py    # 字符用量分析 (字库分配方案生成)
│   ├── analyze_slps.py          # SLPS_027.28 逆向分析 (需 capstone)
│   ├── make_patch.py            # BDIF 差异补丁生成
│   ├── apply_patch.py           # BDIF 补丁应用
│   ├── bof4_v15_full_build.py   # ★ v15 全量镜像构建 (4 套 CLUT 分页架构)
│   ├── bof4_v16e_build.py       # ★ v16e = v15 + 系统文本回填 (DEMO seg2 + seg4 池复制)
│   ├── bof4_v16e_demo_verify.py # ★ v16e DEMO/SYSTEM 专项验证
│   ├── bof4_v16e_full_verify.py # ★ v16e 全量读回验证 (470 EMI / CLUT / 字库)
│   ├── bof4_export_remaining.py    # 系统文本未译页导出 (1,138 条)
│   └── bof4_translate_remaining.py  # 系统文本翻译表回填 TSV (v16f 用)
│
├── data/
│   ├── font_alloc_v2.json       # 字库分配方案 (基于旧译文, 供参考)
│   ├── font_alloc_4set.json     # ★ v15 4 套字库分配 (v15/v16e 构建实际使用)
│   ├── font_alloc_4set_v16.json # v16 4 套字库分配 (v16e 验证用)
│   ├── font_segments_report.json# 297 个字库段扫描报告
│   ├── main_font_index.csv      # 原版主字库索引对照
│   ├── small_font_index.csv     # 原版小字库索引对照
│   ├── scene_map_original.json  # ★ 原版场景字库映射 5,388 条 (锚点+指纹+人工)
│   ├── multi_page_translations.json # ★ 多页槽页 2+ 译文 (v0.8, 34 页)
│   └── text_blocks_original.json# 原始文本块 (hex+解码, 多页版, v0.6 重建)
│
├── docs/
│   ├── cracking_analysis.md     # ★ 破解技术文档 (格式/编码/字库/容量, 含修正记录)
│   ├── v16_system_text_backfill.md # ★ v16 系统文本回填技术定案 (seg2/CLUT/字形规范)
│   ├── translation_guide.md    # 翻译规范与术语基准
│   ├── slps_reverse_engineering.md # SLPS 逆向报告 (字库加载路径)
│   ├── font_source_experiment.md  # 字体来源实验记录
│   ├── improvement_compliance.md   # 工程规范落实报告
│   └── release_notes_v0.2.md   # 历史发布说明
│
├── tests/
│   ├── test_codec.py            # 编码/解码测试 (12 项)
│   ├── test_font_roundtrip.py   # 21 列布局测试 (7 项)
│   ├── test_alloc.py            # 分配一致性测试 (14 项)
│   ├── test_multipage.py        # 多页文本段重组测试 (10 项, v0.8)
│   └── minimal_workbook.json
│
└── patch/                       # 历史补丁 (基于旧译文构建, 仅作参考)
    ├── bof4_chinese_v0.2.bdiff
    ├── bof4_chinese_v0.2_data.json
    ├── bof4_chinese.bdiff        # v0.1 时期补丁
    └── patch_data.json
```

## 快速开始

### 环境要求

- Python 3.8+
- Pillow（字模渲染）

```bash
pip install pillow
```

### 环境要求（可选）

- capstone（仅 `analyze_slps.py` 逆向需要）

### 工作流：修改译文后一键重建镜像

**第 1 步 — 翻译/修改译文**

直接编辑 `texts/tsv/batch_NN.tsv` 的第 5 列（`tgt`），
前 4 列（id/file/seg/src）原样保留。规范见 `texts/tsv/SPEC.md`。

**第 2 步 — 校验并合并回工作簿**

```bash
python tools/merge_tsv.py texts/tsv translation_workbook.json
```

自动校验假名残留、控制码、换行数、分隔线、缺译；任一问题即报错退出不写回。

**第 3 步 — 容量审计（可选但建议）**

```bash
python tools/check_capacity.py translation_workbook.json
```

输出各文件用字数 vs 字库段容量、超标文件清单。

**第 4 步 — 生成汉化镜像**

```bash
python tools/patch_bin.py "<原版镜像>.bin" translation_workbook.json 输出.bin \
    --alloc data/font_alloc_v2.json \
    --font C:/Windows/Fonts/simsun.ttc
```

> 注意：`patch_bin.py` 为 v0.x 单场景验证时代的工具（基于旧译文字符集的分配方案）。
> **全量构建已改走 v15/v16e 构建链**，见下一节。
> 字体推荐 **Windows XP 宋体 simsun.ttc**（12px 内置点阵字形，纯黑白无抗锯齿失真）。

### 构建全量汉化镜像 (v15/v16e，当前基线)

```bash
# v16e 构建 = 内部先跑 v15 全量构建 (import bof4_v15_full_build)
#           + DEMO seg2 62 条系统文本回填 + SYSTEM 字库 V1描边/V9白芯打包 + INIT win0[9] 白化
python tools/bof4_v16e_build.py

# 双重静态验证 (纯读, 不写镜像)
python tools/bof4_v16e_demo_verify.py
python tools/bof4_v16e_full_verify.py
```

产出 `bof4_chinese_v16e.bin`（740,731,544 B，SHA256 eeada38a…）。
构建输入：原版日版镜像、`translation_workbook.json`、`data/font_alloc_4set.json`、
62 条系统文本 TSV、simsun.ttc。脚本头部路径为本机配置，接手者按需调整；
架构细节见 [docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md)。

v16f（规划）：回填已翻译的 1,138 条系统文本
（`texts/tsv/system_text/system_text_remaining_translated.tsv`），
需先适配 COMMU03/SGAMEN/SHOP 的非标准 seg2 表结构（tbl[0]≠512）。

### 翻译场景级验证镜像（历史验证方式，v12 时代）

生成只汉化单个场景、其余保持原样的最小验证镜像：

```bash
python tools/patch_bin.py "<原版镜像>.bin" translation_workbook.json 验证.bin \
    --alloc data/font_alloc_v2.json --font C:/Windows/Fonts/simsun.ttc
```

v12 验证镜像（`bof4_verify_v12.bin`，零搬移）已实测：中文显示清晰、
描边正常、控制码正确。

### 原版字库 Round-trip 验证

```bash
python tools/dump_font.py "<原版镜像>.bin" --out font_dump --scale 4
python tools/import_font.py "<原版镜像>.bin" --dump font_dump
```

### 运行单元测试

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## 关键技术发现

### 1. 字库像素布局：21 列网格（推翻早期 64B/行 × 10 glyph 带假说）

字库段数据在 VRAM 中按 **21 列 × 12px** 网格排布（21×6 = 126 字节 < 256px 区宽）：

```
glyph i 位置: col = i % 21, row = i // 21 (×12px)
段内偏移须经 _vram_to_seg() 换算 (相邻 2048B 块在 VRAM 中并排)
```

经 VRAM 转储逐字节比对 + 字形渲染双重验证。**这是此前汉化版游戏内
字形碎片的根因**：按旧假说写入位置整体错位。

### 2. nibble 顺序：低 nibble = 左像素（PS1 标准）

4bpp 每字节存 2 像素，**低位在前**。客观指标验证：
低 nibble 在左时孤立像素率 0.0036，高 nibble 在左时 0.0969（差 27 倍），
后者在游戏内表现为「奇偶列错位碎片」。

### 3. 字模值语义 + 描边（v12 定稿，v16e 实证修正）

| 值 | 含义 |
|----|------|
| 1 | 笔画主体（白） |
| 8 | 笔画右/下 1px 扩展（阴影，浅色背景可见的关键） |
| 0 | 背景 |

纯值 1 无描边时，白字在浅色背景上会「偶尔不显示」（与原版日文字形对比确认）。
三版对比（无描边 / 3 向粗描边 / 右下 2 向细描边）定稿为**右下 2 向细描边**。

**v16e 实证修正**：对原版字形（INIT seg7）像素值统计显示双峰
**V=1 (24.9%，暗描边) + V=8 (25.9%，亮字芯)**，9-15 为零；描边结构 ≈ **8 邻域环**
（80.9% 覆盖，非「右下 2 向」）。文字调色板 = INIT seg1 win0：
[1]=(7,7,7) 暗描边、**[8]=(19,19,15) 恰为命名界面面板底色（绝不能动）**、
[9]=(20,21,22) 灰阶峰值。v16e 系统字库打包：描边→V=1 + 字芯→V=9 +
INIT seg1/3/4 win0[9] 白化 7FFF。详见
[docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md)。

### 4. 字库加载路径（SLPS 逆向确认）

- 进场景时上传该场景 EMI 字库段到 VRAM 覆盖全局字库
- `INIT.EMI` 的字库段只在开机上传，不参与游戏内文本渲染
- 7 个系统文件（CAMP/SHOP/MASTER/MSHOP/SGAMEN/SGAMENX/COMMU03）无字库段，
  沿用当前 VRAM 字库 → 用字必须全部在全局槽内
- EXE 在 RAM `0x8016BCE4` 有 516 项 LBA 硬编码文件表，ISO 搬移不同步会出错

### 5. 容量实测（21 列布局修正后）

| 段大小 | 总容量 | 场景专属槽 | 段数量 |
|--------|--------|-----------|--------|
| 28672 (0x7000) | 378 | 48 | 210 |
| 30720 (0x7800) | 388 | 58 | 31 |
| 32768 (0x8000) | 441 | 111 | 56 |

全局/场景分界 = **330**（索引 0-329 全场景一致；早期文档的 349 为错误值）。

### 6. 文本编码规则

| 字节序列 | 含义 |
|----------|------|
| 0x12 XX | 主字库索引 XX (0-255) |
| 0x13 XX | 主字库索引 XX+256 (256-511) |
| 0x15 XX | 小字库索引 XX+224（字形资源未定位，勿依赖） |
| 字节 B (0x21-0x7E) | 小字库索引 B-32 |
| 字节 B (<0x21) | 控制码（17 种，`{框}` `{立绘}` `{引2}` 等，翻译时原样保留） |

**系统文本（seg2）编码与主文本不同**（v16 破译，详见
[docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md)）：
单字节 0x20-0xFF → 小字库 idx 0-223；`0x15 XX` → 图标码（×=15 01 △=15 02 □=15 03 』=15 0A）；
`0x12/0x13` → 主字库全局池。

### 7. 小字库：独立资源，位置未定位

小字库（索引 0-61 为 ASCII/标点/假名固有位）的字形数据在全部 297 个
字库段中均未找到，是独立资源。**可使用其固有字符（1 字节编码）但无法新增字符**。

## 翻译信息

| 项 | 数值 |
|----|------|
| 总条目 | 17,676 |
| 非空条目（已译） | 15,049 |
| 文本段 | 270 |
| EMI 文件 | 262 |
| 唯一日文原文 | 4,888（去重率 67.5%） |
| 控制码 | 17 种，全部保留 |
| 格式校验 | 0 假名 / 0 控制码损坏 / 0 换行数不一致 / 0 缺译 |

翻译规范（音译同音同字、长音促音省略、译名冻结表、术语表）见
[texts/tsv/SPEC.md](texts/tsv/SPEC.md) 与 [docs/translation_guide.md](docs/translation_guide.md)。

## 接手指南

1. **先读文档**：`docs/cracking_analysis.md`（格式/布局/容量事实）→
   `docs/clut_banking_design.md`（路径 E 架构）→
   `docs/v16_system_text_backfill.md`（v16 系统文本技术定案）→ [CHANGELOG.md](CHANGELOG.md)
2. **跑测试**：`python -m unittest discover -s tests` 确认环境正常（v0.8 起 53 项，含多页重组测试）
3. **验证字库**：`dump_font.py` + `import_font.py` round-trip，确认布局理解正确
4. **复现基线**：`tools/bof4_v16e_build.py` 构建 → `bof4_v16e_demo_verify.py` +
   `bof4_v16e_full_verify.py` 双验证 → 与当前基线 SHA256 比对
5. **继续 v16f**：回填 `texts/tsv/system_text/system_text_remaining_translated.tsv` 的
   1,138 条译文（需适配 COMMU03/SGAMEN/SHOP 非标准 seg2 表结构），或继续场景文字描边/
   VRAM 字体上传变换逆向（见 CHANGELOG v0.8.2 已知边界）
6. **模拟器实测**：推荐 RetroArch (PCSX-ReArmed) / DuckStation

## 致谢

- Capcom：龙战士4 原版游戏
- 全部参与翻译与破解的工作者

## 许可证

MIT License（见 [LICENSE](LICENSE)）。

本项目仅供学习与研究用途，请通过合法渠道获取并使用正版游戏。

> AI生成