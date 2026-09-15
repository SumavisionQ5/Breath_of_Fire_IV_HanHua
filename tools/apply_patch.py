# -*- coding: utf-8 -*-
"""
apply_patch.py — 龙战士4 汉化补丁应用工具

将 .bdiff 补丁文件应用到原始 BIN 镜像，生成汉化后的镜像。

用法:
    python apply_patch.py <original.bin> <patch.bdiff> <output.bin>

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

import struct
import sys
import os
import hashlib


def apply_patch(original_path, patch_path, output_path):
    """应用 .bdiff 补丁到原始 BIN 镜像。

    Args:
        original_path: str, 原始 BIN 镜像路径
        patch_path: str, 补丁文件路径
        output_path: str, 输出汉化 BIN 路径
    """
    print("读取原始 BIN: %s" % original_path)
    with open(original_path, 'rb') as f:
        data = bytearray(f.read())
    print("  大小: %d bytes" % len(data))

    print("读取补丁: %s" % patch_path)
    with open(patch_path, 'rb') as f:
        patch = f.read()

    # 解析头部
    magic = patch[:4]
    if magic != b'BDIF':
        print("错误: 无效的补丁文件格式 (期望 BDIF, 得到 %s)" % magic)
        sys.exit(1)

    orig_size = struct.unpack_from('<Q', patch, 4)[0]
    diff_count = struct.unpack_from('<I', patch, 12)[0]

    print("  补丁记录: %d 条" % diff_count)
    print("  原始大小: %d" % orig_size)

    if len(data) != orig_size:
        print("警告: 原始文件大小 %d != 补丁期望 %d" % (len(data), orig_size))

    # 应用补丁
    pos = 16
    applied = 0
    for i in range(diff_count):
        if pos + 12 > len(patch):
            print("错误: 补丁数据不完整")
            break
        offset = struct.unpack_from('<Q', patch, pos)[0]
        length = struct.unpack_from('<I', patch, pos + 8)[0]
        pos += 12

        if pos + length > len(patch):
            print("错误: 补丁数据不足 (记录 %d)" % i)
            break

        if offset + length > len(data):
            print("错误: 偏移越界 (记录 %d, offset=0x%X, length=%d)" % (i, offset, length))
            break

        data[offset:offset + length] = patch[pos:pos + length]
        pos += length
        applied += 1

    print("  已应用: %d/%d 条" % (applied, diff_count))

    # 保存
    print("\n保存汉化 BIN: %s" % output_path)
    with open(output_path, 'wb') as f:
        f.write(bytes(data))

    new_sha = hashlib.sha256(bytes(data)).hexdigest()
    print("  大小: %d bytes" % len(data))
    print("  SHA256: %s" % new_sha)
    print("\n完成! 请用模拟器加载 %s 测试。" % output_path)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python apply_patch.py <original.bin> <patch.bdiff> <output.bin>")
        sys.exit(1)
    apply_patch(sys.argv[1], sys.argv[2], sys.argv[3])
