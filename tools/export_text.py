# -*- coding: utf-8 -*-
"""
export_text.py — 龙战士4 全文本导出工具

从原始 BIN 镜像中提取所有日文文本，输出为 JSON 和可读文本文件。

用法:
    python export_text.py <input.bin> [output_dir]

输出:
    text_blocks.json   — 原始文本块 (hex + 解码文本)
    all_text.txt      — 可读的解码文本

依赖:
    pip install pillow  (仅字模预览需要)

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import struct

# 添加库路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    read_file_from_iso, parse_dir, list_iso_files,
    parse_emi, is_text_segment, trim, CTRL_LEN, CTRL_NAME
)

# ============================================================
# 字库索引对照表 (从项目 data 目录加载)
# ============================================================

def load_font_tables(data_dir):
    """加载主字库和小字库的索引对照表。

    Returns:
        (MA, SM) — 主字库 {idx: char}, 小字库 {idx: char}
    """
    MA = {}
    csv_path = os.path.join(data_dir, "main_font_index.csv")
    if os.path.exists(csv_path):
        raw = open(csv_path, "r", encoding="utf-8-sig", errors="replace").read().replace("\\n", "\n")
        for line in raw.split("\n")[1:]:
            p = line.split(",")
            if len(p) >= 4 and p[0].strip().isdigit():
                MA[int(p[0])] = p[3].strip() or None
        MA[100] = "方"  # 已修正: 放→方

    SM = {}
    csv_path2 = os.path.join(data_dir, "small_font_index.csv")
    if os.path.exists(csv_path2):
        raw = open(csv_path2, "r", encoding="utf-8-sig", errors="replace").read().replace("\ufeff", "").replace("\r", "")
        for line in raw.split("\n")[1:]:
            p = line.split(",")
            if len(p) >= 2 and p[0].strip().isdigit():
                SM[int(p[0])] = p[1].strip() or None
        SM[61] = "ー"
        SM[223] = "〜"

    return MA, SM


def decode_text(raw, fname, MA, SM, SCENE):
    """解码原始字节流为可读文本。

    编码规则:
      0x12 XX → 主字库索引 XX
      0x13 XX → 主字库索引 XX+256 (XX<93 全局, XX>=93 场景)
      0x15 XX → 小字库索引 XX+224
      字节B(≥0x21) → 小字库索引 B-32
      字节B(<0x21) → 控制码
    """
    out = []
    j = 0
    while j < len(raw):
        b = raw[j]
        if b == 0x12 and j + 1 < len(raw):
            c = MA.get(raw[j + 1])
            if c:
                out.append(c)
            else:
                out.append("[主%d]" % raw[j + 1])
            j += 2
        elif b == 0x13 and j + 1 < len(raw):
            idx = raw[j + 1] + 256
            if idx < 349:
                c = MA.get(idx)
                if c:
                    out.append(c)
                else:
                    out.append("[主%d]" % idx)
            else:
                c = SCENE.get((fname, idx))
                if c:
                    out.append(c)
                else:
                    out.append("[场%d]" % idx)
            j += 2
        elif b == 0x15 and j + 1 < len(raw):
            c = SM.get(raw[j + 1] + 224)
            if c:
                out.append(c)
            else:
                out.append("[小%d]" % (raw[j + 1] + 224))
            j += 2
        elif b < 33:
            n = CTRL_LEN.get(b, 1)
            if b in CTRL_NAME and n > 1:
                try:
                    out.append(CTRL_NAME[b] % tuple(raw[j + 1:j + n]))
                except:
                    pass
            elif b == 0x01:
                out.append("\n")
            elif b == 0x02:
                out.append("\n---\n")
            j += n
        else:
            c = SM.get(b - 32)
            if c:
                out.append(c)
            else:
                out.append("[小%d]" % (b - 32))
            j += 1
    return "".join(out)


def export_all(bin_path, output_dir="."):
    """导出全量文本。

    Args:
        bin_path: str, 原始 BIN 镜像路径
        output_dir: str, 输出目录
    """
    print("读取 BIN 文件: %s" % bin_path)
    with open(bin_path, 'rb') as f:
        iso_data = f.read()
    print("BIN 大小: %d bytes (%.1f MB)" % (len(iso_data), len(iso_data) / 1048576))

    # 加载字库对照表
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    MA, SM = load_font_tables(data_dir)
    print("主字库: %d 字, 小字库: %d 字" % (len(MA), len(SM)))

    # 列出所有文件
    files = list_iso_files(iso_data)
    print("ISO 文件数: %d" % len(files))

    # 遍历 EMI 文件
    blocks = []
    total = 0

    for name, lba, size in files:
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        buf = read_file_from_iso(iso_data, lba, size)
        if len(buf) < 16 or buf[8:16] != b"MATH_TBL":
            continue
        parsed = parse_emi(buf)
        if parsed is None:
            continue

        cnt = parsed["count"]
        sec_offset = 0x800
        for i in range(cnt):
            base = 0x10 * (i + 1)
            if base + 8 > len(buf):
                break
            ssz = struct.unpack_from('<I', buf, base)[0]
            seg = buf[sec_offset:sec_offset + ssz]
            sec_offset += ssz + (-ssz % DSZ)

            vals = is_text_segment(seg)
            if vals is None:
                continue

            ents = []
            for k in range(len(vals)):
                s = vals[k]
                e = vals[k + 1] if k + 1 < len(vals) else len(seg)
                if e <= s:
                    continue
                raw = seg[s:e]
                trimmed = trim(raw)
                if not trimmed:
                    continue
                txt = decode_text(trimmed, name, MA, SM, {})
                ents.append({"hex": trimmed.hex(), "txt": txt})
                total += 1

            if ents:
                blocks.append({"file": name, "seg": i + 1, "strings": ents})

    print("\n文本段: %d, 字符串: %d" % (len(blocks), total))

    # 保存
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, "text_blocks.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False)
    print("已保存: %s" % json_path)

    # 可读文本
    txt_path = os.path.join(output_dir, "all_text.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("龙战士4 (Breath of Fire IV) 全量文本导出\n")
        f.write("=" * 72 + "\n\n")
        for blk in blocks:
            f.write("\n########## %s seg%d ##########\n" % (blk["file"], blk["seg"]))
            for e in blk["strings"]:
                f.write(e["txt"] + "\n")
    print("已保存: %s" % txt_path)

    return blocks


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python export_text.py <input.bin> [output_dir]")
        sys.exit(1)
    bin_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    export_all(bin_path, output_dir)
