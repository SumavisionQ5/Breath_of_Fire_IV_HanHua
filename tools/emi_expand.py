# -*- coding: utf-8 -*-
"""
emi_expand.py — EMI 段扩容与 ISO 文件搬移库

提供:
    - EMI 段替换/扩容后的重建 (基于 rebuild_emi)
    - 扩容后写回 ISO: 若原 LBA 空间足够则原地写, 否则搬到镜像尾部空闲区
    - ISO9660 目录记录更新 (LBA/size, LE+BE)

这是场景字库扩容 (21~71 -> 128) 与超长文本段 relocation 的基础。

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    SEC, DOFF, DSZ,
    parse_dir, list_iso_files,
    parse_emi,
)
from rebuild_emi import rebuild_emi


def find_record_abs(iso_data, dir_lba, dir_size, wanted):
    """在目录数据区中搜索指定文件名的记录, 返回记录的绝对字节偏移。"""
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


def get_system_record(iso_data):
    """返回 SYSTEM 子目录记录位置 (BIN > SYSTEM)。"""
    return get_dir_record(iso_data, "SYSTEM")


def get_dir_record(iso_data, top_dir):
    """返回指定顶层子目录 (BIN > top_dir) 的记录。"""
    root = parse_dir(bytes(iso_data), 22, DSZ)
    binf = [x for x in root if x[0] == 'BIN'][0]
    sub = parse_dir(bytes(iso_data), binf[1], binf[2])
    for d in sub:
        if d[0] == top_dir:
            return d
    raise ValueError("未找到子目录: %s" % top_dir)


def tail_start_lba(iso_data):
    """计算镜像尾部空闲区起始 LBA (所有文件最大结束位置)。"""
    ends = []
    root = parse_dir(bytes(iso_data), 22, DSZ)
    for nm, fl, fs, isd in root:
        ends.append(fl + (fs + DSZ - 1) // DSZ)
    for f in list_iso_files(bytes(iso_data)):
        ends.append(f[1] + (f[2] + DSZ - 1) // DSZ)
    return max(ends)


def write_emi_to_iso(iso_data, name, new_emi, dry_run=False):
    """把 (可能扩容后的) EMI 写回 ISO。

    策略:
      - 新大小 <= 原扇区数: 原地写 (保持 LBA)
      - 否则: 搬到尾部空闲区, 更新目录记录

    Args:
        iso_data: bytearray, 可修改的 ISO 数据
        name: str, EMI 文件名 (如 "WORLD/AREAD000.EMI")
        new_emi: bytes, 新 EMI 内容
        dry_run: bool, 只检查不写入

    Returns:
        dict: {lba, size, moved(bool), old_lba, old_size}
    """
    # 找到文件当前 LBA/size
    target = None
    for n, lba, size in list_iso_files(bytes(iso_data)):
        if n == name:
            target = (n, lba, size)
            break
    if target is None:
        raise ValueError("ISO 中未找到文件: %s" % name)
    _, old_lba, old_size = target
    old_sectors = (old_size + DSZ - 1) // DSZ
    new_size = len(new_emi)
    new_sectors = (new_size + DSZ - 1) // DSZ

    result = {
        "old_lba": old_lba, "old_size": old_size,
        "size": new_size, "moved": False,
    }

    if dry_run:
        result["lba"] = old_lba if new_sectors <= old_sectors else tail_start_lba(iso_data)
        result["moved"] = new_sectors > old_sectors
        return result

    if new_sectors <= old_sectors:
        # 原地写 (剩余空间清零)
        new_lba = old_lba
    else:
        # 搬移到尾部
        new_lba = tail_start_lba(iso_data)
        result["moved"] = True
        # 关键: 越界切片赋值会插入到末尾而非目标位置 (Python bytearray 语义),
        # 必须先扩展镜像到目标长度, 否则多文件搬移互相错位叠加 (v15 实证 bug)
        need_end = (new_lba + new_sectors) * SEC + DOFF + DSZ
        if len(iso_data) < need_end:
            iso_data.extend(b'\x00' * (need_end - len(iso_data)))

    # 写入
    for i in range(new_sectors):
        off = (new_lba + i) * SEC + DOFF
        chunk = new_emi[i * DSZ:(i + 1) * DSZ]
        if len(chunk) < DSZ:
            chunk = chunk + b'\x00' * (DSZ - len(chunk))
        iso_data[off:off + DSZ] = chunk

    # 更新目录记录 (仅 LBA/size 变化时)
    if new_lba != old_lba or new_size != old_size:
        top_dir = name.split("/")[0]
        d = get_dir_record(bytes(iso_data), top_dir)
        wanted = os.path.basename(name).upper()
        rec = find_record_abs(bytes(iso_data), d[1], d[2], wanted)
        if rec is None:
            raise ValueError("未找到目录记录: %s (in %s)" % (wanted, top_dir))
        for endian, off in (('<', 2), ('>', 6)):
            struct.pack_into(endian + 'I', iso_data, rec + off, new_lba)
        for endian, off in (('<', 10), ('>', 14)):
            struct.pack_into(endian + 'I', iso_data, rec + off, new_size)

    result["lba"] = new_lba
    return result


def expand_emi_in_iso(iso_data, name, replacements, dry_run=False):
    """对 ISO 中的 EMI 做段替换/扩容并写回。

    Args:
        iso_data: bytearray
        name: EMI 文件名
        replacements: {seg_index: bytes}
        dry_run: 只检查

    Returns:
        dict: write_emi_to_iso 的结果
    """
    # 找到文件
    target = None
    for n, lba, size in list_iso_files(bytes(iso_data)):
        if n == name:
            target = (n, lba, size)
            break
    if target is None:
        raise ValueError("ISO 中未找到文件: %s" % name)
    _, lba, size = target

    # 读取 EMI
    buf = bytearray()
    for i in range((size + DSZ - 1) // DSZ):
        off = (lba + i) * SEC + DOFF
        buf.extend(iso_data[off:off + DSZ])
    emi_buf = bytes(buf[:size])

    new_emi = rebuild_emi(emi_buf, replacements)
    return write_emi_to_iso(iso_data, name, new_emi, dry_run=dry_run)