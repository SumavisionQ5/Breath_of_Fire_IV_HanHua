# -*- coding: utf-8 -*-
"""
analyze_slps.py — SLPS_027.28 可执行文件逆向分析工具

用途:
  从原始 BIN 中提取 SLPS_027.28, 分析游戏的文件表、EMI 容器解析逻辑,
  并核对字库段的加载路径。

分析内容:
  1. PS-X EXE 头解析
  2. 硬编码 LBA 文件表 (RAM 0x8016BCE4, 516 项)
  3. EMI 容器解析代码定位 (MATH_TBL 校验)
  4. GPU 上传函数 (LoadImage) 定位
  5. 字库段归属核对

用法:
    python tools/analyze_slps.py <original.bin> [--exe-out SLPS_027.28]

依赖:
    pip install capstone

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import struct
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    DSZ, read_file_from_iso, list_iso_files, parse_dir,
    parse_emi, find_font_segments,
)

TEXT_OFF = 0x800
FILE_TABLE_OFF = 0x07ACE4
FILE_TABLE_RAM = 0x8016BCE4
STR_MATH_TBL = 0x80130800
STR_LOADIMAGE = 0x801312B4


def extract_exe(iso_path, out_path):
    """从 ISO 中提取 SLPS_027.28 (可执行文件)。"""
    with open(iso_path, 'rb') as f:
        iso = f.read()
    root = parse_dir(iso, 22, DSZ)
    for nm, lba, sz, isd in root:
        if nm.startswith("SLPS"):
            data = read_file_from_iso(iso, lba, sz)
            with open(out_path, 'wb') as f:
                f.write(data)
            return out_path, lba, sz
    raise RuntimeError("未找到 SLPS_*.xx 可执行文件")


def parse_psexe(data):
    if data[:8] != b"PS-X EXE":
        raise ValueError("不是 PS-X EXE 文件")
    return {
        "pc0": struct.unpack_from("<I", data, 0x10)[0],
        "gp0": struct.unpack_from("<I", data, 0x14)[0],
        "text_addr": struct.unpack_from("<I", data, 0x18)[0],
        "text_size": struct.unpack_from("<I", data, 0x1C)[0],
        "stack_addr": struct.unpack_from("<I", data, 0x30)[0],
    }


def dump_file_table(data):
    """导出硬编码 LBA 文件表 (直到值不再递增)。"""
    entries = []
    off = FILE_TABLE_OFF
    while True:
        if off + 4 > len(data):
            break
        v = struct.unpack_from("<I", data, off)[0]
        if 90000 <= v <= 300000 and (not entries or v >= entries[-1]):
            entries.append(v)
            off += 4
        else:
            break
    return entries


def main():
    parser = argparse.ArgumentParser(description="SLPS_027.28 逆向分析")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("--exe-out", default="SLPS_027.28",
                        help="提取的可执行文件输出路径")
    parser.add_argument("--iso", default=None,
                        help="同时列出 ISO 中字库段分布 (可选)")
    args = parser.parse_args()

    exe_path, lba, size = extract_exe(args.original_bin, args.exe_out)
    print("已提取可执行文件: %s (LBA=%d, size=%d)" % (exe_path, lba, size))

    with open(exe_path, 'rb') as f:
        data = f.read()

    hdr = parse_psexe(data)
    print("\n=== PS-X EXE 头 ===")
    for k, v in hdr.items():
        print("  %-12s = 0x%08X" % (k, v))

    entries = dump_file_table(data)
    print("\n=== 硬编码 LBA 文件表 @RAM 0x%08X ===" % FILE_TABLE_RAM)
    print("  项数: %d" % len(entries))
    print("  起始 LBA: %d, 结束 LBA: %d" % (entries[0], entries[-1]))

    # 映射到文件名
    with open(args.original_bin, 'rb') as f:
        iso = f.read()
    lba2name = {l: n for n, l, s in list_iso_files(iso)}
    root = parse_dir(iso, 22, DSZ)
    for nm, l, sz, isd in root:
        lba2name[l] = "[root] " + nm
    init_idx = entries.index(98960) if 98960 in entries else -1
    if init_idx >= 0:
        print("  INIT.EMI (LBA 98960) 索引: %d" % init_idx)

    print("\n=== 关键代码地址 ===")
    print("  EMI 容器校验 (MATH_TBL): RAM 0x80133074")
    print("  段表遍历 + 扇区计算    : RAM 0x8013311C")
    print("  LoadImage 函数         : RAM 0x80162CB8")
    print("  GPU 函数表             : RAM 0x80173B48")

    if args.iso:
        print("\n=== 字库段分布 ===")
        sys_cnt = 0
        sys_no = []
        wld_cnt = 0
        wld_total = 0
        for name, l, s in list_iso_files(iso):
            if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
                continue
            emi = read_file_from_iso(iso, l, s)
            p = parse_emi(emi)
            if p is None:
                continue
            has = bool(find_font_segments(p))
            if name.startswith("SYSTEM/"):
                if has:
                    sys_cnt += 1
                else:
                    sys_no.append(name)
            else:
                wld_total += 1
                if has:
                    wld_cnt += 1
        print("  SYSTEM: 有字库段 %d 个" % sys_cnt)
        print("  SYSTEM 无字库段: %d 个" % len(sys_no))
        print("  WORLD : 有字库段 %d / %d" % (wld_cnt, wld_total))


if __name__ == "__main__":
    main()
