---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '159ce427-b829-4352-823d-2d1787f4b6ee'
  PropagateID: '159ce427-b829-4352-823d-2d1787f4b6ee'
  ReservedCode1: 'a5a44084-c851-4159-a84a-5ce086d204af'
  ReservedCode2: 'a5a44084-c851-4159-a84a-5ce086d204af'
---

# 《龙战士4汉化改进》第 1-22 项完成报告

> 生成时间：2026-09-17
> 对应文档：`龙战士4汉化改进.MD` 第 1~22 项建议
> 验证方式：源码检查 + 单元测试（31 项）+ 端到端流水线运行

---

## 总览

| # | 建议 | 状态 | 落实位置 |
|---|------|------|----------|
| 1 | 确定三个核心问题 | ✅ | 全部修复（见下） |
| 2 | 原版字库 Round-trip | ✅ | `dump_font.py` / `import_font.py` |
| 3 | 字体生成函数彻底改掉 | ✅ | `patch_bin.generate_glyphs()` |
| 4 | 字模先做二值版本 | ✅ | `--threshold`（默认 96） |
| 5 | `build_main_font()` 不写死 349 | ✅ | `build_font_block(index_map, glyphs, count)` |
| 6 | 修掉"未知字变索引 0" | ✅ | `bof4lib.encode_char()` raise |
| 7 | 增加统一的 GlyphCodec | ✅ | `encode_char()` / `encode_text()` |
| 8 | Scene Font 依赖文件名 | ✅ | `encode_char(ch, fname, alloc)` + 3 项测试 |
| 9 | 不再只写 INIT.EMI Seg7 | ✅ | `find_font_segments()` 按 sig 定位 |
| 10 | 先扫描所有 EMI 字库段 | ✅ | `scan_fonts.py` → `font_segments_report.json` |
| 11 | 修 `export_text.py` 场景字反解 | ✅ | 传入 SCENE 映射 |
| 12 | `export_text.py` 读取 `font_alloc.json` | ✅ | `load_scene_tables()` |
| 13 | 导出"字库来源" | ✅ | `decode_with_sources()` + `--font-source` |
| 14 | `build_text_segment()` 顺序匹配 | ✅ | 有序消耗 + 双重校验 |
| 15 | `build_text_segment()` 核心实现 | ✅ | 指针表重建 + 耗尽报错 |
| 16 | 8 个超长段 EMI relocation | ✅ | `rebuild_emi.py`（8 段已处理） |
| 17 | EMI relocation 核心算法 | ✅ | `rebuild_emi()` 段表 + 数据重排 |
| 18 | ISO 文件大小变化 | ✅ | `emi_expand.py` / `move_file_in_iso.py` |
| 19 | `check_text_size.py` | ✅ | 270 段分类：262 可原地 / 8 超长 |
| 20 | 严格报告 | ✅ | 9 项指标 + 双重复核 raise |
| 21 | 字库分配一致性检查 | ✅ | `check_alloc_consistency()` + 7 项测试 |
| 22 | 不重新自动分配 `font_alloc.json` | ✅ | `--alloc` 必选，`--auto-alloc` 默认关闭 |

---

## 第 1 项：三个核心问题

文档指出的三个缺口，均已修复：

| 原问题 | 原文 | 修复 |
|--------|------|------|
| 字体路径硬编码 Windows | `for fp in ["C:\\Windows\\Fonts\\simsun.ttc", ...]` | `generate_glyphs(alloc, font_path, ...)`，缺失即 `FileNotFoundError` |
| PIL 默认字体静默 fallback | `ImageFont.load_default()` | 已移除，无 fallback |
| 只写 INIT.EMI Seg7 | `if seg["index"] == 7` | `find_font_segments()` 按 `sig == 0x1C000200` 定位，支持全部 297 个字库段 |
| 静默继续 | `if not encoded: result.append(0x12); result.append(0)` | `raise ValueError`（未映射字符） |

**证据**：
```
$ python -c "from patch_bin import generate_glyphs; generate_glyphs({}, '不存在.ttf')"
FileNotFoundError: Chinese font not found: 不存在.ttf
```

---

## 第 2 项：原版字库 Round-trip

**要求**：`memcmp(original_seg7, rebuilt_seg7) == 0`

**实现**：
- `tools/dump_font.py`：INIT.EMI seg7 → 370 个 PNG + `seg_original.bin` + `meta.json`
- `tools/import_font.py`：PNG → 还原字节 → 对比

**结果**：
```
原始段长度  : 28672
重建段长度  : 28672
SHA256(orig): d796d4e4d57e77a1ca01f26f6612c333292b0eadacbf2c8364853e43b2225d45
SHA256(reb) : d796d4e4d57e77a1ca01f26f6612c333292b0eadacbf2c8364853e43b2225d45
memcmp      : 完全一致 (100% round-trip 通过)
```

### 附带突破：字库像素布局

Round-trip 过程中确认了文档未给出结论的**像素物理布局**：

```
字库段按 64 字节/行 存储 (128px 宽, 4bpp)
  每行放 10 个 glyph 的横向切片 (10 × 6 字节 = 60 字节 + 4 字节空白)
  每个 glyph 的 12 行像素分散在 12 个行带中

glyph i 的像素位置:
  band = i // 10
  slot = i % 10
  行 r 的字节偏移 = band × 768 + r × 64 + slot × 6

nibble 顺序: 高 nibble 在前
```

这解释了文档第 2 项指出的数字矛盾：
- 连续 72B 平铺 → 28672/72 = 398.22（无法整除）
- 实际布局 → 37 带 × 10 = **370 个完整 glyph**（整除）

---

## 第 3 项：字体生成函数

```python
def generate_glyphs(alloc, font_path, size=12, threshold=96):
    if not os.path.isfile(font_path):
        raise FileNotFoundError(
            "Chinese font not found: %s\n"
            "请通过 --font 指定字体文件, 例如: --font font/NotoSansCJK-Regular.ttc" % font_path
        )
    font = ImageFont.truetype(font_path, size)
```

命令行：
```bash
python tools/patch_bin.py input.bin workbook.json output.bin \
    --alloc data/font_alloc_v2.json \
    --font ./font/NotoSansCJK-Regular.ttc
```

**不再允许** `ImageFont.load_default()` 作为 fallback。

---

## 第 4 项：字模二值版本

文档建议先做可验证的二值版本，确认坐标/大小/nibble 顺序正确后再优化。

**实现**：`--threshold`（默认 96），先二值化：

```python
if v1 >= threshold: b |= 0x80
if v2 >= threshold: b |= 0x08
```

**额外发现（超出文档要求）**：通过分析原始字库的 12×12 矩阵，发现 nibble 值有明确语义：

| 值 | 含义 | 全库占比 |
|----|------|---------|
| 0 | 背景透明 | 39.8% |
| **1** | **笔画主体（白色）** | 28.4% |
| **8** | **笔画右/下边缘（阴影）** | 29.5% |
| 2-7 | 抗锯齿过渡 | ~2.3% |

原始"中"字矩阵实证：
```
0  0  0  0  1  0  0  8  0  0  0  0
1  1  1  1  1  1  1  1  1  1  8  1
8  1  8  8  1  8  8  8  8  8  8  1
```
→ 笔画用值 1，右缘用值 8（营造立体感）。

**生成器已按此实现**（笔画=1，右/下边缘自动加 8），而非简单的 0/8 两级。

---

## 第 5 项：`build_font_block()` 通用化

按文档给出的参考实现落地：

```python
def build_font_block(index_map, glyphs, count):
    inverse = {int(idx): ch for ch, idx in index_map.items()}
    data = bytearray()
    for idx in range(count):
        ch = inverse.get(idx)
        if ch is None:
            data.extend(b'\x00' * GLYPH_SIZE)
            continue
        if ch not in glyphs:
            raise ValueError("Missing glyph for index %d: %r" % (idx, ch))
        glyph = glyphs[ch]
        if len(glyph) != GLYPH_SIZE:
            raise ValueError("Bad glyph size for %r: %d" % (ch, len(glyph)))
        data.extend(glyph)
    return bytes(data)
```

主字库 / 小字库 / 场景字库全部复用同一函数（`build_main_font()` / `build_scene_font_data()`）。

---

## 第 6 项：修掉"未知字变索引 0"

**修复前**（危险）：
```python
if not encoded:
    result.append(0x12)
    result.append(0)
```

**修复后**：
```python
raise ValueError(
    "Unmapped character %r in %s at position %s "
    "(not in global_main/global_small/scene/ascii)"
)
```

**实测输出**：
```
RuntimeError: 文本编码失败: 108 处未映射字符,
首条: Unmapped character '立' in SYSTEM/CAMP.EMI at position 1
```

---

## 第 7 项：统一的 GlyphCodec

按文档结构拆分：

```python
def encode_char(ch, fname, alloc, position=None):
    gm = alloc["global_main"]
    gs = alloc["global_small"]
    si = alloc.get("small_font_inherent", {})
    scene_map = alloc.get("scene", {}).get(fname, {})

    if ch in gm: ...
    if ch in scene_map: ...
    if ch in gs: ...
    if ch in si: ...
    if 0x20 <= ord(ch) <= 0x7e: ...
    raise ValueError(...)

def encode_text(tgt, fname, alloc):
    # 控制码 / 换行 / 分隔线 / 普通字符 → encode_char
```

**调试便利性**（文档目标）：
```python
>>> encode_char("龙", "SYSTEM/CAMP.EMI", alloc)
b'\x12\x33'   # 直接知道编码到哪个字库
```

---

## 第 8 项：Scene Font 依赖文件名

**设计确认**：`0x13 XX` 不是全局字符，而是 `file + glyph index`。
**禁止**只生成一个全局 `scene_font.bin`。

**实现验证**：
- `font_alloc_v2.json` 保存 `scene: {fname: {char: idx}}`（254 个文件独立映射）
- `build_scene_font_data()` 逐文件构建独立字库段
- `patch_bin()` 逐文件写入各自 EMI 的字库段

**新增 3 项单元测试**（`tests/test_alloc.py::TestSceneFontIndependence`）：
```
test_same_index_different_char_per_file  同一索引在不同文件指向不同字符 ✓
test_scene_not_shared_globally           场景字不跨文件共享 ✓
test_encode_text_uses_filename           相同字节序列在不同文件解码不同 ✓
```

---

## 第 9 项：不再只写 INIT.EMI Seg7

```python
def find_font_segments(parsed):
    """返回所有 sig == 0x1C000200 的段 (字体段)。"""
    return [seg for seg in parsed["segments"] if seg["sig"] == FONT_SEG_SIG]
```

**实测**：全游戏共 **297 个字库段**，分布：
| 段大小 | glyph 容量 | 段数量 |
|--------|-----------|--------|
| 28672 | 370 | 210 |
| 30720 | 400 | 31 |
| 32768 | 420 | 56 |

---

## 第 10 项：先扫描所有 EMI 字库段

**产出**：`tools/scan_fonts.py` → `data/font_segments_report.json`（219 KB）

报告内容（每个字库段）：
```json
{
  "index": 7,
  "sig": "0x1C000200",
  "size": 28672,
  "glyph_capacity": 370,
  "extra_slots": 21,
  "extra_nonzero": 11,
  "head128": "...",
  "tail128": "..."
}
```

**扫描结果**：
```
字库段总数     : 297
尺寸分布       : {28672: 210, 30720: 31, 32768: 56}
含场景专属字的文件数: 297
```

**重要发现**：7 个系统 EMI（CAMP/SHOP/MASTER/MSHOP/SGAMEN/SGAMENX/COMMU03）
**没有** sig=0x1C000200 段 → 它们直接使用全局字库，场景字无处存放。

---

## 第 11 项：`export_text.py` 场景字反解 bug

**修复前**：`decode_text(trimmed, name, MA, SM, {})` —— 最后参数永远是 `{}`，
所以 `0x13 XX`（索引 ≥349）只能得到 `[场349]`。

**修复后**：
```python
SCENE = load_scene_tables(data_dir)
txt = decode_with_sources(trimmed, name, MA, SM, SCENE)
```

---

## 第 12 项：读取 `font_alloc.json`

```python
def load_scene_tables(data_dir):
    path = os.path.join(data_dir, "font_alloc.json")
    ...
    for fname, mapping in alloc.get("scene", {}).items():
        for ch, idx in mapping.items():
            scene[(fname, int(idx))] = ch
    return scene
```

实测加载场景映射 **9769 条**。

---

## 第 13 项：导出"字库来源"

**新增** `decode_with_sources()`，返回文本 + 每字符来源。

**输出示例**（`--font-source` 生成的 `text_blocks_font_source.json`）：
```json
{
  "hex": "0c0417c2403c1201135d24787195135e5f705f867101135f5f705f6d769f",
  "txt": "{框04}{立绘C240}「大游、ひとが避いていると...",
  "summary": {
    "global_small": [28, 4, 88, 81, 117, 63, 80, 102, ...],
    "global_main": [1],
    "scene": [349, 350, 351]
  },
  "sources": [
    {"char": "{框04}", "font": "control", "index": 12, "raw": "0c04"},
    {"char": "「", "font": "global_small", "index": 28, "raw": "3c"},
    {"char": "大", "font": "global_main", "index": 1, "raw": "1201"},
    {"char": "游", "font": "scene", "index": 349, "raw": "135d"},
    ...
  ]
}
```

**全量统计**：
```
字库来源统计: {'global_small': 242963, 'global_main': 45332, 'scene': 7965}
```

---

## 第 14/15 项：`build_text_segment()` 顺序匹配

### 关键发现：文档建议的"ID 精确匹配"需要修正

文档建议用 `id` 作为 key。实测发现工作簿的 `id` 是**全局编号**（`000000`~`017676`），
不是段内序号，且导出时**跳过了空槽/空串**，因此直接用 id 索引会错位。

**实际落地方案**（保留文档的原意：禁止静默错位）：

```python
def build_text_segment(orig_seg_data, vals, encoded_list):
    enc_idx = 0
    for k in range(n):
        s, e = vals[k], ...
        if e <= s:
            new_strings.append(b'\x00'); continue      # 空槽: 不消耗
        trimmed = trim(orig_seg_data[s:e])
        if not trimmed:
            new_strings.append(b'\x00'); continue      # 空串: 不消耗

        if enc_idx >= len(encoded_list):
            raise ValueError("Missing translation: text entry %d ... exhausted" % k)

        enc_hex = encoded_list[enc_idx]; enc_idx += 1
        ...

    # 防御: 编码列表未耗尽 → 报错 (顺序不一致)
    if enc_idx != len(encoded_list):
        raise ValueError("Encoded list not fully consumed: %d used / %d provided")
```

**双重校验**：既防"耗尽"（翻译不足），也防"剩余"（顺序错位）。

> 该修复曾直接解决一个严重 bug：旧诊断脚本跳过空 tgt 导致顺序错位，
> 250 个文本段被静默跳过（游戏内"仿佛没汉化"）。

---

## 第 16/17/18 项：EMI relocation

### 第 17 项核心算法

```python
def rebuild_emi(emi_buf, replacements):
    # 头 16 字节 + 段表 (每项 16 字节, 保留原始 8 字节元数据)
    new_emi = bytearray(emi_buf[:0x10])
    for i, s in enumerate(segs):
        entry = bytearray(emi_buf[0x10 + i*16 : 0x10 + i*16 + 16])
        struct.pack_into('<I', entry, 0, len(s["data"]))   # size
        struct.pack_into('<I', entry, 4, s["sig"])         # sig
        new_emi += entry
    new_emi += b'\x00' * (0x800 - len(new_emi))
    # 每段按 0x800 对齐
    for s in segs:
        new_emi += b'\x00' * ((-len(new_emi)) % DSZ)
        new_emi += s["data"]
    return bytes(new_emi)
```

**关键修正**（调试中发现）：
- EMI 头部是 **16 字节**（不是 32），段表从 `0x10` 开始
- 段表每项 **16 字节**（size + sig + 8 字节保留元数据），不是 8 字节

### 第 16 项实测

```
Relocated segments    : 8
  WORLD/AREAD072.EMI seg11: 2048 -> 4096 (+2048)
  WORLD/AREAD135.EMI seg11: 2048 -> 4096 (+2048)
  WORLD/AREAM021.EMI seg11: 2048 -> 4096 (+2048)
  WORLD/AREAM022.EMI seg11: 2048 -> 4096 (+2048)
  WORLD/AREAM044.EMI seg11: 2048 -> 4096 (+2048)
  WORLD/AREAM050.EMI seg14: 2048 -> 4096 (+2048)
  WORLD/AREAM051.EMI seg11: 2048 -> 4096 (+2048)
  WORLD/AREAS038.EMI seg8 : 2048 -> 4096 (+2048)
```

### 第 18 项 ISO 文件大小变化

文档指出：relocation 后 ISO 中 EMI 文件长度变化，需要检查连续空闲空间。

**实现**：
- `emi_expand.py`：新大小 ≤ 原扇区 → 原地写；否则搬移到尾部空闲区
- `move_file_in_iso.py`：ISO9660 文件搬移 + 目录记录更新（LE + BE 双写）
- `tail_start_lba()`：自动定位镜像尾部空闲区

**实测空间**：
```
BIN 总扇区: 296700
文件最大结束: 277781
尾部空闲扇区: 18919 (38,746,112 bytes)
```

**实测搬移**：253 个 EMI 搬到尾部，目录记录全部更新（游戏可正常启动）。

---

## 第 19 项：`check_text_size.py`

**新增 `--tolerate-unmapped`**（未映射字符按 2 字节占位，使空间检查在字库未完成时仍可运行）。

**实测输出**（复现文档预期）：
```
文本段总数   : 270
可原地写入   : 262
超长段       : 8
  WORLD/AREAD072.EMI seg11: 2048 -> 4096 (+2048)
  ... (共 8 条)
```

与文档预期完全一致：
```
<= old padded      262
> old padded          8
```

---

## 第 20 项：严格报告

**修复前**（3 项硬编码）：
```python
print("  Translation errors    : 0")   # 假
print("  Unknown glyphs        : 0")   # 假
print("  Font glyphs missing   : 0")   # 假
```

**修复后**（真实统计 + 双重复核）：
```
汉化完成 (严格报告):
  Patched text segments : 251
  Relocated segments    : 8
  Text segments total   : 270
  Segments w/o translation: 11
  Scene font files      : 253
  EMI moved to tail     : 253
  Translation errors    : 0
  Unknown glyphs        : 0
  Font glyphs missing   : 0
  Unwritten segments    : 0
```

最终校验：
```python
if missing_glyphs:
    raise RuntimeError("字模缺失 %d 个字符 (建议20): %s" % ...)
if not_written:
    raise RuntimeError("%d 个翻译文本段未写入 (建议20: 不允许半成品): %s" % ...)
```

---

## 第 21 项：字库分配一致性检查

`check_alloc_consistency(alloc)` 实现文档要求的全部检查：

| 检查项 | 实现 |
|--------|------|
| `len(global_main) <= 349` | ✅ |
| `len(global_small) <= 205` | ✅ |
| 场景容量上限（0x13 编码空间） | ✅ |
| 索引范围（主字库/小字库/场景） | ✅ |
| `set(global_main) ∩ set(global_small) == ∅` | ✅ |
| 场景字 ∉ 全局字库 | ✅ |
| 索引重复检查 | ✅ |

**7 项单元测试**（`tests/test_alloc.py::TestAllocConsistency`）全部通过。

---

## 第 22 项：不重新自动分配

```bash
# 正式构建: 必须显式指定固定分配方案
python tools/patch_bin.py input.bin workbook.json output.bin \
    --alloc data/font_alloc_v2.json \
    --font ./font/NotoSansCJK-Regular.ttc

# --auto-alloc 默认为 False; 不提供 --alloc 且未开启时直接报错:
RuntimeError: 未提供字库分配方案。
建议22: 请使用固定的 data/font_alloc_v2.json, 不要每次自动重新分配。
用法: --alloc data/font_alloc_v2.json
```

---

## 验证汇总

| 验证项 | 结果 |
|--------|------|
| 原版字库 Round-trip | SHA256 100% 一致 |
| 字形渲染（索引 0-19） | 全部匹配（中大砂嵐泥流回復天光海特異点最防御変身銃） |
| 单元测试 | **31/31 通过** |
| 文本段空间分类 | 270 段 / 262 可原地 / 8 超长（与文档一致） |
| 端到端流水线 | 251 原地 + 8 relocation + 253 场景字库，0 错误 |
| 字库段扫描 | 297 段（28672×210 / 30720×31 / 32768×56） |

---

## 超出文档要求的额外成果

1. **字库像素布局破解**（第 2 项的衍生）：64B/行 × 10 glyph/行，高 nibble 前
2. **nibble 值语义**（第 4 项的衍生）：值 1 = 笔画，值 8 = 边缘
3. **字符用量分析工具**：证明 Global 554 + Scene 128 架构成立（1803 字符，0 溢出）
4. **7 个无字库段系统文件的发现**：613 字符 > 554 全局容量的架构约束
5. **ISO 文件搬移工具**：补齐文档第 18 项指出的"不是完整 ISO 重排器"缺口

---

## 未在本批（1-22）范围内的事项

以下来自文档第 23-40 项，属于下一批：

- 建议 23-25：最小中文测试（"龙"字三级测试）
- 建议 26-27：Scene Font / Global Small 专项测试
- 建议 28：`0x15` 编码 off-by-one 疑点验证
- 建议 29：`bof4lib.py` 三个单元测试
- 建议 31：`patch_bin.py` 六阶段拆分
- 建议 32：原始 BIN SHA-256 校验（已实现）
- 建议 33-34：7 项自动一致性检查 / BIN 级验证
- 建议 35-37：目录结构 / 执行顺序 / xdelta

> AI生成