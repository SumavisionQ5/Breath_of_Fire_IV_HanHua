# -*- coding: utf-8 -*-
"""
move_file_in_iso.py — ISO9660 文件搬移工具 (建议18 配套)

功能:
    把一个 ISO 9660 文件从原 LBA 搬到新 LBA (例如搬到镜像尾部空闲区),
    并同步更新目录记录中的 LBA/大小 (LE+BE), 使 ISO 结构保持有效。

    用途: 为 EMI 扩容 (字库段扩容 / 文本段扩容) 腾出连续空间。

用法:
    python tools/move_file_in_iso.py <original.bin> <path> <new_lba> --out output.bin

    new_lba 可使用 0 表示"自动放到镜像尾部空闲区"。

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import struct
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import SEC, DOFF, DSZ, parse_dir, list_iso_files


def find_file_record(iso_data, target_name):
    """找到目标文件的目录记录位置与数据位置。

    Returns:
        (rec_lba, rec_off, file_lba, file_size)
        rec_lba/rec_off: 目录记录在 ISO 中的绝对字节偏移 (数据区)
        file_lba: 文件数据 LBA
        file_size: 文件大小
    """
    # 目录树: root(22) -> BIN 目录
    root = parse_dir(iso_data, 22, DSZ)
    binf = [x for x in root if x[0] == 'BIN'][0]
    sub = parse_dir(iso_data, binf[1], binf[2])

    # 在 BIN 目录的数据区里精确定位记录项
    target_name = target_name_of(target)
    for nm, lba, sz, isd in sub:
        if nm == target_name:
            rec_abs = find_record_abs(iso_data, lba, sz, nm)
            if rec_abs:
                return rec_abs + (lba, sz)
    raise ValueError("未找到目录记录: %s" % target_name)


def target_name_of(path):
    return os.path.basename(path).upper()


def find_record_abs(iso_data, dir_lba, dir_size, wanted):
    """在目录数据区中搜索指定文件名, 返回记录绝对偏移 (在 BIN 数据字节流中)。"""
    off = 0
    while off < dir_size:
        si = off // DSZ
        so = off % DSZ
        base = (dir_lba + si) * SEC + DOFF + so
        b = iso_data[base:base + 256]
        if not b:
            return None
        rl = b[0]
        if rl == 0:
            off = (si + 1) * DSZ
            continue
        if len(b) < rl:
            return None
        nl = b[32]
        name = b[33:33 + nl]
        if name not in (b'\x00', b'\x01') and name.decode('ascii', 'replace').split(';')[0] == wanted:
            return base
        off += rl
    return None


def update_record(iso_data, rec_abs, new_lba, new_size):
    """更新目录记录中的 LBA 与 size (LE + BE)。"""
    for endian in ('<', '>'):
        struct.pack_into(endian + 'I', iso_data, rec_abs + 2, new_lba)
        struct.pack_into(endian + 'I', iso_data, rec_abs + 10, new_size)


def main():
    parser = argparse.ArgumentParser(description="ISO9660 文件搬移工具")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("file_path", help="要搬移的文件路径 (如 SYSTEM/INIT.EMI)")
    parser.add_argument("output_bin", help="输出 BIN")
    parser.add_argument("--new-lba", type=int, default=None,
                        help="目标 LBA (默认: 自动放到镜像尾部空闲区, 2048 对齐)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印计划不写盘")
    args = parser.parse_args()

    with open(args.original_bin, 'rb') as f:
        iso_data = bytearray(f.read())

    files = list_iso_files(bytes(iso_data))
    target = None
    for name, lba, size in files:
        if name == args.file_path:
            target = (name, lba, size)
            break
    if target is None:
        sys.exit("错误: 未找到文件 %s" % args.file_path)
    name, lba, size = target
    sectors = (size + DSZ - 1) // DSZ
    print("目标: %s LBA=%d size=%d (%d 扇区)" % (name, lba, size, sectors))

    # 计算新 LBA
    if args.new_lba is not None:
        new_lba = args.new_lba
    else:
        max_end = max((f[1] + (f[2] + DSZ - 1) // DSZ) for f in list_iso_files(bytes(iso_data)))
        new_lba = (max_end + DSZ - 1) // DSZ * DSZ // SEC + 0
        # 对齐到扇区
        new_lba = ((max_end * DSZ + DSZ - 1) // DSZ) * DSZ // DSZ
    print("新 LBA: %d" % new_lba)

    # 读取文件数据
    data = bytearray()
    for i in range(sectors):
        off = (lba + i) * SEC + DOFF
        data.extend(iso_data[off:off + DSZ])
    data = data[:size]
    print("已读取 %d bytes" % len(data))

    # 找到目录记录
    root = parse_dir(bytes(iso_data), 22, DSZ)
    binf = [x for x in root if x[0] == 'BIN'][0]
    wanted = os.path.basename(args.file_path).upper()
    rec_abs = find_record_abs(bytes(iso_data), binf[1], binf[2], wanted)
    if rec_abs is None:
        sys.exit("错误: 未找到目录记录 %s" % wanted)
    print("目录记录位置: LBA=%d 内偏移=%d (abs=%d)" % (
        rec_abs // SEC, rec_abs % SEC, rec_abs))

    if args.dry_run:
        print("[dry-run] 计划: 把 %s 从 LBA %d 搬到 %d (大小 %d bytes)" % (
            name, lba, new_lba, size))
        return

    # 写入新位置 (按扇区)
    for i in range(sectors):
        off = (new_lba + i) * SEC + DOFF
        start = i * DSZ
        chunk = data[start:start + DSZ]
        if len(chunk) < DSZ:
            chunk = chunk + b'\x00' * (DSZ - len(chunk))
        iso_data[off:off + DSZ] = chunk

    # 更新目录记录
    update_record(iso_data, rec_abs, new_lba, size)

    # 保存
    with open(args.output_bin, 'wb') as f:
        f.write(bytes(iso_data))
    print("完成: %s -> %s (新 LBA %d)" % (args.output_bin, args.file_path, new_lba))

    # 校验: 重新解析 ISO 确认文件在新区
    check = list_iso_files(bytes(iso_data))
    for n2, l2, s2 in check:
        if n2 == name:
            print("校验: %s 现在 LBA=%d size=%d (%s)" % (n2, l2, s2, "OK" if l2 == new_lba else "FAIL"))


if __name__ == "__main__":
    main()