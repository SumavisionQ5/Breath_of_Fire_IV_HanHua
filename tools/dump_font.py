# -*- coding: utf-8 -*-
"""
dump_font.py — 龙战士4 原版字库提取工具 (建议2: 原版字库 Round-trip 第一步)

功能:
    1. 读取原始日版 BIN 中的 SYSTEM/INIT.EMI
    2. 按 sig == 0x1C000200 定位字库段 (建议9: 不用 seg index)
    3. 按已验证的像素布局提取 glyph (64B/行, 每行 10 个 glyph, 高 nibble 前)
    4. 每个 glyph 渲染为 PNG (灰度图, nibble 值 0-8 → 0-255)
    5. 保存原始段副本 seg_original.bin (作为 round-trip 还原模板)

输出:
    font_dump/
    ├── 000.png ... NNN.png   (每个 glyph 的灰度图, 尺寸 12x12 * scale)
    ├── seg_original.bin      (原始字库段完整副本)
    ├── meta.json             (段信息 + nibble 值统计 + 布局参数)
    └── sheet.png             (全部 glyph 拼成的总览图)

用法:
    python tools/dump_font.py <original.bin> [--out font_dump] [--scale 4]

依赖:
    pip install pillow

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import argparse
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    GLYPH_SIZE, FONT_SEG_SIG,
    FONT_ROW_BYTES, FONT_GLYPHS_PER_ROW, FONT_BAND_ROWS, FONT_BAND_BYTES,
    FONT_GLYPH_ROW_BYTES,
    glyph_offset, get_glyph,
    read_file_from_iso, list_iso_files,
    parse_emi, find_font_segments,
)

# nibble 值 (0-8) → PNG 灰度 (0-255) 的线性映射, 保证无损还原
def nibble_to_gray(v):
    return round(v * 255 / 8) if v <= 8 else 255


def glyph_to_pixels(glyph, glyph_w=12, glyph_h=12):
    """把 72 字节 glyph (行优先) 解码为 12x12 nibble 矩阵。

    布局: 每行 6 字节 = 12 个 nibble, 高 nibble 在前 (已通过字形渲染验证)。
    """
    rows = []
    for r in range(glyph_h):
        row_bytes = glyph[r * 6:(r + 1) * 6]
        row = []
        for b in row_bytes:
            row.append((b >> 4) & 0xF)   # 高 nibble → 左侧像素
            row.append(b & 0xF)          # 低 nibble → 右侧像素
        rows.append(row[:glyph_w])
    return rows


def main():
    parser = argparse.ArgumentParser(description="龙战士4 原版字库提取工具")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("--out", default="font_dump",
                        help="输出目录 (默认: font_dump)")
    parser.add_argument("--scale", type=int, default=4,
                        help="PNG 放大倍数 (默认 4, 便于人工查看)")
    args = parser.parse_args()

    if args.scale < 1:
        parser.error("--scale 必须 >= 1")

    # 读取 ISO
    print("读取 BIN: %s" % args.original_bin)
    with open(args.original_bin, 'rb') as f:
        iso_data = f.read()
    print("  大小: %d bytes" % len(iso_data))

    # 定位 INIT.EMI
    files = list_iso_files(iso_data)
    init_files = [x for x in files if x[0] == "SYSTEM/INIT.EMI"]
    if not init_files:
        sys.exit("错误: 未找到 SYSTEM/INIT.EMI")
    name, lba, size = init_files[0]
    print("   找到 %s: LBA=%d, size=%d" % (name, lba, size))

    emi_buf = read_file_from_iso(iso_data, lba, size)
    parsed = parse_emi(emi_buf)
    if parsed is None:
        sys.exit("错误: INIT.EMI 解析失败")

    font_segs = find_font_segments(parsed)
    if not font_segs:
        sys.exit("错误: 未找到 sig=0x%08X 的字库段" % FONT_SEG_SIG)

    seg = font_segs[0]
    seg_data = seg["data"]
    print("   字库段: seg%d, sig=0x%08X, size=%d (0x%X)" % (
        seg["index"], seg["sig"], len(seg_data), len(seg_data)
    ))

    # 按正确布局计算完整 glyph 数
    n_full = 0
    while True:
        base = glyph_offset(n_full)
        if base + FONT_GLYPH_ROW_BYTES + (FONT_BAND_ROWS - 1) * FONT_ROW_BYTES > len(seg_data):
            break
        n_full += 1
    print("   完整 glyph (布局 FONT_ROW_BYTES=%d, %d/行, %d 行/带): %d" % (
        FONT_ROW_BYTES, FONT_GLYPHS_PER_ROW, FONT_BAND_ROWS, n_full
    ))

    # 统计 nibble 值分布
    nibble_stat = Counter()
    for i in range(n_full):
        for b in get_glyph(seg_data, i):
            nibble_stat[b >> 4] += 1
            nibble_stat[b & 0xF] += 1

    # 输出目录
    os.makedirs(args.out, exist_ok=True)

    from PIL import Image

    glyph_w, glyph_h = 12, 12
    px = args.scale

    # 逐个 glyph 生成 PNG
    value_stats = {"min": 16, "max": -1}
    zero_count = 0
    for i in range(n_full):
        glyph = get_glyph(seg_data, i)
        rows = glyph_to_pixels(glyph, glyph_w, glyph_h)

        img = Image.new("L", (glyph_w * px, glyph_h * px), 0)
        pix = img.load()
        for r in range(glyph_h):
            for c in range(glyph_w):
                v = rows[r][c]
                if v < value_stats["min"]:
                    value_stats["min"] = v
                if v > value_stats["max"]:
                    value_stats["max"] = v
                g = nibble_to_gray(v)
                for dy in range(px):
                    for dx in range(px):
                        pix[c * px + dx, r * px + dy] = g
        if all(v == 0 for row in rows for v in row):
            zero_count += 1
        img.save(os.path.join(args.out, "%03d.png" % i))

    # 保存原始段副本 (round-trip 模板)
    seg_path = os.path.join(args.out, "seg_original.bin")
    with open(seg_path, "wb") as f:
        f.write(seg_data)

    # 总览 sheet (每行 10 个 glyph, 与真实布局行一致)
    cols = 10
    rows_total = (n_full + cols - 1) // cols
    sheet = Image.new("L", (glyph_w * px * cols, glyph_h * px * rows_total), 255)
    spix = sheet.load()
    for i in range(n_full):
        glyph = get_glyph(seg_data, i)
        rows_p = glyph_to_pixels(glyph, glyph_w, glyph_h)
        rr = i // cols
        cc = i % cols
        for r in range(glyph_h):
            for c in range(glyph_w):
                g = nibble_to_gray(rows_p[r][c])
                for dy in range(px):
                    for dx in range(px):
                        spix[(cc * glyph_w + c) * px + dx,
                             (rr * glyph_h + r) * px + dy] = g
    sheet_path = os.path.join(args.out, "sheet.png")
    sheet.save(sheet_path)

    # meta.json
    meta = {
        "source_bin": os.path.basename(args.original_bin),
        "emi": name,
        "lba": lba,
        "file_size": size,
        "seg_index": seg["index"],
        "seg_sig": "0x%08X" % seg["sig"],
        "seg_size": len(seg_data),
        "glyph_count": n_full,
        "glyph_size": GLYPH_SIZE,
        "glyph_w": glyph_w,
        "glyph_h": glyph_h,
        "layout": {
            "row_bytes": FONT_ROW_BYTES,
            "glyphs_per_row": FONT_GLYPHS_PER_ROW,
            "glyph_row_bytes": 6,
            "band_rows": FONT_BAND_ROWS,
            "nibble_high_first": True,
        },
        "nibble_value_min": value_stats["min"],
        "nibble_value_max": value_stats["max"],
        "nibble_stats": {str(k): v for k, v in sorted(nibble_stat.items())},
        "zero_glyphs": zero_count,
        "scale": px,
    }
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\n完成:")
    print("   glyph PNG : %d 个 -> %s" % (n_full, args.out))
    print("   seg_original.bin : %d bytes" % len(seg_data))
    print("   sheet.png : %s" % sheet_path)
    print("   nibble 值范围: %d ~ %d" % (value_stats["min"], value_stats["max"]))
    print("   全 0 glyph: %d 个" % zero_count)
    print("   nibble 分布: %s" % dict(sorted(nibble_stat.items())))


if __name__ == "__main__":
    main()