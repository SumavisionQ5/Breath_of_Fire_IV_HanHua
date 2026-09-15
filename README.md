---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'b17163cb-2b38-4e83-be8a-3b88ba62b2c6'
  PropagateID: 'b17163cb-2b38-4e83-be8a-3b88ba62b2c6'
  ReservedCode1: 'c131c98a-149d-465c-ac53-04b89ec9b9bb'
  ReservedCode2: 'c131c98a-149d-465c-ac53-04b89ec9b9bb'
---

# 龙战士4 (Breath of Fire IV) 简体中文汉化项目

## 项目简介

本项目对 PlayStation 1 平台游戏《龙战士4》(Breath of Fire IV - Utsurowazaru Mono, 日版) 进行简体中文汉化。

汉化工作包括：
- 全量日文文本提取 (17676 条, 270 个文本段, 262 个 EMI 文件)
- 全量中文翻译 (15049 条非空文本, 100% 完成)
- 12×12 像素中文字库生成 (349 全局主字库 + 205 小字库 + 261 场景字库)
- 游戏镜像补丁写入

## 项目状态

⚠️ **汉化补丁处于开发中，尚未完全可用。**

| 功能 | 状态 |
|------|------|
| 文本提取 | ✅ 完成 |
| 中文翻译 | ✅ 完成 (100%) |
| 字库分配 | ✅ 完成 |
| 字模生成 | ✅ 完成 |
| 文本编码 | ✅ 完成 |
| 写入 BIN 镜像 | ✅ 完成 (262/270 段) |
| 模拟器测试 | ⚠️ 游戏可启动，文本显示待修复 |
| 场景字库写入 | ❌ 待完成 |
| 字模格式适配 | ⚠️ 格式已确认，像素排列待验证 |

## 文件结构

```
bof4-chinese/
├── README.md                    # 本文件 (中文)
├── README_EN.md                 # 英文说明
├── docs/
│   └── cracking_analysis.md     # 破解技术文档
├── texts/
│   ├── original_japanese.txt    # 原始日文文本 (可读格式)
│   ├── original_hex_comparison.txt # 原始文本 hex 对照
│   └── translated_chinese.txt   # 翻译后中文文本
├── tools/
│   ├── lib/
│   │   └── bof4lib.py           # 共享库 (ISO/EMI/编码)
│   ├── export_text.py          # 文本导出工具
│   └── patch_bin.py             # 一键导入汉化补丁
├── data/
│   ├── font_alloc.json          # 字库分配方案
│   ├── main_font_index.csv      # 主字库索引对照表
│   ├── main_font_index.json     # 主字库索引 (JSON)
│   ├── small_font_index.csv     # 小字库索引对照表
│   └── merged_font_index.csv    # 合并对照表
└── patch/
    └── (补丁文件 — 待生成)
```

## 快速开始

### 环境要求

- Python 3.8+
- PIL/Pillow (字模生成需要)

```bash
pip install pillow
```

### 一键导入汉化补丁

```bash
# 使用项目提供的翻译工作簿和字库分配
python tools/patch_bin.py "Breath of Fire IV - Utsurowazaru Mono (Japan).bin" \
    translation_workbook.json \
    bof4_chinese.bin \
    data/font_alloc.json
```

### 导出原始文本

```bash
python tools/export_text.py "Breath of Fire IV - Utsurowazaru Mono (Japan).bin" output/
```

## 翻译信息

- **总条目**: 17676 条
- **非空条目**: 15049 条
- **翻译覆盖率**: 100%
- **文本段数**: 270 个
- **涉及文件**: 262 个 EMI 文件
- **控制码**: 17 种 (全部保留原样)
- **字符集**: 1804 个唯一字符 (349 全局主字库 + 205 小字库 + 261 场景字库)

## 技术细节

详见 [破解技术文档](docs/cracking_analysis.md)。

### 编码规则

| 字节序列 | 含义 |
|----------|------|
| 0x12 XX | 主字库索引 XX (0-255) |
| 0x13 XX | 主字库索引 XX+256 或场景字 |
| 0x15 XX | 小字库索引 XX+224 |
| 字节 B (≥0x21) | 小字库索引 B-32 |
| 字节 B (<0x21) | 控制码 |

### 字库结构

- **主字库**: 349 字模, 存于 INIT.EMI Seg7 (VRAM 0x1C000200)
- **小字库**: 205 字模 (扩展)
- **场景字库**: 每场景最多 97 字 (索引 349-445)

### 字模格式

- 尺寸: 12×12 像素
- 色深: 4bpp (4 bits per pixel)
- 大小: 72 字节/字模 (12 行 × 6 字节/行)
- 灰度: 9 级 (0-8, 0=透明, 8=不透明)

## 致谢

- Capcom: 龙战士4 原版游戏开发
- 所有参与翻译和破解的工作者

## 许可证

本项目仅供学习和研究用途。请支持正版游戏。

> AI生成