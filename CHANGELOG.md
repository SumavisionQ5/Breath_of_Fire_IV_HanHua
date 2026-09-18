---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '22c85338-09cb-4280-9128-951081f38212'
  PropagateID: '22c85338-09cb-4280-9128-951081f38212'
  ReservedCode1: '8a6b1252-ba88-43f8-815b-0b16e7e9ce90'
  ReservedCode2: '8a6b1252-ba88-43f8-815b-0b16e7e9ce90'
---

# 变更日志 (Changelog)

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [v0.4] - 2026-09-18

### 全量重译定稿

- **24 批 TSV（15,049 条）全部翻译完成并回填** `translation_workbook.json`
  （回填更新 12,897 条），全量校验：
  **0 假名残留 / 0 控制码损坏 / 0 换行数不一致 / 0 缺译**
- 修正 4 处分隔线数量不一致（同一句台词在 4 个场景文件多加 1 个 `---`，
  id 006939 / 012329 / 012383 / 012806）
- TSV 批次与翻译规范收入 `texts/tsv/`（batch_01~24.tsv + SPEC.md）

### 修复 (字模链路全部定稿)

- **nibble 顺序修正**：`generate_glyphs` 改为低 nibble = 左像素（PS1 标准）。
  客观指标：低 nibble 在左孤立像素率 0.0036，高 nibble 在左 0.0969（27 倍差距）
- **描边定稿**：字模加右下 2 向细描边（笔画=1，右/下 1px 扩展=8，不覆盖笔画）。
  三版对比（无描边 v10 / 3 向粗描边 v11 / 右下 2 向细描边 v12）定稿 v12。
  纯值 1 无描边时白字在浅色背景上"偶尔不显示"的问题由此解决
- **字体定稿**：Windows XP 宋体（simsun.ttc）12px 内置点阵（纯 0/255，无抗锯齿失真）
- v12 验证镜像 `bof4_verify_v12.bin`（零搬移）模拟器实测中文显示正常

### 容量审计 (新结论)

- 新增 `tools/check_capacity.py`：全量译文用字审计
- **实测**：译文唯一字符并集 **2,087**（全局槽仅 330）；
  7 个无字库系统文件用字并集 **1,134**；独立超标文件 15 个；
  贪心全局分配后场景槽超标文件 124 个
- **结论**：全量零搬移不可行（根因：假名走小字库 1 字节，中文全走主字库 2 字节）。
  可行路径 A（最小可玩版）/ B（精简用字）/ C（扩容搬移 53248B/段）/ D（定位小字库 +225 槽仍不足）

### 新增

- `tools/merge_tsv.py` — TSV 译文合并回工作簿（含全量格式校验，任一问题即中止）
- `tools/check_capacity.py` — 译文字符容量审计（各文件用字 vs 段容量/超标清单）
- `texts/tsv/` — 24 批定稿译文 + 翻译规范 SPEC.md
- `texts/translated_chinese.txt` — 从新工作簿重新生成的全量对照文本

### 变更

- `tools/patch_bin.py` `generate_glyphs()` — 描边支持（`shadow=True` 默认开启）、
  字体推荐改为 simsun.ttc、矩阵化二值化流程
- `README.md` / `README_EN.md` — 全面重写：反映 21 列布局 / 低 nibble / 描边方案 /
  容量瓶颈实测数据 / 接手工作流

---

## [v0.3] - 2026-09-17

### 生成记录

**最小验证版镜像（零搬移）**：`D:\龙战士\bof4_verify_v6_21col.bin`

- 目的：验证「21 列布局 + 笔画值 1」修复后，游戏内中文能否正确显示
- 处理文件：
  - `WORLD/AREAE023.EMI` — 文本段 seg17（1048 → 1251 字节，仍在原 2048 对齐空间内）+ 字库段 seg18
  - `WORLD/AREAE030.EMI` — 同一段剧情（鲁普沙漠·砂船·流星撞击）的另一份
  - `SYSTEM/INIT.EMI` — 字库段 seg7
- 字符集：该剧情 109 个字符（含汉字、假名残留、标点），写入槽 0..108，统一 `0x12 XX` 编码
- 字模：微软雅黑 12×12，阈值 96，**笔画值 = 1**（值 8 为阴影色，会导致淡色碎片）
- **零搬移验证**：输出镜像 697,838,400 字节，与原版**完全一致**
- 自查：读回字库段，109/109 非空字形；非零像素值分布仅 `{1: 201}`，确认笔画值正确；
  按 21 列渲染逐格识别与字符表一一对应

### 修复 (关键)

**字库布局重大修正：10 glyph/行 → 21 列网格**

早期实现（v0.1/v0.2 及全部汉化版本 v3/v4/v5）按「64 字节/行 × 10 glyph 带」写入字模，
导致写入位置整体错位，游戏内表现为**字形碎片、半涂抹汉字、乱码**——这是汉化一直
无法通过模拟器验证的**根因**。

经 VRAM 转储（`ram_full_state1.bin`）与 `INIT.EMI` seg7 交叉核对确认：

| 项目 | 旧（错误） | 新（已修正） |
|------|-----------|-------------|
| 网格 | 10 glyph/行 | **21 glyph/行**（21×6 = 126 字节，VTAM 区宽 256px） |
| glyph 定位 | `band×768 + r×64 + slot×6` | `_vram_to_seg(row, col)` 逐字节映射 |
| 28672 段容量 | 370 | **378** |
| 30720 段容量 | 400 | **388** |
| 32768 段容量 | 420 | **441** |
| 全局/场景分界 | 349 | **330** |

证据链：
- 段文件与 VRAM 在前 32 行（首个 2048 块）逐字节一致，块级落点为「2 块并排」
- 按 21 列从 VRAM 提取 glyph 0-20 得「中大砂嵐泥流回復天光海特異点最防御変身銃王」，
  与 `main_font_index.csv` 索引完全吻合；按旧「10 glyph 带」提取则为碎片
- 378 槽中 373 槽与 VRAM 逐字节一致（余 5 槽 349-353 已被场景字覆盖，反证 330 分界）
- 全局 4.4MB 搜索：不存在第二份字库副本，且不存在 21 列以外的排布

### 变更

- `tools/lib/bof4lib.py` — 字库布局改为 21 列网格，新增 `glyph_cell()` /
  `glyph_capacity()` / `glyph_seg_size()` / `_vram_to_seg()`，`get_glyph()` /
  `set_glyph()` 改为逐字节映射（跨块 glyph 不再互相破坏）
- `tools/patch_bin.py` — 删除本地 band 版 `glyph_capacity()`，场景段大小改用
  `glyph_seg_size()`（477 槽 → 36864 字节，与原段大小一致）
- `tools/scan_fonts.py` — 容量统计改用 `glyph_capacity()`
- `tests/test_font_roundtrip.py` — 重写为 21 列布局测试，新增跨块互不覆盖、
  超范围安全读取、容量精确值断言

### 文档

- `docs/cracking_analysis.md` — 修正 6.1（容量表）、6.2（像素布局）、5.1（小字库说明，
  推翻「单字节码 = 主字库右半区」）、5.2 / 6.5（分界 349 → 330）、10.0（新增修正记录）、
  10.1（字库加载路径已确认）

### 验证

- 单元测试 33 项全部通过（字库布局 7 + 编码 12 + 分配 14）
- 全部工具脚本导入正常

---

## [v0.2] - 2026-09-17

### 新增

**字库逆向工具**
- `tools/dump_font.py` — 原版字库提取工具（字库段 → 370 个字模 PNG + meta.json）
- `tools/import_font.py` — 原版字库还原工具（PNG → 字库段，round-trip 验证）
- `tools/scan_fonts.py` — 扫描全游戏 297 个字库段，输出 `font_segments_report.json`
- `tools/check_text_size.py` — 文本段空间预检查（编码后大小 vs 原始容量）
- `tools/rebuild_emi.py` — EMI relocation（段替换/扩容重建）
- `tools/emi_expand.py` — EMI 扩容 + ISO 文件搬移 + 目录记录更新
- `tools/move_file_in_iso.py` — ISO9660 文件搬移工具
- `tools/analyze_font_usage.py` — 字符用量分析（v2.1，强制全局约束）
- `tools/make_patch.py` — BDIF 差异补丁生成工具

**单元测试**
- `tests/test_codec.py` — 编码/解码单元测试（12 项）
- `tests/test_font_roundtrip.py` — 字库布局 round-trip 测试（5 项）
- `tests/test_alloc.py` — 场景字库独立性 + 分配一致性检查（14 项）
- `tests/minimal_workbook.json` — 最小测试工作簿

**数据文件**
- `data/font_alloc_v2.json` — 字库分配方案 v2（254 场景，0 溢出/0 不可编码）
- `data/font_segments_report.json` — 297 个字库段扫描报告

**文档**
- `docs/improvement_compliance.md` — 《汉化改进》第 1-22 项完成报告

### 《龙战士4汉化改进》第 1-22 项落实

| # | 建议 | 落实 |
|---|------|------|
| 1 | 三个核心问题 | 字体路径必填 / 场景字库写入 / 禁止静默失败 |
| 2 | 原版字库 Round-trip | 100% SHA256 一致（并破解像素布局） |
| 3 | 字体生成函数 | `generate_glyphs(alloc, font_path, ...)`，无 fallback |
| 4 | 二值字模 | `--threshold`（默认 96）+ nibble 语义修正 |
| 5 | `build_main_font` 不写死 | `build_font_block(index_map, glyphs, count)` |
| 6 | 未知字不变索引 0 | `raise ValueError` |
| 7 | 统一 GlyphCodec | `encode_char()` / `encode_text()` |
| 8 | Scene Font 依赖文件名 | 逐文件独立映射 + 3 项测试 |
| 9 | 不只写 INIT Seg7 | `find_font_segments()` 按 sig 定位（297 段） |
| 10 | 先扫描字库段 | `scan_fonts.py` → 219KB 报告 |
| 11 | 修场景字反解 | 传入 SCENE 映射 |
| 12 | 读取 `font_alloc.json` | `load_scene_tables()`（9769 条） |
| 13 | 导出"字库来源" | `decode_with_sources()` + `--font-source` |
| 14/15 | `build_text_segment` 精确匹配 | 有序消耗 + 耗尽/剩余双校验 |
| 16/17/18 | EMI relocation | `rebuild_emi()` + ISO 搬移（实测 8 段/253 文件） |
| 19 | `check_text_size.py` | 270 段 → 262 可原地 / 8 超长 |
| 20 | 严格报告 | 10 项真实统计 + 缺失/未写入双重复核 raise |
| 21 | 分配一致性检查 | 7 类检查 + 7 项测试 |
| 22 | 不自动重新分配 | `--alloc` 必选，`--auto-alloc` 默认关闭 |

### 修复

- **字库像素布局**：确认字库段按 **64 字节/行 × 10 glyph/行** 存储（128px 宽），
  高 nibble 在前。此前按连续 72B 平铺导致游戏内文本乱码。
- **字模 nibble 值**：原版字库中 **值 1 = 笔画主体（白色）**、值 8 = 笔画右/下边缘（阴影）。
  此前用值 8 生成笔画导致游戏显示"淡色碎片"。
- **EMI 段表格式**：修正段表每项 16 字节（不是 8 字节）的重建逻辑。
- **EMI 头长度**：修正为 16 字节（段表从 0x10 开始）。
- **`export_text.py` 缺失 DSZ 导入**：原脚本 `sec_offset += ssz + (-ssz % DSZ)` 会
  `NameError`，从未跑通；现已修复。
- **build_text_segment 顺序匹配**：修复空 tgt 条目未占位导致的编码列表错位
  （曾导致 250 个文本段被静默跳过）。
- **encode_char position 参数**：修复 `position=None` 时的格式化异常。
- **patch_bin 读取 font_alloc**：修复文件头的字面量 `\ufeff` 导致的 JSON 解析失败。
- **INIT.EMI 场景字合并**：修复场景字被主字库写入覆盖的问题。
- **emi_expand 目录记录定位**：支持 WORLD/ 与 SYSTEM/ 两个顶层目录。

### 变更

- `bof4lib.py` 新增字库布局常量与 `glyph_offset()` / `get_glyph()` / `set_glyph()`
- `bof4lib.py` 场景索引上限从 97 放宽到 511（0x13 单字节编码上限）
- `build_encoded_map()` 改为返回有序列表（匹配原始段的非空字符串顺序）
- `export_text.py` 新增 `decode_with_sources()` / `summarize_sources()` / `--font-source`
- `check_text_size.py` 新增 `--tolerate-unmapped`（未映射按 2 字节占位估算）
- `patch_bin.py` 严格报告改为 10 项真实统计（含"无翻译段"）
- `patch_bin.py` 支持场景字库写入 + EMI relocation
- 字库分配算法重写：跨文件字符优先全局，无字库段文件强制全局

### 验证

- **原版字库 Round-trip 100% 一致**（SHA256: `d796d4e4...`）
- 字库布局渲染验证：索引 0-19 字形与字符表完全匹配
  （中/大/砂/嵐/泥/流/回/復/天/光/海/特/異/点/最/防/御/変/身/銃）
- 单元测试 **31 项全部通过**
- 文本段空间分类与文档预期一致：270 段 / 262 可原地 / 8 超长
- 字符用量分析：1803 字符，场景字平均 38.1 / 最大 107（≤128 上限），0 溢出
- 端到端流水线：251 原地写入 + 8 relocation + 253 场景字库，0 错误
- 建议22 校验：无 `--alloc` 时正确报错并提示使用固定方案

### 已知问题

- **字库加载路径未确认**：INIT.EMI seg7 的修改在模拟器中不生效
  （极简测试：将 glyph 0/100 改为全白方块，游戏内无任何变化）
- **7 个无字库段系统文件**：CAMP/SHOP/MASTER/MSHOP/SGAMEN/SGAMENX/COMMU03
  的字符并集 613 > 全局 554 容量
- **8 个超长文本段**：原段 2048B → 新文本需 4096B（工具已就绪，已实测 relocation）
- **镜像体积膨胀**：全量方案因 253 个 EMI 搬移导致 697MB → 846MB

---

## [v0.1] - 2026-09-16

### 新增

- 全量日文文本提取（17676 条，270 个文本段，262 个 EMI 文件）
- 全量中文翻译（15049 条非空，100% 完成）
- 字库索引对照表（主字库 349 / 小字库 205 / 场景字库）
- 基础工具：`bof4lib.py`、`export_text.py`、`patch_bin.py`、`apply_patch.py`
- 破解技术文档 `docs/cracking_analysis.md`
- 原文/译文文本导出

### 已知问题

- 文本段仅 262/270 写入
- 场景字库未写入
- 字模像素排列未验证
- 模拟器显示异常

---

## 未发布

### 待办

- [ ] 确认游戏字库加载路径（逆向 SLPS_027.28）
- [ ] 解决 7 个无字库段系统文件的容量问题
- [ ] 8 个超长文本段的 EMI relocation
- [ ] 镜像体积优化（紧凑重排）
- [ ] 生成可用的 xdelta 补丁
- [ ] 实机/模拟器全流程验证

> AI生成