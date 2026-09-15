# -*- coding: utf-8 -*-
"""
patch_bin.py — 龙战士4 一键导入汉化补丁工具

将翻译好的中文文本导入原始 BIN 镜像，生成汉化后的游戏镜像。

功能:
  1. 读取翻译工作簿 (JSON/CSV)
  2. 分配字库索引 (如果未提供 font_alloc.json 则自动分配)
  3. 编码中文文本为游戏字节序列
  4. 生成 12×12 4bpp 字模
  5. 写入文本段和字库段到 BIN 镜像
  6. 输出汉化后的 BIN 文件

用法:
    python patch_bin.py <original.bin> <translation_workbook.json> [output.bin]

参数:
    original.bin           — 原始日版 BIN 镜像
    translation_workbook.json — 翻译工作簿 (含 file/seg/id/src/tgt 字段)
    output.bin             — 输出汉化 BIN 路径 (默认: bof4_chinese.bin)

依赖:
    pip install pillow

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import struct
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    SEC, DOFF, DSZ, EMI_MAGIC,
    read_file_from_iso, write_file_to_iso,
    parse_dir, list_iso_files,
    parse_emi, is_text_segment, trim,
    encode_text, build_text_segment,
)
from collections import defaultdict

# ============================================================
# 步骤 1: 字库分配
# ============================================================

def allocate_fonts(workbook):
    """分析翻译文本，分配字库索引。

    全局主字库: 349 字 (索引 0-348)
    全局小字库: 205 字 (索引 0-204)
    场景字库: 每场景最多 97 字 (索引 349-445)

    Returns:
        dict: 字库分配方案 (与 font_alloc.json 格式相同)
    """
    from collections import Counter

    # 统计全局字符频率
    global_chars = Counter()
    scene_chars = defaultdict(Counter)

    for item in workbook:
        tgt = item.get("tgt", "")
        fname = item.get("file", "")
        if not tgt:
            continue
        for ch in tgt:
            if ord(ch) > 0x7E:  # 非ASCII
                global_chars[ch] += 1
                scene_chars[fname][ch] += 1

    # 分配全局主字库 (按频率排序, 取前349)
    global_main = {}
    for idx, (ch, _) in enumerate(global_chars.most_common(349)):
        global_main[ch] = idx

    # 分配全局小字库 (标点符号等)
    small_chars = set()
    for item in workbook:
        tgt = item.get("tgt", "")
        for ch in tgt:
            if ord(ch) > 0x7E and ch not in global_main:
                small_chars.add(ch)

    global_small = {}
    for idx, ch in enumerate(sorted(small_chars)[:205]):
        global_small[ch] = idx

    # 场景字库 (每场景独有的字符)
    scene = {}
    for fname, chars in scene_chars.items():
        scene_unique = {}
        scene_idx = 349
        for ch, cnt in chars.most_common():
            if ch not in global_main and ch not in global_small:
                if scene_idx <= 445:
                    scene_unique[ch] = scene_idx
                    scene_idx += 1
        if scene_unique:
            scene[fname] = scene_unique

    return {
        "global_main": global_main,
        "global_small": global_small,
        "scene": scene,
        "small_font_inherent": {},
        "scene_max": 97,
        "stats": {
            "global_main": len(global_main),
            "global_small": len(global_small),
            "scene_count": len(scene),
        },
    }


# ============================================================
# 步骤 2: 字模生成
# ============================================================

def generate_glyphs(alloc, size=12):
    """从 Windows 中文字体渲染 12×12 4bpp 字模。

    使用 PIL 从系统字体 (宋体) 渲染字符，
    转换为 4bpp 灰度值 (0/1/3/5/7/8)。

    Returns:
        dict: {char: bytes(72)} — 每个字符的 72 字节字模数据
    """
    from PIL import Image, ImageDraw, ImageFont

    # 收集所有需要生成字模的字符
    all_chars = set(alloc["global_main"].keys())
    all_chars |= set(alloc["global_small"].keys())
    for fname, chars in alloc["scene"].items():
        all_chars.update(chars.keys())

    # 加载字体
    font = None
    for fp in ["C:\\Windows\\Fonts\\simsun.ttc", "C:\\Windows\\Fonts\\msyh.ttc"]:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, size)
                break
            except:
                continue
    if font is None:
        font = ImageFont.load_default()

    glyphs = {}
    for ch in all_chars:
        img = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(img)
        try:
            bbox = font.getbbox(ch)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            x = (size - w) // 2 - bbox[0]
            y = (size - h) // 2 - bbox[1]
        except:
            x, y = 0, 0
        draw.text((x, y), ch, fill=255, font=font)

        # 转换为 4bpp
        data = bytearray()
        for row in range(size):
            for col in range(0, size, 2):
                v1 = img.getpixel((col, row))
                v2 = img.getpixel((col + 1, row)) if col + 1 < size else 0
                # 灰度 → 4bpp
                def to_4bpp(v):
                    if v == 0: return 0
                    elif v >= 240: return 8
                    elif v >= 200: return 7
                    elif v >= 150: return 5
                    elif v >= 100: return 3
                    else: return 1
                data.append((to_4bpp(v1) << 4) | to_4bpp(v2))
        glyphs[ch] = bytes(data)

    return glyphs


def build_main_font(alloc, glyphs):
    """构建主字库二进制数据 (349 字模 × 72 字节 = 25128 字节)"""
    data = bytearray()
    for i in range(349):
        ch = None
        for c, idx in alloc["global_main"].items():
            if int(idx) == i:
                ch = c
                break
        data.extend(glyphs.get(ch, b'\x00' * 72))
    return bytes(data)


# ============================================================
# 步骤 3: 文本编码
# ============================================================

def encode_all_texts(workbook, alloc):
    """编码全部翻译文本。

    Returns:
        list of dict: {file, id, seg, encoded_hex}
    """
    encoded_texts = []
    for item in workbook:
        tgt = item.get("tgt", "")
        fname = item.get("file", "")
        if not tgt:
            encoded_texts.append({
                "file": fname,
                "id": item.get("id", ""),
                "seg": item.get("seg", 0),
                "encoded_hex": "",
            })
            continue
        encoded = encode_text(tgt, fname, alloc)
        encoded_texts.append({
            "file": fname,
            "id": item.get("id", ""),
            "seg": item.get("seg", 0),
            "encoded_hex": encoded.hex(),
        })
    return encoded_texts


# ============================================================
# 步骤 4: 写入 BIN 镜像
# ============================================================

def patch_bin(original_bin_path, workbook_path, output_path, alloc_path=None):
    """一键导入: 读取翻译 → 编码 → 生成字模 → 写入 BIN。

    Args:
        original_bin_path: str, 原始 BIN 镜像
        workbook_path: str, 翻译工作簿 JSON 路径
        output_path: str, 输出汉化 BIN 路径
        alloc_path: str, 可选的字库分配方案 JSON (如不提供则自动分配)
    """
    print("=" * 60)
    print("龙战士4 汉化补丁工具")
    print("=" * 60)

    # 1. 读取原始 BIN
    print("\n[1/6] 读取原始 BIN...")
    with open(original_bin_path, 'rb') as f:
        iso_data = bytearray(f.read())
    orig_sha = hashlib.sha256(bytes(iso_data)).hexdigest()
    print("  大小: %d bytes, SHA256: %s" % (len(iso_data), orig_sha[:16] + "..."))

    # 2. 读取翻译工作簿
    print("\n[2/6] 读取翻译工作簿...")
    workbook = json.load(open(workbook_path, "r", encoding="utf-8"))
    print("  条目: %d" % len(workbook))

    # 3. 字库分配
    print("\n[3/6] 字库分配...")
    if alloc_path and os.path.exists(alloc_path):
        alloc = json.load(open(alloc_path, "r", encoding="utf-8"))
        print("  使用已有分配方案: %s" % alloc_path)
    else:
        alloc = allocate_fonts(workbook)
        print("  自动分配: 主字库 %d, 小字库 %d, 场景 %d" % (
            alloc["stats"]["global_main"],
            alloc["stats"]["global_small"],
            alloc["stats"]["scene_count"],
        ))

    # 4. 生成字模
    print("\n[4/6] 生成字模...")
    glyphs = generate_glyphs(alloc)
    main_font_data = build_main_font(alloc, glyphs)
    print("  字模数: %d, 主字库: %d bytes" % (len(glyphs), len(main_font_data)))

    # 5. 编码文本
    print("\n[5/6] 编码文本...")
    encoded_texts = encode_all_texts(workbook, alloc)
    enc_by_fileseg = defaultdict(list)
    for et in encoded_texts:
        enc_by_fileseg[(et["file"], et["seg"])].append(et)
    n_nonempty = sum(1 for et in encoded_texts if et["encoded_hex"])
    print("  编码: %d 条 (非空 %d)" % (len(encoded_texts), n_nonempty))

    # 6. 写入 BIN
    print("\n[6/6] 写入 BIN 镜像...")
    files = list_iso_files(bytes(iso_data))
    modified = bytearray(iso_data)
    patched = 0
    skipped = 0

    for name, lba, size in files:
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        emi_buf = bytearray(read_file_from_iso(bytes(iso_data), lba, size))
        parsed = parse_emi(bytes(emi_buf))
        if parsed is None:
            continue

        modified_emi = False
        for seg in parsed["segments"]:
            vals = is_text_segment(seg["data"])
            if vals is None:
                continue

            blk_seg = seg["index"] + 1
            key = (name, blk_seg)
            if key not in enc_by_fileseg:
                continue

            encoded_list = enc_by_fileseg[key]
            new_seg_data = build_text_segment(seg["data"], vals, encoded_list)

            new_size = len(new_seg_data)
            new_padded = new_size + (-new_size % DSZ)
            old_padded = seg["padded_size"]

            if new_padded <= old_padded:
                seg_offset = seg["offset"]
                emi_buf[seg_offset:seg_offset + new_size] = new_seg_data
                for i in range(new_size, old_padded):
                    emi_buf[seg_offset + i] = 0
                if new_size > seg["size"]:
                    struct.pack_into('<I', emi_buf, seg["table_offset"], new_size)
                patched += 1
                modified_emi = True
            else:
                skipped += 1
                print("  跳过 %s seg%d: %d > %d" % (name, blk_seg, new_padded, old_padded))

        if modified_emi:
            write_file_to_iso(modified, lba, bytes(emi_buf), size)

    # 写入 INIT.EMI 字库
    print("\n写入字库到 INIT.EMI...")
    init_files = [(n, l, s) for n, l, s in files if n == "SYSTEM/INIT.EMI"]
    if init_files:
        init_name, init_lba, init_size = init_files[0]
        init_buf = bytearray(read_file_from_iso(bytes(iso_data), init_lba, init_size))
        init_parsed = parse_emi(bytes(init_buf))
        if init_parsed:
            for seg in init_parsed["segments"]:
                if seg["index"] == 7:  # 字库段 sig=0x1C000200
                    font_len = len(main_font_data)
                    if font_len <= seg["size"]:
                        init_buf[seg["offset"]:seg["offset"] + font_len] = main_font_data
                        for i in range(font_len, seg["size"]):
                            init_buf[seg["offset"] + i] = 0
                        write_file_to_iso(modified, init_lba, bytes(init_buf), init_size)
                        print("  Seg7: 写入 %d bytes (%d 字模)" % (font_len, font_len // 72))
                    break

    # 保存
    print("\n保存汉化 BIN...")
    with open(output_path, 'wb') as f:
        f.write(bytes(modified))

    new_sha = hashlib.sha256(bytes(modified)).hexdigest()
    print("\n" + "=" * 60)
    print("汉化完成!")
    print("  输出: %s" % output_path)
    print("  大小: %d bytes" % len(modified))
    print("  SHA256: %s" % new_sha)
    print("  修改文本段: %d" % patched)
    print("  跳过文本段: %d (空间不足)" % skipped)
    print("=" * 60)

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python patch_bin.py <original.bin> <translation_workbook.json> [output.bin] [font_alloc.json]")
        print("")
        print("参数:")
        print("  original.bin              原始日版 BIN 镜像")
        print("  translation_workbook.json  翻译工作簿")
        print("  output.bin                输出路径 (默认: bof4_chinese.bin)")
        print("  font_alloc.json           可选: 字库分配方案")
        sys.exit(1)

    bin_path = sys.argv[1]
    wb_path = sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else "bof4_chinese.bin"
    alloc_path = sys.argv[4] if len(sys.argv) > 4 else None

    patch_bin(bin_path, wb_path, out_path, alloc_path)
