# -*- coding: utf-8 -*-
"""
bof4lib.py — 龙战士4 (Breath of Fire IV) 汉化工具共享库

提供 ISO 9660 BIN/CUE 镜像读写、EMI 文件解析、
文本段检测、字体格式处理等通用功能。

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

# 控制码名称 → 字节前缀
CTRL_CODES = {
    "框": 0x0c, "队员": 0x04, "道具": 0x09, "占位": 0x07,
    "打字": 0x10, "延时": 0x16, "立绘": 0x17, "色": 0x05,
    "引2": 0x19, "引": 0x18, "金钱": 0x1c, "选择": 0x14,
    "符号2": 0x15,
}

# 控制码长度表 (字节码 → 参数字节数, 不含字节码本身)
CTRL_LEN = {
    0x04: 2, 0x05: 1, 0x06: 1, 0x07: 2, 0x09: 3,
    0x0c: 2, 0x0d: 1, 0x0e: 1, 0x0f: 1, 0x10: 2,
    0x14: 4, 0x16: 2, 0x17: 3, 0x18: 3, 0x19: 3,
    0x1b: 2, 0x1c: 2,
}

# 控制码可读名称
CTRL_NAME = {
    0x04: "{队员%02X}", 0x05: "{色%02X}", 0x06: "{/色}",
    0x07: "{占位%02X}", 0x09: "{道具%02X%02X}", 0x0c: "{框%02X}",
    0x0d: "{特效}", 0x0f: "{/特效}", 0x10: "{打字%02X}",
    0x14: "{选择%02X}", 0x16: "{延时%02X}", 0x17: "{立绘%02X%02X}",
    0x18: "{引%02X%02X}", 0x19: "{引2 %02X%02X}",
    0x1b: "{等待%02X}", 0x1c: "{金钱%02X}",
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
    """从原始字节流中提取有效文本 (跳过转义参数)。

    0x12/0x13/0x15 后跟一个参数字节，不能误判为终止符。
    0x00 为真正的字符串终止符。

    Args:
        raw: bytes, 原始文本数据 (从指针表指向的位置到段末尾)

    Returns:
        bytes: 终止符前的有效数据
    """
    i = 0
    while i < len(raw):
        b = raw[i]
        if b in (0x12, 0x13, 0x15):
            i += 2
            continue
        if b == 0x00:
            return raw[:i]
        i += 1
    return raw


# ============================================================
# 文本编码/解码
# ============================================================

def encode_text(tgt, fname, alloc):
    """将中文翻译文本编码为游戏字节序列。

    编码规则:
      - 全局主字库索引 0-255: 0x12 XX
      - 全局主字库索引 256-348: 0x13 XX (XX=索引-256)
      - 场景字索引 349+: 0x13 XX
      - 全局小字库扩展: 0x15 XX
      - 小字库固有位置: 直接字节 (0x20-0x7E)
      - 控制码 {xxx}: 转换为原始字节序列
      - \\n: 0x01, ---: 0x02

    Args:
        tgt: str, 翻译后的文本
        fname: str, EMI 文件名 (用于查找场景字库)
        alloc: dict, 字库分配方案 (font_alloc.json)

    Returns:
        bytes: 编码后的字节序列
    """
    gm = alloc["global_main"]
    gs = alloc["global_small"]
    si = alloc.get("small_font_inherent", {})
    sa = alloc["scene"]
    scene_map = sa.get(fname, {})

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

                if ' ' in code_str:
                    parts = code_str.split(' ', 1)
                    name = parts[0]
                    param = parts[1] if len(parts) > 1 else ''
                    if name in CTRL_CODES:
                        result.append(CTRL_CODES[name])
                        for c in param:
                            if c in '0123456789ABCDEFabcdef':
                                result.append(int(c, 16))
                            else:
                                result.append(ord(c))
                        matched = True

                if not matched:
                    if code_str in CTRL_CODES:
                        result.append(CTRL_CODES[code_str])
                        matched = True

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
                                        except:
                                            result.append(ord(param_str[k]) if k < len(param_str) else 0)
                                matched = True
                                break

                if not matched:
                    for c in tgt[i:j + 1]:
                        result.append(ord(c) if ord(c) < 256 else 0x3F)

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

        # ---- 字库映射 ----
        encoded = False

        # 场景字库
        if ch in scene_map:
            idx = scene_map[ch]
            if 349 <= idx <= 445:
                result.append(0x13)
                result.append(idx - 256)
                encoded = True

        # 全局主字库
        if not encoded and ch in gm:
            idx = gm[ch]
            if idx < 256:
                result.append(0x12)
                result.append(idx)
            else:
                result.append(0x13)
                result.append(idx - 256)
            encoded = True

        # 全局小字库扩展
        if not encoded and ch in gs:
            idx = gs[ch]
            result.append(0x15)
            result.append(idx + 1)
            encoded = True

        # 小字库固有位置
        if not encoded and ch in si:
            idx = si[ch]
            if 0x20 <= idx + 0x20 <= 0x7E:
                result.append(idx + 0x20)
            else:
                result.append(0x15)
                result.append(idx)
            encoded = True

        # ASCII
        if not encoded:
            cp = ord(ch)
            if 0x20 <= cp <= 0x7E:
                result.append(cp)
                encoded = True

        if not encoded:
            result.append(0x12)
            result.append(0)

        i += 1

    return bytes(result)


def build_text_segment(orig_seg_data, vals, encoded_texts):
    """用编码文本构建新的文本段。

    使用与提取脚本相同的 trim() 逻辑精确映射
    编码文本到原始字符串位置。空字符串保持为空。

    Args:
        orig_seg_data: bytes, 原始段数据
        vals: tuple, 原始指针表
        encoded_texts: list of dict, 该段的编码文本列表

    Returns:
        bytes: 新的段数据 (指针表 + 文本数据)
    """
    n = len(vals)
    ptsize = n * 2
    enc_idx = 0
    new_strings = []

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

        if enc_idx < len(encoded_texts):
            enc_hex = encoded_texts[enc_idx]["encoded_hex"]
            enc_idx += 1
            if enc_hex:
                raw_enc = bytes.fromhex(enc_hex)
                if not raw_enc or raw_enc[-1] != 0x00:
                    raw_enc = raw_enc + b'\x00'
                new_strings.append(raw_enc)
            else:
                new_strings.append(b'\x00')
        else:
            new_strings.append(b'\x00')

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
