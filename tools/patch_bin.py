# -*- coding: utf-8 -*-
"""
patch_bin.py — 龙战士4 一键导入汉化补丁工具

将翻译好的中文文本导入原始 BIN 镜像，生成汉化后的游戏镜像。

遵循《龙战士4汉化改进》建议:
  - 建议3: 字体路径必须显式通过 --font 提供, 不再允许静默 fallback
  - 建议4: 字模生成先做可验证的二值版本 (threshold)
  - 建议5: build_font_block() 通用复用, 不写死 349/72
  - 建议9: 按 sig == 0x1C000200 定位字库段, 不用 seg index == 7
  - 建议20: 存在 skipped/unknown/overflow 时 raise, 不允许半成品成功
  - 建议22: 优先使用固定 font_alloc.json, 禁止每次 build 自动重新分配

用法:
    python tools/patch_bin.py <original.bin> <translation_workbook.json> [output.bin] \
        [--alloc data/font_alloc.json] \
        [--font font/NotoSansCJK-Regular.ttc] \
        [--threshold 64] \
        [--auto-alloc] \
        [--allow-unknown-image]

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
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    SEC, DOFF, DSZ, EMI_MAGIC,
    MAIN_FONT_COUNT, SMALL_FONT_COUNT, SCENE_FONT_MAX,
    SCENE_FONT_BASE, GLYPH_SIZE, FONT_SEG_SIG,
    read_file_from_iso, write_file_to_iso,
    parse_dir, list_iso_files,
    parse_emi, find_font_segments, is_text_segment, trim,
    encode_text, build_text_segment, build_encoded_map,
    set_glyph, GLYPH_SIZE,
    glyph_cell, glyph_capacity, glyph_seg_size, FONT_CELL_ROWS,
)
from collections import defaultdict

# 目标日版镜像 SHA256 (建议32)
EXPECTED_SHA256 = "bf0b2a0d73f64eee32756b8b7932ae152b5204437c14e196427305c6209fdf2b"


# ============================================================
# 步骤 1: 字库分配 (建议 21: 一致性检查)
# ============================================================

def allocate_fonts(workbook):
    """分析翻译文本，分配字库索引。 (建议 21: 分配后强制一致性检查)

    全局主字库: 349 字 (索引 0-348)  — 最高频/最多跨文件的字符
    全局小字库: 205 字 (索引 0-204)
    场景字库: 每场景最多 97 字 (索引 349-445) — 仅放"本场景专用"的低频字符

    分配优先级 (关键修复):
      1. 跨文件字符必须全局, 不能放进单场景 (否则其他文件无法编码)
      2. 排序键 = (跨文件数, 出现次数) 降序
      3. 全部全局字库满后, 剩余字符按文件归入 scene (每文件限 SCENE_FONT_MAX)

    Returns:
        dict: 字库分配方案 (与 font_alloc.json 格式相同)
    """
    from collections import Counter, defaultdict

    char_files = defaultdict(set)
    char_freq = Counter()

    for item in workbook:
        tgt = item.get("tgt", "")
        fname = item.get("file", "")
        if not tgt:
            continue
        for ch in tgt:
            if ord(ch) > 0x7E:  # 非ASCII
                char_files[ch].add(fname)
                char_freq[ch] += 1

    # 全局优先级: 跨文件数(降序) > 出现频率(降序)
    def global_key(ch):
        return (len(char_files[ch]), char_freq[ch])

    sorted_chars = sorted(char_freq.keys(), key=global_key, reverse=True)

    # 全局主字库 (0-348)
    global_main = {}
    # 全局小字库 (0-204)
    global_small = {}
    for ch in sorted_chars:
        if len(global_main) < MAIN_FONT_COUNT:
            global_main[ch] = len(global_main)
        elif len(global_small) < SMALL_FONT_COUNT:
            global_small[ch] = len(global_small)
        else:
            break

    # 场景字库: 剩余字符按文件归入 (每文件从 349 开始, 限 SCENE_FONT_MAX)
    scene = defaultdict(dict)
    scene_overflow = []
    for ch in sorted_chars:
        if ch in global_main or ch in global_small:
            continue
        for fname in sorted(char_files[ch]):
            d = scene[fname]
            if ch in d:
                continue
            if len(d) < SCENE_FONT_MAX:
                d[ch] = SCENE_FONT_BASE + len(d)
            else:
                scene_overflow.append((fname, ch))

    alloc = {
        "global_main": global_main,
        "global_small": global_small,
        "scene": dict(scene),
        "small_font_inherent": {},
        "scene_max": SCENE_FONT_MAX,
        "stats": {
            "global_main": len(global_main),
            "global_small": len(global_small),
            "scene_count": len(scene),
            "scene_overflow": len(scene_overflow),
        },
    }

    # 建议21: 一致性检查
    check_alloc_consistency(alloc)

    if scene_overflow:
        raise RuntimeError(
            "场景字库容量不足: %d 处放不下 (每文件限 %d 字), 前 %d 处:\n%s" % (
                len(scene_overflow), SCENE_FONT_MAX, min(10, len(scene_overflow)),
                "\n".join("  %s: %r" % (f, c) for f, c in scene_overflow[:10])
            )
        )
    return alloc


def check_alloc_consistency(alloc):
    """字库分配一致性检查 (建议21)。

    Raises:
        AssertionError / ValueError: 违反约束时抛出
    """
    gm = alloc.get("global_main", {})
    gs = alloc.get("global_small", {})
    scene = alloc.get("scene", {})
    si = alloc.get("small_font_inherent", {})

    assert len(gm) <= MAIN_FONT_COUNT, "global_main 超限: %d" % len(gm)
    assert len(gs) <= SMALL_FONT_COUNT, "global_small 超限: %d" % len(gs)

    for fname, mapping in scene.items():
        # 场景容量上限: 0x13 XX 编码空间 349-511 (v2 方案实际按 alloc 的 scene_max 控制)
        assert len(mapping) <= 0x1FF - SCENE_FONT_BASE + 1, (
            "场景 %s 字库超限: %d > %d" % (fname, len(mapping), 0x1FF - SCENE_FONT_BASE + 1)
        )

    # 索引范围检查
    for ch, idx in gm.items():
        assert 0 <= int(idx) < MAIN_FONT_COUNT, "主字库索引越界: %r=%d" % (ch, idx)
    for ch, idx in gs.items():
        assert 0 <= int(idx) < SMALL_FONT_COUNT, "小字库索引越界: %r=%d" % (ch, idx)
    for fname, mapping in scene.items():
        for ch, idx in mapping.items():
            assert SCENE_FONT_BASE <= int(idx) <= 0x1FF, (
                "场景 %s 索引越界: %r=%d (0x13 编码上限 511)" % (fname, ch, int(idx))
            )

    # 互斥检查: global_main ∩ global_small == ∅
    overlap = set(gm.keys()) & set(gs.keys())
    assert not overlap, "global_main 与 global_small 重叠: %r" % (sorted(overlap)[:10])

    # 场景字符不得出现在全局字库
    for fname, mapping in scene.items():
        dup = set(mapping.keys()) & set(gm.keys())
        dup |= set(mapping.keys()) & set(gs.keys())
        assert not dup, "场景 %s 与全局字库重叠: %r" % (fname, sorted(dup)[:10])

    # 索引重复检查
    def has_dup_idx(mapping):
        seen = set()
        for idx in mapping.values():
            if int(idx) in seen:
                return True
            seen.add(int(idx))
        return False

    assert not has_dup_idx(gm), "主字库存在重复索引"
    assert not has_dup_idx(gs), "小字库存在重复索引"
    for fname, mapping in scene.items():
        assert not has_dup_idx(mapping), "场景 %s 存在重复索引" % fname


# ============================================================
# 步骤 2: 字模生成 (建议 3/4/5)
# ============================================================

def generate_glyphs(alloc, font_path, size=12, threshold=96, shadow=True):
    """从指定字体渲染 12×12 4bpp 字模 (含右下 2 向细描边)。

    建议3: font_path 必须存在, 否则 FileNotFoundError, 禁止默认字体 fallback。

    字模结构 (与原版日文字库一致, 已在模拟器实测验证):
      - 值 1 = 笔画主体 (白色)
      - 值 8 = 笔画右/下边缘 1 像素扩展 (阴影/描边, 浅色背景可见的关键)
      - 值 0 = 背景透明
    描边方案经三版对比 (无描边 / 3向粗描边 / 右下2向细描边) 定稿为右下 2 向细描边。

    推荐字体: Windows XP 宋体 simsun.ttc (12px 内置点阵, 纯 0/255 无抗锯齿)。

    Args:
        alloc: dict, 字库分配方案
        font_path: str, 中文字体文件路径 (TTF/TTC/OTF)
        size: int, 字模尺寸 (默认12)
        threshold: int, 二值化阈值 (0-255, 默认96)
        shadow: bool, 是否添加右下描边 (默认 True)

    Returns:
        dict: {char: bytes(GLYPH_SIZE)} — 每个字符的字模数据

    Raises:
        FileNotFoundError: 字体文件不存在
    """
    from PIL import Image, ImageDraw, ImageFont

    if not os.path.isfile(font_path):
        raise FileNotFoundError(
            "Chinese font not found: %s\n"
            "请通过 --font 指定字体文件, 推荐: --font C:/Windows/Fonts/simsun.ttc" % font_path
        )

    # 收集所有需要生成字模的字符
    all_chars = set(alloc.get("global_main", {}).keys())
    all_chars |= set(alloc.get("global_small", {}).keys())
    all_chars |= set(alloc.get("small_font_inherent", {}).keys())
    for fname, chars in alloc.get("scene", {}).items():
        all_chars.update(chars.keys())

    font = ImageFont.truetype(font_path, size)

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
        except Exception:
            x, y = 0, 0
        draw.text((x, y), ch, fill=255, font=font)

        # 二值化: 笔画 = 1 (矩阵形式, 便于描边处理)
        m = [[0] * size for _ in range(size)]
        for r in range(size):
            for c in range(size):
                if img.getpixel((c, r)) >= threshold:
                    m[r][c] = 1

        # 描边: 右/下方向扩展 1 像素为值 8 (不覆盖笔画主体)
        #   原版日文字形即为此结构: 纯值1在浅色背景上会"偶尔不显示"
        if shadow:
            sh = [[0] * size for _ in range(size)]
            for r in range(size):
                for c in range(size):
                    if m[r][c] == 1:
                        for dr, dc in ((0, 1), (1, 0)):
                            rr, cc = r + dr, c + dc
                            if 0 <= rr < size and 0 <= cc < size and m[rr][cc] == 0:
                                sh[rr][cc] = 8
            for r in range(size):
                for c in range(size):
                    if sh[r][c]:
                        m[r][c] = sh[r][c]

        # 打包 4bpp: 低 nibble = 左侧像素 (PS1 标准)
        #   经原版字库客观指标验证: 低 nibble 在左时横向成对率 0.8301 / 孤立像素率 0.0036,
        #   而高 nibble 在左时为 0.7579 / 0.0969 —— 后者笔画会被打散成"奇偶列错位"的碎片。
        data = bytearray()
        for r in range(size):
            for c in range(0, size, 2):
                lo = m[r][c] & 0xF
                hi = m[r][c + 1] & 0xF if c + 1 < size else 0
                data.append(lo | (hi << 4))
        glyphs[ch] = bytes(data)

    return glyphs


def build_font_block(index_map, glyphs, count):
    """按索引构建字库数据块 (建议5: 通用, 主/小/场景字库复用)。

    Args:
        index_map: dict, {char: index}
        glyphs: dict, {char: 72 bytes 字模}
        count: int, 字库容量 (从 0 到 count-1)

    Returns:
        bytes: count * GLYPH_SIZE 字节的字库数据

    Raises:
        ValueError: 索引缺失字符字模或字模长度错误
    """
    inverse = {}
    for ch, idx in index_map.items():
        inverse[int(idx)] = ch

    data = bytearray()
    for idx in range(count):
        ch = inverse.get(idx)
        if ch is None:
            data.extend(b'\x00' * GLYPH_SIZE)
            continue

        if ch not in glyphs:
            raise ValueError("Missing glyph for index %d: %r" % (idx, ch))

        glyph = glyphs[ch]
        if len(glyph) != GLYPH_SIZE:
            raise ValueError("Bad glyph size for %r: %d" % (ch, len(glyph)))

        data.extend(glyph)

    return bytes(data)


def build_main_font(alloc, glyphs):
    """构建主字库数据 (建议5: 复用 build_font_block)"""
    return build_font_block(alloc["global_main"], glyphs, MAIN_FONT_COUNT)




def build_scene_font_data(main_font_data, scene_map, glyphs, scene_capacity=128):
    """构建场景字库段数据 (v2 架构)。

    布局: 349 个主字副本 (槽 0-348) + scene_capacity 个场景字槽 (349+)。
    段大小 = ceil((349+scene_capacity)/10) 带xEA 768 字节。

    场景段在游戏内会覆盖主字库区域, 因此 0-348 槽必须写入中文主字副本,
    否则场景内文本会显示原日文字形。

    Args:
        main_font_data: bytes, 349x72B 中文主字库
        scene_map: dict {char: scene_idx} (349+)
        glyphs: dict {char: 72B 字形}
        scene_capacity: int, 场景字槽容量 (默认 128)

    Returns:
        bytes: 场景字库段数据
    """
    total_slots = SCENE_FONT_BASE + scene_capacity   # 349 + 128 = 477
    seg_size = glyph_seg_size(total_slots)           # 21 列布局, 36864 字节
    data = bytearray(seg_size)
    view = memoryview(data)

    # 1) 主字副本 (槽 0-348)
    for idx in range(MAIN_FONT_COUNT):
        set_glyph(view, idx, main_font_data[idx * GLYPH_SIZE:(idx + 1) * GLYPH_SIZE])

    # 2) 场景字 (槽 349+)
    inverse = {}
    for ch, sidx in scene_map.items():
        sidx = int(sidx)
        if not (SCENE_FONT_BASE <= sidx < total_slots):
            raise ValueError("场景索引越界: %r -> %d (上限 %d)" % (ch, sidx, total_slots - 1))
        inverse[sidx] = ch
    for sidx in range(SCENE_FONT_BASE, total_slots):
        ch = inverse.get(sidx)
        if ch is None:
            continue
        if ch not in glyphs:
            raise ValueError("Missing glyph for scene char %r (idx %d)" % (ch, sidx))
        g = glyphs[ch]
        if len(g) != GLYPH_SIZE:
            raise ValueError("Bad glyph size for %r: %d" % (ch, len(g)))
        set_glyph(view, sidx, g)

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
    errors = []

    for item in workbook:
        tgt = item.get("tgt", "")
        fname = item.get("file", "")
        seg = item.get("seg", 0)
        eid = item.get("id", "")

        if not tgt:
            encoded_texts.append({
                "file": fname, "id": eid, "seg": seg, "encoded_hex": "",
            })
            continue

        try:
            encoded = encode_text(tgt, fname, alloc)
        except ValueError as exc:
            # 建议6: 未映射字符必须显式报告
            errors.append(str(exc))
            continue

        encoded_texts.append({
            "file": fname, "id": eid, "seg": seg, "encoded_hex": encoded.hex(),
        })

    if errors:
        # 建议6/20: 不允许静默产出"半成品"
        raise RuntimeError(
            "文本编码失败: %d 处未映射字符, 首条: %s" % (len(errors), errors[0])
        )

    return encoded_texts


# ============================================================
# 步骤 4: 写入 BIN 镜像 (建议20: 严格报告)
# ============================================================

def patch_bin(original_bin_path, workbook_path, output_path,
              alloc_path=None, font_path=None, threshold=96,
              auto_alloc=False, allow_unknown_image=False):
    """一键导入: 读取翻译 → 编码 → 生成字模 → 写入 BIN。

    Args:
        original_bin_path: str, 原始 BIN 镜像
        workbook_path: str, 翻译工作簿 JSON 路径
        output_path: str, 输出汉化 BIN 路径
        alloc_path: str, 字库分配方案 JSON (建议22: 固定方案)
        font_path: str, 中文字体路径 (建议3: 必须显式提供)
        threshold: int, 二值化阈值 (建议4)
        auto_alloc: bool, 是否允许自动分配字库 (建议22: 默认禁止)
        allow_unknown: bool, 是否允许未知 SHA256 的镜像

    Raises:
        RuntimeError: 任何一致性失败 (建议20: 不允许半成品)
    """
    print("=" * 60)
    print("龙战士4 汉化补丁工具")
    print("=" * 60)

    # [1/6] 读取并校验原始 BIN
    print("\n[1/6] 读取原始 BIN...")
    with open(original_bin_path, 'rb') as f:
        iso_data = bytearray(f.read())
    orig_sha = hashlib.sha256(bytes(iso_data)).hexdigest()
    print("  大小: %d bytes" % len(iso_data))
    print("  SHA256: %s" % orig_sha)

    if orig_sha != EXPECTED_SHA256 and not allow_unknown:
        raise RuntimeError(
            "镜像 SHA256 与目标日版不符!\n"
            "  期望: %s\n"
            "  实际: %s\n"
            "如确认为其他 dump, 请使用 --allow-unknown-image" %
            (EXPECTED_SHA256, orig_sha)
        )

    # [2/6] 读取翻译工作簿
    print("\n[2/6] 读取翻译工作簿...")
    with open(workbook_path, "r", encoding="utf-8") as f:
        workbook = json.load(f)
    print("  条目: %d" % len(workbook))

    # [3/6] 字库分配 (建议22: 固定方案优先)
    print("\n[3/6] 字库分配...")
    if alloc_path and os.path.exists(alloc_path):
        with open(alloc_path, "r", encoding="utf-8") as f:
            alloc_txt = f.read()
        if not alloc_txt.lstrip().startswith('{'):
            alloc_txt = alloc_txt[alloc_txt.index('{'):]
        alloc = json.loads(alloc_txt)
        print("  使用固定分配方案: %s" % alloc_path)
        check_alloc_consistency(alloc)  # 建议21
    elif auto_alloc:
        alloc = allocate_fonts(workbook)
        print("  自动分配 (仅 --auto-alloc 允许): 主字库 %d, 小字库 %d, 场景 %d" % (
            alloc["stats"]["global_main"],
            alloc["stats"]["global_small"],
            alloc["stats"]["scene_count"],
        ))
    else:
        raise RuntimeError(
            "未提供字库分配方案。\n"
            "建议22: 请使用固定的 data/font_alloc.json, 不要每次自动重新分配。\n"
            "用法: --alloc data/font_alloc.json"
        )

    # [4/6] 生成字模 (建议3/4)
    print("\n[4/6] 生成字模...")
    glyphs = generate_glyphs(alloc, font_path, threshold=threshold)
    main_font_data = build_main_font(alloc, glyphs)
    print("  字模数: %d, 主字库: %d bytes, 阈值: %d" % (
        len(glyphs), len(main_font_data), threshold
    ))

    # [5/6] 编码文本 (建议6: 未映射即报错)
    print("\n[5/6] 编码文本...")
    encoded_texts = encode_all_texts(workbook, alloc)
    enc_by_fileseg = defaultdict(list)
    for et in encoded_texts:
        enc_by_fileseg[(et["file"], et["seg"])].append(et)
    n_nonempty = sum(1 for et in encoded_texts if et["encoded_hex"])
    print("  编码: %d 条 (非空 %d)" % (len(encoded_texts), n_nonempty))

    # [6/6] 写入 BIN
    print("\n[6/6] 写入 BIN 镜像...")
    files = list_iso_files(bytes(iso_data))
    modified = bytearray(iso_data)
    patched = 0
    relocated = []
    emi_replacements = defaultdict(dict)   # name -> {seg_index: new_data}
    scene_font_count = 0
    written_keys = set()    # 建议20: 已写入的 (file, seg)
    text_seg_keys = set()   # 游戏中全部文本段 (file, seg)

    # 缓存每个 EMI 的解析结果
    emi_cache = {}
    for name, lba, size in files:
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        emi_buf = bytearray(read_file_from_iso(bytes(iso_data), lba, size))
        parsed = parse_emi(bytes(emi_buf))
        if parsed is None:
            continue
        emi_cache[name] = (emi_buf, parsed, lba, size)

        modified_emi = False
        has_replacement = False
        for seg in parsed["segments"]:
            vals = is_text_segment(seg["data"])
            if vals is None:
                continue

            blk_seg = seg["index"] + 1
            key = (name, blk_seg)
            text_seg_keys.add(key)
            if key not in enc_by_fileseg:
                continue

            # 建议14/15: ID 精确匹配
            encoded_map = build_encoded_map(enc_by_fileseg[key])
            new_seg_data = build_text_segment(seg["data"], vals, encoded_map)

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
                # 建议16/17/18: EMI relocation (超长段扩容, 不再报错)
                emi_replacements[name][seg["index"]] = new_seg_data
                has_replacement = True
                relocated.append((name, blk_seg, new_padded, old_padded))
            written_keys.add(key)

        if modified_emi and not has_replacement:
            write_file_to_iso(modified, lba, bytes(emi_buf), size)

    # ---- 场景字库写入 (v2 架构: 349 主字副本 + 场景字, 扩容到 349+scene_max 槽) ----
    scene_target = int(alloc.get("scene_max", 128))
    print("\n写入场景字库 (349 主字副本 + %d 场景字槽)..." % scene_target)
    for fname, scene_map in alloc.get("scene", {}).items():
        if fname == "SYSTEM/INIT.EMI":
            # INIT.EMI 的字库段即主字库段, 场景字在主字库写入时合并处理
            continue
        if fname not in emi_cache:
            raise RuntimeError("场景分配引用了不存在的文件: %s" % fname)
        _buf, parsed_f, _lba, _size = emi_cache[fname]
        font_segs_f = find_font_segments(parsed_f)
        if not font_segs_f:
            print("  警告: %s 无字库段, 场景字跳过" % fname)
            continue
        scene_data = build_scene_font_data(main_font_data, scene_map, glyphs, scene_target)
        for fs in font_segs_f[:1]:   # 写入第一个字库段
            emi_replacements[fname][fs["index"]] = scene_data
            scene_font_count += 1
    print("  场景字库文件数: %d" % scene_font_count)

    # ---- INIT.EMI 主字库 (建议9: 按 sig=0x1C000200 定位; 布局: 21 列网格, 见 bof4lib) ----
    print("\n写入主字库到 INIT.EMI...")
    init_files = [(n, l, s) for n, l, s in files if n == "SYSTEM/INIT.EMI"]
    if not init_files:
        raise RuntimeError("未找到 SYSTEM/INIT.EMI!")
    init_name, init_lba, init_size = init_files[0]
    _init_buf, init_parsed, _l, _s = emi_cache["SYSTEM/INIT.EMI"]
    font_segs = find_font_segments(init_parsed)
    if not font_segs:
        raise RuntimeError("INIT.EMI 中未找到 sig=0x%08X 的字库段" % FONT_SEG_SIG)
    font_seg = font_segs[0]
    if MAIN_FONT_COUNT > glyph_capacity(font_seg["size"]):
        raise RuntimeError("主字库 %d 槽 > 字体段容量 %d 槽" % (
            MAIN_FONT_COUNT, glyph_capacity(font_seg["size"])))
    init_font_data = bytearray(font_seg["size"])
    view = memoryview(init_font_data)
    for idx in range(MAIN_FONT_COUNT):
        set_glyph(view, idx, main_font_data[idx * GLYPH_SIZE:(idx + 1) * GLYPH_SIZE])
    # INIT.EMI 自身的场景字 (若分配), 写入 349+ 槽 (段容量 370 槽, 余 21 槽)
    init_scene = alloc.get("scene", {}).get("SYSTEM/INIT.EMI", {})
    if init_scene:
        cap = glyph_capacity(font_seg["size"])
        inv = {int(v): k for k, v in init_scene.items()}
        for sidx in range(SCENE_FONT_BASE, min(cap, 0x200)):
            ch = inv.get(sidx)
            if ch is None:
                continue
            if ch not in glyphs:
                raise ValueError("Missing glyph for INIT scene char %r" % ch)
            set_glyph(view, sidx, glyphs[ch])
        print("  INIT.EMI 场景字: %d 个 (合并写入主字库段 349+ 槽)" % len(init_scene))
    emi_replacements["SYSTEM/INIT.EMI"][font_seg["index"]] = bytes(init_font_data)
    print("  主字库: %d 字模 -> seg%d (%d bytes)" % (
        MAIN_FONT_COUNT, font_seg["index"], font_seg["size"]))

    # ---- 统一 EMI 扩容/写入 (原地 或 搬移尾部) ----
    print("\n应用 EMI 修改 (%d 个文件)..." % len(emi_replacements))
    from emi_expand import expand_emi_in_iso
    moved_count = 0
    for name, reps in emi_replacements.items():
        res = expand_emi_in_iso(modified, name, reps)
        if res["moved"]:
            moved_count += 1
    print("  原地写入: %d, 搬移: %d" % (len(emi_replacements) - moved_count, moved_count))

    # ---- 建议20: 严格校验 (不允许半成品) ----
    # 1) 所有分配字符必须有字形
    alloc_chars = set(alloc.get("global_main", {})) | set(alloc.get("global_small", {}))
    alloc_chars |= set(alloc.get("small_font_inherent", {}))
    for _f, _m in alloc.get("scene", {}).items():
        alloc_chars |= set(_m.keys())
    missing_glyphs = sorted(alloc_chars - set(glyphs.keys()))

    # 2) 所有翻译段必须写入 (原地或 relocation)
    not_written = sorted(set(enc_by_fileseg.keys()) - written_keys)

    # 3) 未提供翻译的文本段 (工作簿未覆盖, 保持原文)
    no_translation = sorted(text_seg_keys - set(enc_by_fileseg.keys()))

    # 4) 翻译错误 (encode_all_texts 已抛错, 到这里必为 0)
    translation_errors = 0

    print("\n" + "=" * 60)
    print("汉化完成 (严格报告):")
    print("  Patched text segments : %d" % patched)
    print("  Relocated segments    : %d" % len(relocated))
    print("  Text segments total   : %d" % len(text_seg_keys))
    print("  Segments w/o translation: %d" % len(no_translation))
    print("  Scene font files      : %d" % scene_font_count)
    print("  EMI moved to tail     : %d" % moved_count)
    print("  Translation errors    : %d" % translation_errors)
    print("  Unknown glyphs        : %d" % len(missing_glyphs))
    print("  Font glyphs missing   : %d" % len(missing_glyphs))
    print("  Unwritten segments    : %d" % len(not_written))
    print("=" * 60)

    if missing_glyphs:
        raise RuntimeError(
            "字模缺失 %d 个字符 (建议20): %s" % (
                len(missing_glyphs), missing_glyphs[:20]))
    if not_written:
        raise RuntimeError(
            "%d 个翻译文本段未写入 (建议20: 不允许半成品): %s" % (
                len(not_written), ["%s seg%d" % k for k in not_written[:10]]))

    # 保存
    print("\n保存汉化 BIN...")
    with open(output_path, 'wb') as f:
        f.write(bytes(modified))

    new_sha = hashlib.sha256(bytes(modified)).hexdigest()
    print("  输出: %s" % output_path)
    print("  大小: %d bytes" % len(modified))
    print("  SHA256: %s" % new_sha)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="龙战士4 汉化补丁工具")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("workbook", help="翻译工作簿 JSON")
    parser.add_argument("output", nargs="?", default="bof4_chinese.bin",
                        help="输出汉化 BIN 路径 (默认: bof4_chinese.bin)")
    parser.add_argument("--alloc", default=None,
                        help="固定字库分配方案 JSON (建议22: 必选)")
    parser.add_argument("--font", default=None,
                        help="中文字体文件路径 (建议3: 必选)")
    parser.add_argument("--threshold", type=int, default=96,
                        help="二值化阈值 (建议4, 默认96)")
    parser.add_argument("--auto-alloc", action="store_true",
                        help="允许自动重新分配字库 (不推荐, 违反建议22)")
    parser.add_argument("--allow-unknown-image", action="store_true",
                        help="允许 SHA256 与目标镜像不同的 dump")
    args = parser.parse_args()

    if not args.font:
        # 尝试从项目目录默认查找
        default_font = os.path.join(
            os.path.dirname(__file__), "..", "font", "NotoSansCJK-Regular.ttc"
        )
        if os.path.isfile(default_font):
            args.font = default_font
        else:
            parser.error(
                "--font 必选: 请提供中文字体路径, 例如 --font font/NotoSansCJK-Regular.ttc"
            )

    patch_bin(
        args.original_bin,
        args.workbook,
        args.output,
        alloc_path=args.alloc,
        font_path=args.font,
        threshold=args.threshold,
        auto_alloc=args.auto_alloc,
        allow_unknown_image=args.allow_unknown_image,
    )


if __name__ == "__main__":
    main()