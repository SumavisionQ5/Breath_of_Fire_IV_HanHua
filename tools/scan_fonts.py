# -*- coding: utf-8 -*-
"""
scan_fonts.py — 扫描所有 EMI 字库段 (建议10)

功能:
    扫描 ISO 中所有 WORLD/ 与 SYSTEM/ 下的 EMI,
    列出每个 sig == 0x1C000200 的字库段 (index/sig/size/槽位容量/前128字节/尾128字节),
    输出 font_segments_report.json。

用法:
    python tools/scan_fonts.py <original.bin> [--out font_segments_report.json]

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    read_file_from_iso, list_iso_files, parse_emi,
    FONT_SEG_SIG, FONT_GRID_COLS, glyph_capacity, glyph_cell, get_glyph,
)


def main():
    parser = argparse.ArgumentParser(description="龙战士4 字库段扫描工具")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("--out", default="font_segments_report.json",
                        help="输出报告路径 (默认: font_segments_report.json)")
    args = parser.parse_args()

    with open(args.original_bin, 'rb') as f:
        iso_data = f.read()
    files = list_iso_files(iso_data)

    report = {}
    summary = {"total_segments": 0, "by_size": {}, "scenes_with_extra": 0}
    for name, lba, size in files:
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        emi_buf = read_file_from_iso(iso_data, lba, size)
        parsed = parse_emi(emi_buf)
        if parsed is None:
            continue
        seg_list = []
        for s in parsed["segments"]:
            if s["sig"] != FONT_SEG_SIG:
                continue
            sd = s["data"]
            cap = glyph_capacity(len(sd))
            # 统计场景专属槽 (349+) 非零数
            extra_nonzero = 0
            if cap > 349:
                for i in range(349, min(cap, 420)):
                    if any(get_glyph(sd, i)):
                        extra_nonzero += 1
            seg_list.append({
                "index": s["index"],
                "sig": "0x%08X" % s["sig"],
                "size": len(sd),
                "glyph_capacity": cap,
                "extra_slots": max(0, cap - 349),
                "extra_nonzero": extra_nonzero,
                "head128": sd[:128].hex(),
                "tail128": sd[-128:].hex(),
            })
            summary["total_segments"] += 1
            summary["by_size"][len(sd)] = summary["by_size"].get(len(sd), 0) + 1
            if extra_nonzero > 0:
                summary["scenes_with_extra"] += 1
        if seg_list:
            report[name] = seg_list

    out = {"summary": summary, "segments": report}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("扫描完成:")
    print("  字库段总数     : %d" % summary["total_segments"])
    print("  尺寸分布       : %s" % summary["by_size"])
    print("  含场景专属字的文件数: %d" % summary["scenes_with_extra"])
    print("  报告已输出     : %s" % args.out)


if __name__ == "__main__":
    main()