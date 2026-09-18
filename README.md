---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '9da0b182-a065-4f4f-9722-4c4d61ef2709'
  PropagateID: '9da0b182-a065-4f4f-9722-4c4d61ef2709'
  ReservedCode1: '4e1c214e-9438-47cf-b5f7-958b92097ae6'
  ReservedCode2: '4e1c214e-9438-47cf-b5f7-958b92097ae6'
---

# 龙战士4 (Breath of Fire IV) 简体中文汉化项目

> PlayStation 1《Breath of Fire IV - うつろわざるもの》(日版) 简体中文汉化工程：
> 全量文本提取、全量重译、字库像素布局逆向、字模生成与镜像写入工具链。
> 本仓库包含全部译文、工具、破解文档，供后续接手者完整复现。

## 当前状态 (2026-09-18)

| 模块 | 状态 | 说明 |
|------|------|------|
| 文本提取 | ✅ 完成 | 17,676 条 / 270 文本段 / 262 个 EMI 文件 |
| 全量重译 | ✅ 完成 | 15,049 条非空文本 100% 译完，24 批 TSV 定稿 |
| 译文校验 | ✅ 完成 | 控制码/换行/分隔线逐条一致，0 假名残留，0 缺译 |
| 字库布局逆向 | ✅ 完成 | 21 列网格 + 低 nibble 在左（经 VRAM 转储逐字节验证） |
| 字模方案 | ✅ 完成 | XP 宋体 12px 点阵 + 右下 2 向细描边（v12 定稿） |
| 模拟器验证 | ✅ 通过 | v12 验证镜像中文显示正常（沙漠流星场景） |
| **字库容量** | ❌ **未解决** | 全量译文 2,087 唯一字符 > 原版架构容量，见下文「核心瓶颈」 |

⚠️ **全量汉化镜像尚不可生成**：翻译与显示技术均已就绪，但字库容量模型需重新设计。
接手者请先阅读 [docs/cracking_analysis.md](docs/cracking_analysis.md) 与下文「核心瓶颈」。

## 核心瓶颈：字库容量

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

## 项目结构

```
bof4-chinese/
├── README.md                    # 本文件
├── README_EN.md                 # 英文说明
├── CHANGELOG.md                 # 变更日志 (v0.1~v0.4)
├── LICENSE                      # MIT
├── translation_workbook.json    # 翻译工作簿 (17,676 条, 已含全量定稿译文)
│
├── texts/                       # 文本资产
│   ├── tsv/                     # ★ 24 批翻译 TSV (定稿译文, 翻译协作主载体)
│   │   ├── batch_01~24.tsv      #   id / file / seg / src(日文) / tgt(中文)
│   │   ├── SPEC.md              #   翻译规范 (假名禁用/音译表/术语表/控制码表)
│   │   └── TSV_README.md        #   TSV 使用说明
│   ├── original_japanese.txt    # 原文解码全文 (人类可读)
│   ├── translated_chinese.txt   # 译文对照全文 (JP/CN 逐条)
│   └── original_hex_comparison.txt
│
├── tools/                       # 全套工具 (Python 3.8+)
│   ├── lib/bof4lib.py           # 共享库: ISO 读写 / EMI 解析 / 21列字库布局 / 文本编解码
│   ├── merge_tsv.py             # ★ TSV 译文合并回工作簿 (含全量格式校验)
│   ├── check_capacity.py        # ★ 译文字符容量审计 (各文件用字 vs 段容量)
│   ├── patch_bin.py             # ★ 一键导入: 工作簿+字体 → 汉化镜像
│   ├── export_text.py           # 文本导出 (+字库来源分析)
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
│   └── apply_patch.py           # BDIF 补丁应用
│
├── data/
│   ├── font_alloc_v2.json       # 字库分配方案 (基于旧译文, 供参考)
│   ├── font_segments_report.json# 297 个字库段扫描报告
│   ├── main_font_index.csv      # 原版主字库索引对照
│   ├── small_font_index.csv     # 原版小字库索引对照
│   └── text_blocks_original.json# 原始文本块 (hex + 解码)
│
├── docs/
│   ├── cracking_analysis.md     # ★ 破解技术文档 (格式/编码/字库/容量, 含修正记录)
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

> 注意：`--alloc` 方案基于旧译文的字符集，全量新译文会触发容量报错——
> 这正是「核心瓶颈」。解决容量问题后此命令即可端到端产出镜像。
> 字体推荐 **Windows XP 宋体 simsun.ttc**（12px 内置点阵字形，纯黑白无抗锯齿失真）。

### 翻译场景级验证镜像（技术已验证）

生成只汉化单个场景、其余保持原样的最小验证镜像（当前技术验证方式）：

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

### 3. 字模值语义 + 描边（v12 定稿）

| 值 | 含义 |
|----|------|
| 1 | 笔画主体（白） |
| 8 | 笔画右/下 1px 扩展（阴影，浅色背景可见的关键） |
| 0 | 背景 |

纯值 1 无描边时，白字在浅色背景上会「偶尔不显示」（与原版日文字形对比确认）。
三版对比（无描边 / 3 向粗描边 / 右下 2 向细描边）定稿为**右下 2 向细描边**。

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

1. **先读文档**：`docs/cracking_analysis.md`（全部格式/布局/容量事实）→ 本 README「核心瓶颈」
2. **跑测试**：`python -m unittest discover -s tests` 确认环境正常
3. **验证字库**：`dump_font.py` + `import_font.py` round-trip，确认布局理解正确
4. **选容量路径**：A/B/C/D（见上），或提出新方案
5. **构建镜像**：容量方案确定后，`merge_tsv.py` → `patch_bin.py` 端到端
6. **模拟器实测**：推荐 RetroArch (PCSX-ReArmed) / DuckStation

## 致谢

- Capcom：龙战士4 原版游戏
- 全部参与翻译与破解的工作者

## 许可证

MIT License（见 [LICENSE](LICENSE)）。

本项目仅供学习与研究用途，请通过合法渠道获取并使用正版游戏。

> AI生成