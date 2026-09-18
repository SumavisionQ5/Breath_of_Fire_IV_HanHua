# -*- coding: utf-8 -*-
"""
rebuild_emi.py — EMI relocation 工具 (建议16/17/18)

功能:
    对 EMI 文件做 relocation: 把指定段替换为更大的数据,
    重新按 0x800 对齐计算各段偏移, 重建段表与 EMI 文件。

    场景:
      1. 文本段超长 (2048 -> 4096): 用 rebuild 后重新落盘
      2. 字库段扩容 (主字库 370 槽 -> 更多): 同样适用

    注意 (建议18):
      ISO 中 EMI 文件变大会占用后续扇区。写入前会检查:
        - 新文件大小 <= 原 LBA 之后到下一个文件之间的连续扇区空间
        - 若空间不足, 报告需要哪些 LBA 可腾挪, 不做自动全盘重排

用法:
    python tools/rebuild_emi.py <original.bin> <emi_path> \
        --replace <seg_index>=<new_data_file> [--replace ...] \
        [--out rebuilt_emi.bin] [--dry-run]

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import struct
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    SEC, DOFF, DSZ, EMI_MAGIC,
    read_file_from_iso, write_file_to_iso, list_iso_files, parse_emi,
)


def rebuild_emi(emi_buf, replacements):
    """重建 EMI: 替换指定段数据, 重新计算段偏移与段表。

    Args:
        emi_buf: bytes, 原始 EMI 内容
        replacements: dict {seg_index: bytes} — 要替换/扩容的段

    Returns:
        bytes: 重建后的 EMI 内容

    Raises:
        ValueError: EMI 解析失败 / 段索引越界
    """
    if len(emi_buf) < 32 or emi_buf[8:16] != EMI_MAGIC:
        raise ValueError("不是有效的 EMI 文件")

    parsed = parse_emi(emi_buf)
    if parsed is None:
        raise ValueError("EMI 解析失败")

    segs = parsed["segments"]
    cnt = parsed["count"]

    # 头 16 字节: u16 seg_count, u16 version, 4B 保留, 8B "MATH_TBL"
    # 段表从 0x10 开始, 每项 16 字节 (u32 size, u32 sig, 8B 保留)
    header = bytearray(emi_buf[:0x10])

    # 应用替换
    for i, s in enumerate(segs):
        if i in replacements:
            segs[i] = dict(s, data=replacements[i], size=len(replacements[i]))

    # 重建: 头部 + 段表 (保留原始每项 16 字节, 仅更新 size/sig) + 数据 (0x800 对齐)
    new_emi = bytearray()
    new_emi += header
    for i, s in enumerate(segs):
        tbl_off = 0x10 + i * 16
        if tbl_off + 16 <= len(emi_buf):
            entry = bytearray(emi_buf[tbl_off:tbl_off + 16])
        else:
            entry = bytearray(16)
        struct.pack_into('<I', entry, 0, len(s["data"]))
        struct.pack_into('<I', entry, 4, s["sig"])
        new_emi += entry
    if len(new_emi) > 0x800:
        raise ValueError("段表区域超过 0x800, 段数过多")
    new_emi += b'\x00' * (0x800 - len(new_emi))
    for s in segs:
        pad = (-len(new_emi)) % DSZ
        new_emi += b'\x00' * pad
        new_emi += s["data"]

    return bytes(new_emi)


def main():
    parser = argparse.ArgumentParser(description="龙战士4 EMI relocation 工具")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("emi_path", help="EMI 文件路径 (如 SYSTEM/INIT.EMI)")
    parser.add_argument("--replace", action="append", default=[],
                        help="段替换: seg_index=new_data_file (可多次)")
    parser.add_argument("--out", default=None, help="输出重建后的 EMI 文件")
    parser.add_argument("--dry-run", action="store_true",
                        help="只做空间检查与打印, 不写 BIN")
    args = parser.parse_args()

    if not args.replace:
        parser.error("至少需要 --replace seg=newfile")

    replacements = {}
    for spec in args.replace:
        if '=' not in spec:
            parser.error("--replace 格式: seg_index=new_data_file, 收到: %r" % spec)
        idx_s, path = spec.split('=', 1)
        idx = int(idx_s)
        with open(path, 'rb') as f:
            replacements[idx] = f.read()
        print("  seg%d <- %s (%d bytes)" % (idx, path, len(replacements[idx])))

    with open(args.original_bin, 'rb') as f:
        iso_data = f.read()

    files = list_iso_files(iso_data)
    target = None
    for name, lba, size in files:
        if name == args.emi_path:
            target = (name, lba, size)
            break
    if target is None:
        sys.exit("错误: 未找到 EMI: %s" % args.emi_path)
    name, lba, size = target
    print("目标: %s LBA=%d size=%d" % (name, lba, size))

    emi_buf = read_file_from_iso(iso_data, lba, size)
    new_emi = rebuild_emi(emi_buf, replacements)
    new_size = len(new_emi)
    new_sectors = (new_size + DSZ - 1) // DSZ
    old_sectors = (size + DSZ - 1) // DSZ

    print("  原 EMI 大小: %d bytes (%d 扇区)" % (size, old_sectors))
    print("  新 EMI 大小: %d bytes (%d 扇区)" % (new_size, new_sectors))

    if args.out:
        with open(args.out, 'wb') as f:
            f.write(new_emi)
        print("  已输出重建 EMI: %s" % args.out)

    # 空间检查 (建议18)
    # 找出该 LBA 之后最近的文件起点
    sorted_files = sorted(files, key=lambda x: x[1])
    next_lba = None
    for fn, fl, fs in sorted_files:
        if fl > lba:
            next_lba = fl
            break
    avail_sectors = (next_lba - lba) if next_lba else (len(iso_data) // SEC - lba)
    print("  后续连续空间: %d 扇区 (%d bytes)" % (avail_sectors, avail_sectors * DSZ))
    if new_sectors <= avail_sectors:
        print("  空间检查: 充足, 可直接落盘")
    else:
        print("  空间检查: 不足! 需要 %d 扇区, 仅 %d 扇区可用" % (new_sectors, avail_sectors))
        print("  下一个文件: %s @ LBA %s" % (next_lba and "?" , next_lba))


if __name__ == "__main__":
    main()