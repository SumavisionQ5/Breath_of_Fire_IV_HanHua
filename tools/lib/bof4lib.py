# -*- coding: utf-8 -*-
"""
bof4lib.py — 龙战士4 (Breath of Fire IV) 汉化工具共享库

提供 ISO 9660 BIN/CUE 镜像读写、EMI 文件解析、
文本段检测、字体格式处理等通用功能。

遵循《龙战士4汉化改进》建议:
  - 建议6: 未知字符禁止静默变 0x12 0x00, 必须 raise ValueError
  - 建议7: 拆出 encode_char() 单一字符编码函数
  - 建议14/15: build_text_segment() 使用 ID 精确匹配, 缺失即报错

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import struct
import os

# ============================================================
# 常量
# ============================================================

SEC = 2352      # 扇区字节数 (Mode 2 raw)
DOFF = 24       # 数据偏移 (跳过扇区头)
DSZ = 2048      # 每扇区数据大小
EMI_MAGIC = b"MATH_TBL"  # EMI 文件标识

# 主字库/小字库/场景字库容量常量 (建议5: 不再写死)
MAIN_FONT_COUNT = 349      # 全局主字库字模数
SMALL_FONT_COUNT = 205     # 全局小字库字模数
SCENE_FONT_MAX = 97        # 每场景最大字模数
SCENE_FONT_BASE = 349      # 场景字库起始索引
GLYPH_SIZE = 72            # 每字模字节数 (12x12 4bpp)
FONT_SEG_SIG = 0x1C000200  # 字库段标识

# 字库段像素布局 (21 列网格, 已经 VRAM 转储逐字节比对 + 字形渲染双重验证):
#   VRAM 中字库区宽 256px = 21 列 x 12px (每列 6 字节, 21*6 = 126 字节)
#   glyph i 位于 col = i % 21, row = i // 21, 尺寸 12x12 像素
#   VRAM 每行步进 2048 字节; 段文件每 2048 字节块在 VRAM 中占 32 行 x 64 字节,
#   相邻两块并排 (左块字节列 0-63 / 右块 64-127), 故段内偏移须经 _vram_to_seg 换算。
#   nibble 顺序: 高 nibble 在前 (每字节 2 像素, 高位 = 左侧像素)
#
#   历史说明: 早期版本误按 "64B/行 x 10 glyph 带" 实现, 导致字模写入错位,
#   游戏中表现为字形碎片/乱码。已由 xcheck 系列实验证伪并改为 21 列布局。
FONT_GRID_COLS = 21         # 字库网格列数
FONT_CELL_PX = 12           # 字形像素尺寸 (12x12)
FONT_CELL_ROW_BYTES = 6     # 字形每行字节数 (12px @ 4bpp)
FONT_CELL_ROWS = 12         # 字形行数
FONT_BLOCK_BYTES = 2048     # VRAM 单次上传块大小
FONT_BLOCK_COL_BYTES = 64   # 单块在 VRAM 中的行宽 (字节)
FONT_BLOCK_ROWS = 32        # 单块在 VRAM 中的行数

# 兼容别名 (旧调用方仍可用)
FONT_ROW_BYTES = FONT_BLOCK_COL_BYTES
FONT_GLYPHS_PER_ROW = FONT_GRID_COLS
FONT_GLYPH_ROW_BYTES = FONT_CELL_ROW_BYTES
FONT_BAND_ROWS = FONT_CELL_ROWS
FONT_BAND_BYTES = FONT_CELL_ROWS * FONT_BLOCK_COL_BYTES


def _vram_to_seg(row, col_byte):
    """VRAM 字库区坐标 -> 段内字节偏移。

    Args:
        row: int, VRAM 行号 (相对字库区顶部)
        col_byte: int, 行内字节列 (0-127); 0-63 属左块, 64-127 属右块

    Returns:
        int: 段内字节偏移
    """
    blk = 2 * (row // FONT_BLOCK_ROWS) + (1 if col_byte >= FONT_BLOCK_COL_BYTES else 0)
    seg_row = blk * FONT_BLOCK_ROWS + (row % FONT_BLOCK_ROWS)
    return seg_row * FONT_BLOCK_COL_BYTES + (col_byte % FONT_BLOCK_COL_BYTES)


def glyph_cell(i):
    """glyph i 左上角在 VRAM 字库区中的 (row, col_byte)。"""
    return (i // FONT_GRID_COLS) * FONT_CELL_ROWS, (i % FONT_GRID_COLS) * FONT_CELL_ROW_BYTES


def glyph_offset(i):
    """glyph i 首行起始的段内字节偏移 (21 列布局)。"""
    r, c = glyph_cell(i)
    return _vram_to_seg(r, c)


def glyph_capacity(seg_size):
    """给定字库段字节数, 返回能完整容纳的 glyph 数。

    Args:
        seg_size: int, 字库段数据字节数

    Returns:
        int: 可容纳的 glyph 上限 (索引 0 .. n-1)
    """
    n = 0
    while n < 4096:
        r0, c0 = glyph_cell(n)
        ok = True
        for rr in range(FONT_CELL_ROWS):
            for k in range(FONT_CELL_ROW_BYTES):
                if _vram_to_seg(r0 + rr, c0 + k) >= seg_size:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            return n
        n += 1
    return n


def glyph_seg_size(total_slots, align=FONT_BLOCK_BYTES):
    """容纳 total_slots 个 glyph 所需的字库段字节数 (向上对齐)。

    Args:
        total_slots: int, 需要的 glyph 槽数
        align: int, 对齐字节数 (默认 2048)

    Returns:
        int: 段字节数
    """
    if total_slots <= 0:
        return 0
    r0, c0 = glyph_cell(total_slots - 1)
    need = 0
    for rr in range(FONT_CELL_ROWS):
        for k in range(FONT_CELL_ROW_BYTES):
            off = _vram_to_seg(r0 + rr, c0 + k)
            if off + 1 > need:
                need = off + 1
    return ((need + align - 1) // align) * align


def get_glyph(seg_data, i):
    """按 21 列布局提取 glyph i 的 72 字节 (12 行 x 6 字节)。

    Args:
        seg_data: bytes, 字库段数据
        i: int, glyph 索引

    Returns:
        bytes: 72 字节字形数据 (行优先)
    """
    r0, c0 = glyph_cell(i)
    n = len(seg_data)
    out = bytearray()
    for r in range(FONT_CELL_ROWS):
        for k in range(FONT_CELL_ROW_BYTES):
            off = _vram_to_seg(r0 + r, c0 + k)
            out.append(seg_data[off] if 0 <= off < n else 0)
    return bytes(out)


def set_glyph(seg_data, i, glyph):
    """按 21 列布局把 72 字节 glyph 写回字库段。

    Args:
        seg_data: bytearray, 字库段数据 (可修改)
        i: int, glyph 索引
        glyph: bytes, 72 字节字形数据

    Raises:
        ValueError: glyph 长度不是 GLYPH_SIZE
    """
    if len(glyph) != GLYPH_SIZE:
        raise ValueError("Bad glyph size: %d (expected %d)" % (len(glyph), GLYPH_SIZE))
    r0, c0 = glyph_cell(i)
    n = len(seg_data)
    for r in range(FONT_CELL_ROWS):
        for k in range(FONT_CELL_ROW_BYTES):
            off = _vram_to_seg(r0 + r, c0 + k)
            if 0 <= off < n:
                seg_data[off] = glyph[r * FONT_CELL_ROW_BYTES + k]

# 控制码名称 → 字节前缀
# 注: "选择" 曾误标为 0x14, 实证 0x14 为 3 参数未知语义码 (CAMP 字节对齐), 已改名 "码14";
#      未定位语义的码统一命名 "码XX", 保证 decode/encode 可逆。
CTRL_CODES = {
    "框": 0x0c, "队员": 0x04, "道具": 0x09, "占位": 0x07,
    "打字": 0x10, "延时": 0x16, "立绘": 0x17, "色": 0x05,
    "引2": 0x19, "引": 0x18, "金钱": 0x1c,
    "符号2": 0x15,
    # 语义未定位的控制码 (参数已实证, 名字保证可逆)
    "码03": 0x03, "码08": 0x08, "码0A": 0x0a, "码0B": 0x0b,
    "码11": 0x11, "码14": 0x14, "码1A": 0x1a, "码1D": 0x1d,
    "码1E": 0x1e, "码1F": 0x1f,
}

# 控制码长度表 (字节码 → 码+参数总字节数)
# 语义: 该码在文本流中占用的总字节数 (含码字节本身)。
# 修正史 (2026-09-18, EXE 反汇编 + CAMP 字节对齐 + 全量数据网格三重实证):
#   - 旧表 0x05: 1 是唯一错项 (应为 2), 其余旧值实为"总长"语义且基本正确
#   - 旧表缺失的码 (0x01/02/03/08/0A/0B/11/12/13/1A/1D/1E/1F/20) 已补全
#   - 0x14 = 4 (3 参数): 上下文 "0c8a 14 820c82 77 5f" = "{框8A}はい" 实证
#   - 0x20 = 1 (0 参数, 空格): dispatcher 0x80138C3C 仅 $s3+=12 推进光标
#   - 0x04/07/09/12/13/15/19: dispatcher 0x8013898C 跳转表各块 $fp=$s2+N 实证
#   - 0x06/1B: {/色}/{等待} 从栈恢复/模板, 0/1 参数
#   - 未知码 (03/08/0A/0B/11/1A/1D/1E/1F): 全量数据网格搜索 unclean=0 定案 0 参数
CTRL_LEN = {
    0x01: 1, 0x02: 1, 0x03: 1, 0x04: 2, 0x05: 2, 0x06: 1, 0x07: 2,
    0x08: 1, 0x09: 3, 0x0a: 1, 0x0b: 1, 0x0c: 2, 0x0d: 1, 0x0e: 1,
    0x0f: 1, 0x10: 2, 0x11: 1, 0x12: 2, 0x13: 2, 0x14: 4, 0x15: 2,
    0x16: 2, 0x17: 3, 0x18: 3, 0x19: 3, 0x1a: 1, 0x1b: 2, 0x1c: 2,
    0x1d: 1, 0x1e: 1, 0x1f: 1, 0x20: 1,
}

# 控制码可读名称
# 参数占位符数 = CTRL_LEN[b] - 1, 保证 decode 格式化成功 (失败则兑底 {码XX...})。
CTRL_NAME = {
    0x01: "\n", 0x02: "\n---\n",
    0x03: "{码03}", 0x04: "{队员%02X}", 0x05: "{色%02X}", 0x06: "{/色}",
    0x07: "{占位%02X}", 0x08: "{码08}", 0x09: "{道具%02X%02X}",
    0x0a: "{码0A}", 0x0b: "{码0B}", 0x0c: "{框%02X}",
    0x0d: "{特效}", 0x0e: "{码0E}", 0x0f: "{/特效}", 0x10: "{打字%02X}",
    0x11: "{码11}", 0x14: "{码14%02X%02X%02X}", 0x16: "{延时%02X}",
    0x17: "{立绘%02X%02X}", 0x18: "{引%02X%02X}", 0x19: "{引2 %02X%02X}",
    0x1a: "{码1A}", 0x1b: "{等待%02X}", 0x1c: "{金钱%02X}",
    0x1d: "{码1D}", 0x1e: "{码1E}", 0x1f: "{码1F}",
}


# ============================================================
# ISO 9660 读写
# ============================================================

def read_file_from_iso(iso_data, lba, size):
    """从 BIN 镜像中按扇区读取文件数据。

    Args:
        iso_data: bytes, 完整的 BIN 文件内容
        lba: int, 文件的 LBA (逻辑块地址)
        size: int, 文件大小 (字节)

    Returns:
        bytes: 文件数据
    """
    buf = bytearray()
    for i in range((size + DSZ - 1) // DSZ):
        off = (lba + i) * SEC + DOFF
        buf.extend(iso_data[off:off + DSZ])
    return bytes(buf[:size])


def write_file_to_iso(modified, lba, file_data, file_size):
    """将文件数据写入 BIN 镜像 (按扇区对齐)。

    Args:
        modified: bytearray, 可修改的 BIN 数据副本
        lba: int, 文件的 LBA
        file_data: bytes, 要写入的文件数据
        file_size: int, 原始文件大小 (用于扇区对齐)
    """
    for i in range((file_size + DSZ - 1) // DSZ):
        off = (lba + i) * SEC + DOFF
        start = i * DSZ
        end = min(start + DSZ, len(file_data))
        chunk = file_data[start:end]
        if len(chunk) < DSZ:
            chunk = chunk + b'\x00' * (DSZ - len(chunk))
        modified[off:off + DSZ] = chunk


def parse_dir(iso_data, lba, size):
    """解析 ISO 9660 目录记录。

    Returns:
        list of (name, lba, size, is_dir)
    """
    out = []
    off = 0
    while off < size:
        si = off // DSZ
        so = off % DSZ
        base_off = (lba + si) * SEC + DOFF + so
        b = iso_data[base_off:base_off + 256]
        if not b:
            break
        rl = b[0]
        if rl == 0:
            off = (si + 1) * DSZ
            continue
        if len(b) < rl:
            break
        elba = struct.unpack_from('<I', b, 2)[0]
        esz = struct.unpack_from('<I', b, 10)[0]
        flags = b[25]
        nl = b[32]
        name = b[33:33 + nl]
        if name not in (b'\x00', b'\x01'):
            out.append((
                name.decode('ascii', 'replace').split(';')[0],
                elba, esz, bool(flags & 2)
            ))
        off += rl
    return out


def list_iso_files(iso_data):
    """递归解析 ISO 目录树，返回所有文件列表。

    Returns:
        list of (name, lba, size)
    """
    root = parse_dir(iso_data, 22, DSZ)
    binf = [x for x in root if x[0] == 'BIN'][0]
    sub = parse_dir(iso_data, binf[1], binf[2])
    files = []
    for nm, lba, sz, isd in sub:
        if isd:
            for n2, l2, s2, d2 in parse_dir(iso_data, lba, sz):
                if not d2:
                    files.append((nm + "/" + n2, l2, s2))
        else:
            files.append((nm, lba, sz))
    return files


# ============================================================
# EMI 文件解析
# ============================================================

def parse_emi(buf):
    """解析 EMI 文件，返回段表信息。

    EMI 头部 32 字节:
      0x00: u16 seg_count
      0x02: u16 version
      0x08: 8 bytes "MATH_TBL"
      0x10: u32 data_size
      0x14: u32 load_addr
      0x18: u32 id

    段表从 0x10 开始，每段 16 字节:
      u32 size, u32 sig

    段数据从 0x800 开始，每段按 2048 字节对齐。

    Returns:
        dict with 'count', 'segments', 'total_size'
        segment: {index, offset, size, sig, data, padded_size, table_offset}
    """
    if len(buf) < 32 or buf[8:16] != EMI_MAGIC:
        return None
    cnt = struct.unpack_from('<H', buf, 0)[0]
    segments = []
    sec_offset = 0x800
    for i in range(cnt):
        base = 0x10 * (i + 1)
        if base + 8 > len(buf):
            break
        ssz = struct.unpack_from('<I', buf, base)[0]
        sig = struct.unpack_from('<I', buf, base + 4)[0]
        padded = ssz + (-ssz % DSZ)
        segments.append({
            "index": i,
            "offset": sec_offset,
            "size": ssz,
            "sig": sig,
            "data": buf[sec_offset:sec_offset + ssz],
            "padded_size": padded,
            "table_offset": base,
        })
        sec_offset += padded
    return {"count": cnt, "segments": segments, "total_size": sec_offset}


def find_font_segments(parsed):
    """返回所有 sig == 0x1C000200 的段 (字体段)。

    建议9: 不要依赖 seg["index"] == 7,
    应该按 sig (VRAM/load target) 定位字体段。

    Args:
        parsed: dict, parse_emi() 的返回结果

    Returns:
        list of segment dicts
    """
    if parsed is None:
        return []
    return [seg for seg in parsed["segments"] if seg["sig"] == FONT_SEG_SIG]


def is_text_segment(seg_data):
    """检测 EMI 段是否为文本段。

    文本段特征:
      - 开头 u16 ptsize 为指针表大小
      - 指针表为单调递增的 u16 数组
      - 指针指向段内偏移
      - 文本数据区含 >=3 个 0x12 字节 (字库索引前缀)

    Returns:
        tuple of u16 pointers if text segment, else None
    """
    L = len(seg_data)
    if L < 128:
        return None
    ptsize = struct.unpack_from('<H', seg_data, 0)[0]
    if ptsize < 16 or ptsize % 2 or ptsize >= L:
        return None
    n = ptsize // 2
    try:
        vals = struct.unpack_from('<%dH' % n, seg_data, 0)
    except struct.error:
        return None
    prev = ptsize
    for v in vals:
        if v < prev or v > L:
            return None
        prev = v
    if vals[-1] < L - 16:
        return None
    if seg_data[ptsize:].count(0x12) < 3:
        return None
    return vals


def trim(raw):
    """从原始字节流中提取第一页有效文本 (参数感知)。

    0x00 为页终止符; 控制码 (含 0x12/0x13/0x15) 的参数区按 CTRL_LEN
    整体跳过 —— 参数值可以是 0x00 (如 {立绘XX00}), 不能误判为终止符。
    旧实现只跳过 0x12/0x13/0x15 的参数, 其余控制码参数区的 0x00
    会被误当终止符 (全量实测 4022 槽被误切, 见 2026-09-18 修复)。

    Args:
        raw: bytes, 槽跨度原始数据 (指针表起点到跨度末尾)

    Returns:
        bytes: 第一个 0x00 终止符前的有效数据 (第一页)
    """
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0x00:
            return raw[:i]
        if b < 0x21:
            i += CTRL_LEN.get(b, 1)
        else:
            i += 1
    return raw


def split_pages(raw):
    """按 0x00 终止符把槽跨度切分为多页 (参数感知)。

    游戏对话槽的结构: 每个指针槽跨度内含多个 0x00 分隔的"页",
    引擎逐页显示 (玩家按键翻页)。0x00 同时充当"引用子文本的返回点"
    (0x04/0x07/0x09/0x19 跳转码的返回逻辑, 见 EXE dispatcher)。

    恒等式: b'\\x00'.join(split_pages(raw)) == raw
    (raw 以 0x00 结尾时, 末尾会多一个 b'' 尾元素 —— 那是终止符后的
    存储空位, 不是真实页, 消费方按需丢弃)

    Args:
        raw: bytes, 槽跨度原始数据

    Returns:
        list[bytes]: 各页数据 (均不含终止符)
    """
    pages = []
    start = 0
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0x00:
            pages.append(raw[start:i])
            i += 1
            start = i
            continue
        if b < 0x21:
            i += CTRL_LEN.get(b, 1)
        else:
            i += 1
    pages.append(raw[start:])
    return pages


# ============================================================
# 文本编码 (建议 6/7: encode_char + 严格报错)
# ============================================================

def encode_char(ch, fname, alloc, position=None):
    """将单个字符编码为游戏字节序列 (建议 7)。

    查找优先级:
        1. 全局主字库 global_main (0-348)
        2. 场景字库 scene[fname] (349+)
        3. 全局小字库 global_small (0x15 XX)
        4. 小字库固有位置 small_font_inherent
        5. ASCII (0x20-0x7E)

    Args:
        ch: str, 要编码的字符
        fname: str, EMI 文件名 (用于场景字库)
        alloc: dict, 字库分配方案 (font_alloc.json)
        position: int, 在原文中的位置 (用于错误信息)

    Returns:
        bytes: 编码后的字节序列

    Raises:
        ValueError: 字符无法映射到任何字库 (建议6: 禁止静默)
    """
    gm = alloc.get("global_main", {})
    gs = alloc.get("global_small", {})
    si = alloc.get("small_font_inherent", {})
    scene_map = alloc.get("scene", {}).get(fname, {})

    # 1. 全局主字库 (0-255 → 0x12, 256-348 → 0x13)
    if ch in gm:
        idx = int(gm[ch])
        if idx < 256:
            return bytes((0x12, idx))
        return bytes((0x13, idx - 256))

    # 2. 场景字库 (349+ → 0x13; 上限 511 由 0x13 XX 单字节编码决定, v2 实际用 128)
    if ch in scene_map:
        idx = int(scene_map[ch])
        if SCENE_FONT_BASE <= idx <= 0x1FF:
            return bytes((0x13, idx - 256))

    # 3. 全局小字库扩展 (0-204 → 0x15 idx+1)
    if ch in gs:
        idx = int(gs[ch])
        return bytes((0x15, idx + 1))

    # 4. 小字库固有位置 (直接字节 0x20-0x7E 或 0x15)
    if ch in si:
        idx = int(si[ch])
        if 0x20 <= idx + 0x20 <= 0x7E:
            return bytes((idx + 0x20,))
        return bytes((0x15, idx))

    # 5. ASCII
    cp = ord(ch)
    if 0x20 <= cp <= 0x7E:
        return bytes((cp,))

    # 建议6: 禁止静默变成 0x12 0x00
    pos_str = position if position is not None else '?'
    raise ValueError(
        "Unmapped character %r in %s at position %s "
        "(not in global_main/global_small/scene/ascii)" %
        (ch, fname, pos_str)
    )


def encode_text(tgt, fname, alloc):
    """将中文翻译文本编码为游戏字节序列 (建议 7)。

    控制码 {框06} / {立绘0101} / {引2 5A40} 等原样转换为原始字节；
    \\n → 0x01, --- → 0x02；其余字符逐个经 encode_char() 编码。

    Args:
        tgt: str, 翻译后的文本
        fname: str, EMI 文件名
        alloc: dict, 字库分配方案

    Returns:
        bytes: 编码后的字节序列

    Raises:
        ValueError: 遇到无法映射的字符
    """
    result = bytearray()
    i = 0

    while i < len(tgt):
        ch = tgt[i]

        # ---- 控制码 {xxx} ----
        if ch == '{':
            j = tgt.find('}', i)
            if j > 0:
                code_str = tgt[i + 1:j]
                matched = False

                # 带空格的控制码 (如 "引2 5A40")
                if ' ' in code_str:
                    parts = code_str.split(' ', 1)
                    name = parts[0]
                    param = parts[1] if len(parts) > 1 else ''
                    if name in CTRL_CODES:
                        result.append(CTRL_CODES[name])
                        for k in range(0, len(param), 2):
                            hex_str = param[k:k + 2]
                            try:
                                result.append(int(hex_str, 16))
                            except ValueError:
                                result.append(ord(param[k]) if k < len(param) else 0)
                        matched = True

                if not matched:
                    # 纯名称控制码
                    if code_str in CTRL_CODES:
                        result.append(CTRL_CODES[code_str])
                        matched = True

                    # 前缀名+数字
                    if not matched:
                        for name in sorted(CTRL_CODES.keys(), key=len, reverse=True):
                            if code_str.startswith(name):
                                param_str = code_str[len(name):]
                                result.append(CTRL_CODES[name])
                                if param_str:
                                    for k in range(0, len(param_str), 2):
                                        hex_str = param_str[k:k + 2]
                                        try:
                                            result.append(int(hex_str, 16))
                                        except ValueError:
                                            result.append(ord(param_str[k]) if k < len(param_str) else 0)
                                matched = True
                                break

                if not matched:
                    # 未知控制码 → 逐字编码 (普通文本)
                    for k2 in range(i, j + 1):
                        result.extend(encode_char(tgt[k2], fname, alloc, k2))

                i = j + 1
                continue

        # ---- 换行 ----
        if ch == '\n':
            result.append(0x01)
            i += 1
            continue

        # ---- 分隔线 --- ----
        if tgt[i:i + 3] == '---':
            result.append(0x02)
            i += 3
            continue

        # ---- 结束标记 ----
        if ch == '\x00':
            result.append(0x00)
            i += 1
            continue

        # ---- 普通字符 ----
        result.extend(encode_char(ch, fname, alloc, i))
        i += 1

    return bytes(result)


# ============================================================
# 文本段构建 (建议 14/15: ID 精确匹配)
# ============================================================

def build_text_segment(orig_seg_data, vals, encoded_list):
    """用编码文本构建新的文本段。

    遍历逻辑与导出脚本严格对称:
      - 空槽 (e <= s) → b'\x00', 不消耗编码列表
      - 空字符串 (trim 后为空) → b'\x00', 不消耗
      - 非空字符串 → 按序消耗 encoded_list 的下一项 (导出顺序 = 工作簿顺序)

    匹配方式说明 (建议14/15 的落地):
      工作簿的 id 是全局编号 (非段内序号), 且导出时跳过空槽/空串,
      因此可靠的匹配是"非空字符串顺序 ↔ 编码列表顺序";
      列表耗尽或剩余时立即报错, 禁止静默错位。

    Args:
        orig_seg_data: bytes, 原始段数据
        vals: tuple, 原始指针表
        encoded_list: list[str], 按 (file, seg) 分组且保持工作簿顺序的 encoded_hex 列表

    Returns:
        bytes: 新的段数据 (指针表 + 文本数据)

    Raises:
        ValueError: 编码列表耗尽 (非空字符串多于翻译条目)
    """
    n = len(vals)
    ptsize = n * 2
    new_strings = []
    enc_idx = 0

    for k in range(n):
        s = vals[k]
        e = vals[k + 1] if k + 1 < n else len(orig_seg_data)
        if e <= s:
            new_strings.append(b'\x00')
            continue

        raw = orig_seg_data[s:e]
        trimmed = trim(raw)

        if not trimmed:
            new_strings.append(b'\x00')
            continue

        # 非空字符串: 顺序消耗编码列表, 耗尽即报错 (禁止静默)
        if enc_idx >= len(encoded_list):
            raise ValueError(
                "Missing translation: text entry %d (segment-local) is non-empty "
                "but encoded list exhausted at %d" % (k, enc_idx)
            )

        enc_hex = encoded_list[enc_idx]
        enc_idx += 1

        if not enc_hex:
            # 翻译为空 → 保持空字符串
            new_strings.append(b'\x00')
            continue

        raw_enc = bytes.fromhex(enc_hex)
        if not raw_enc or raw_enc[-1] != 0x00:
            raw_enc = raw_enc + b'\x00'
        new_strings.append(raw_enc)

    # 防御: 编码列表未耗尽 (翻译条目多于非空字符串) → 报错
    if enc_idx != len(encoded_list):
        raise ValueError(
            "Encoded list not fully consumed: %d used / %d provided "
            "(导出顺序与工作簿不一致?)" % (enc_idx, len(encoded_list))
        )

    # 重建指针表
    pointers = []
    data_offset = ptsize
    for sdata in new_strings:
        pointers.append(data_offset)
        data_offset += len(sdata)

    seg = bytearray()
    seg.extend(struct.pack('<%dH' % n, *pointers))
    for sdata in new_strings:
        seg.extend(sdata)

    return bytes(seg)


def build_encoded_map(encoded_texts):
    """把编码文本列表转为按顺序排列的 encoded_hex 列表。

    工作簿条目在 (file, seg) 分组内保持导出顺序,
    与原始段的非空字符串顺序一一对应。

    Args:
        encoded_texts: list of dict, 含 'encoded_hex' 字段

    Returns:
        list[str]: encoded_hex 列表 (顺序即匹配顺序)
    """
    return [et.get("encoded_hex", "") for et in encoded_texts]