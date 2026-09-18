# -*- coding: utf-8 -*-
"""
make_patch.py — 龙战士4 汉化补丁生成工具

对比原始 BIN 与汉化 BIN, 生成 .bdiff 差异补丁 (BDIF 格式)。

用法:
    python tools/make_patch.py <original.bin> <patched.bin> <output.bdiff>

补丁格式 (BDIF):
    Header:  'BDIF' (4 bytes magic)
             u64    original_size
             u32    diff_count
    Records: u64    offset
             u32    length
             bytes  data[length]

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import struct
import hashlib
import argparse

BLOCK = 4096   # 差异块粒度


def make_patch(original_path, patched_path, out_path):
    with open(original_path, 'rb') as f:
        orig = f.read()
    with open(patched_path, 'rb') as f:
        patched = f.read()

    if len(orig) != len(patched):
        print("警告: 大小不同 (原始 %d, 汉化 %d)" % (len(orig), len(patched)))

    n = min(len(orig), len(patched))
    diffs = []   # (offset, data)
    i = 0
    while i < n:
        # 按块检查是否相同
        end = min(i + BLOCK, n)
        if orig[i:end] == patched[i:end]:
            i = end
            continue
        # 找到连续差异区间
        start = i
        while i < n:
            end = min(i + BLOCK, n)
            if orig[i:end] == patched[i:end]:
                break
            i = end
        diffs.append((start, patched[start:i]))

    # 写入补丁
    with open(out_path, 'wb') as f:
        f.write(b'BDIF')
        f.write(struct.pack('<Q', len(orig)))
        f.write(struct.pack('<I', len(diffs)))
        for off, data in diffs:
            f.write(struct.pack('<Q', off))
            f.write(struct.pack('<I', len(data)))
            f.write(data)

    total_bytes = sum(len(d) for _, d in diffs)
    print("补丁生成: %s" % out_path)
    print("  差异区间 : %d" % len(diffs))
    print("  差异字节 : %d (%.2f MB)" % (total_bytes, total_bytes / 1048576))
    print("  补丁大小 : %d bytes" % os.path.getsize(out_path))
    print("  原始 SHA256 : %s" % hashlib.sha256(orig).hexdigest())
    print("  汉化 SHA256 : %s" % hashlib.sha256(patched).hexdigest())

    # 同时输出 patch_data.json
    meta_path = os.path.splitext(out_path)[0] + "_data.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({
            "original_size": len(orig),
            "original_sha256": hashlib.sha256(orig).hexdigest(),
            "patched_size": len(patched),
            "patched_sha256": hashlib.sha256(patched).hexdigest(),
            "diff_count": len(diffs),
            "total_diff_bytes": total_bytes,
        }, f, ensure_ascii=False, indent=2)
    print("  元数据   : %s" % meta_path)


def main():
    parser = argparse.ArgumentParser(description="龙战士4 汉化补丁生成工具")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("patched_bin", help="汉化后 BIN 镜像")
    parser.add_argument("output_bdiff", help="输出补丁文件 (.bdiff)")
    args = parser.parse_args()
    make_patch(args.original_bin, args.patched_bin, args.output_bdiff)


if __name__ == "__main__":
    main()
