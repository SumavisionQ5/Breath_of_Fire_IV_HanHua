# -*- coding: utf-8 -*-
"""
import_font.py — 龙战士4 原版字库还原工具 (建议2: 原版字库 Round-trip 第二步)

功能:
    1. 读取 font_dump/ 目录中 dump_font.py 生成的 PNG + seg_original.bin
    2. 把每个 PNG 还原为 72 字节 glyph, 按正确布局覆盖回字库段
    3. 与原始字库段 memcmp 对比
    4. 输出一致性报告 (要求 100% 一致)

用法:
    python tools/import_font.py <original.bin> [--dump font_dump] [--out rebuilt_seg.bin]

    --out 可选: 把重建的字库段数据单独保存, 便于 diff
    不加 --out 时只做内存对比并输出报告。

依赖:
    pip install pillow

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import argparse
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    GLYPH_SIZE, FONT_SEG_SIG,
    FONT_ROW_BYTES, FONT_BAND_ROWS, FONT_BAND_BYTES,
    set_glyph,
    read_file_from_iso, list_iso_files,
    parse_emi, find_font_segments,
)


def gray_to_nibble(g):
    """PNG 灰度 → nibble 值 (与 dump_font.nibble_to_gray 严格对称)。"""
    return round(g * 8 / 255)


def pixels_to_glyph(pix, w, h, scale):
    """从放大后的 PNG 采样 12x12 网格, 还原 72 字节 glyph (行优先, 高 nibble 前)。"""
    glyph = bytearray()
    for r in range(h):
        row_vals = []
        for c in range(w):
            g = pix[c * scale, r * scale]
            row_vals.append(gray_to_nibble(g))
        for c in range(0, w, 2):
            glyph.append((row_vals[c] << 4) | row_vals[c + 1])
    return bytes(glyph)


def main():
    parser = argparse.ArgumentParser(description="龙战士4 原版字库还原工具")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("--dump", default="font_dump",
                        help="dump_font.py 输出目录 (默认: font_dump)")
    parser.add_argument("--out", default=None,
                        help="可选: 输出重建的字库段数据文件")
    args = parser.parse_args()

    # 读取 meta.json
    meta_path = os.path.join(args.dump, "meta.json")
    if not os.path.isfile(meta_path):
        sys.exit("错误: 找不到 %s, 请先运行 dump_font.py" % meta_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    n_full = meta["glyph_count"]
    scale = meta["scale"]
    glyph_w, glyph_h = meta["glyph_w"], meta["glyph_h"]
    print("meta: %d glyphs, scale=%d" % (n_full, scale))

    # 读取原始段副本 (round-trip 模板)
    seg_path = os.path.join(args.dump, "seg_original.bin")
    if not os.path.isfile(seg_path):
        sys.exit("错误: 缺少 %s" % seg_path)
    with open(seg_path, "rb") as f:
        seg_data = f.read()
    rebuilt = bytearray(seg_data)  # 基底: 原始数据 (非 glyph 字节保持不变)

    from PIL import Image

    # 逐 PNG 还原并覆盖 glyph 槽位
    for i in range(n_full):
        png_path = os.path.join(args.dump, "%03d.png" % i)
        if not os.path.isfile(png_path):
            sys.exit("错误: 缺少 %s" % png_path)
        img = Image.open(png_path).convert("L")
        pix = img.load()
        w, h = img.size
        if w != glyph_w * scale or h != glyph_h * scale:
            sys.exit("错误: %s 尺寸 %dx%d 与 meta (%dx%d) 不符" % (
                png_path, w, h, glyph_w * scale, glyph_h * scale))
        glyph = pixels_to_glyph(pix, glyph_w, glyph_h, scale)
        set_glyph(rebuilt, i, glyph)

    # 对比
    diffs = []
    for i in range(len(seg_data)):
        if rebuilt[i] != seg_data[i]:
            diffs.append(i)
            if len(diffs) > 20:
                break

    print("\n" + "=" * 60)
    print("Round-trip 对比结果")
    print("=" * 60)
    print("  原始段长度  : %d" % len(seg_data))
    print("  重建段长度  : %d" % len(rebuilt))
    print("  SHA256(orig): %s" % hashlib.sha256(seg_data).hexdigest())
    print("  SHA256(reb) : %s" % hashlib.sha256(bytes(rebuilt)).hexdigest())

    if not diffs:
        print("  memcmp      : 完全一致 (100% round-trip 通过)")
    else:
        print("  memcmp      : 失败, 前 %d 处差异: %s" % (
            len(diffs), [hex(x) for x in diffs[:20]]
        ))
        bad_glyphs = set(d // GLYPH_SIZE for d in diffs)
        print("  涉及 glyph  : %s" % sorted(bad_glyphs)[:20])
        sys.exit(1)

    if args.out:
        with open(args.out, 'wb') as f:
            f.write(bytes(rebuilt))
        print("  已输出重建段: %s" % args.out)

    print("=" * 60)


if __name__ == "__main__":
    main()