# -*- coding: utf-8 -*-
"""
analyze_font_usage.py — 字符用量分析与字库分配工具 v2.1

核心理念 (font_allocator_v2):
    1806 是"全游戏字符集合", 不是"同时需要加载的字符"。
    BOF4 的 Global + Scene 动态字库缓存架构可以承载中文,
    前提是 Scene Font 从日文时代的 21~71 字扩容到 ~128 字。

v2.1 关键修正:
    SYSTEM/CAMP、SHOP、MASTER、MSHOP、SGAMEN、SGAMENX、COMMU03 等
    系统界面文件 **没有自己的字库段** (它们直接使用 INIT.EMI 全局字库)。
    因此这些文件用到的所有字符必须进全局字库,
    场景字只分配给"有字库段的文件"。

分配算法:
    1. must_global = 所有无字库段文件的字符并集 (强制全局)
    2. 全局 554 名额: must_global 优先按频率填充,
       剩余名额给"跨文件高价值"字符
    3. 场景字: 有字库段的文件, 每文件 ≤ scene_target (默认 128)
    4. 严格验证: 0 不可编码 / 0 场景溢出

用法:
    python tools/analyze_font_usage.py <translation_workbook.json> <original.bin> \
        [--scene-target 128] [--alloc-out data/font_alloc_v2.json] \
        [--report-out font_usage_report.json]

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import argparse
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    read_file_from_iso, list_iso_files, parse_emi, find_font_segments,
    FONT_SEG_SIG,
)

MAIN_CAP = 349    # global_main 容量
SMALL_CAP = 205   # global_small 容量


def scan_font_seg_files(iso_path):
    """扫描 ISO, 返回 (有字库段的文件集合, 全部含文本的 EMI 文件集合)。"""
    with open(iso_path, 'rb') as f:
        iso_data = f.read()
    files = list_iso_files(iso_data)
    has_font = set()
    all_emi = set()
    for name, lba, size in files:
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        all_emi.add(name)
        buf = read_file_from_iso(iso_data, lba, size)
        parsed = parse_emi(buf)
        if parsed is None:
            continue
        if find_font_segments(parsed):
            has_font.add(name)
    return has_font, all_emi


def analyze(workbook, scene_target, has_font_files, skip_no_font=False):
    """分析字符用量并生成分配方案 (v2.1)。

    Args:
        workbook: list, 翻译工作簿
        scene_target: int, 每场景字库上限
        has_font_files: set, 有字库段的文件集合
        skip_no_font: bool, 若 True 则无字库段文件不参与汉化
                      (其字符不强制全局, 文本保持日文, 待后续方案)

    Returns:
        (alloc, report)
    """
    # ---- 1. 统计 ----
    char_files = defaultdict(set)
    char_freq = Counter()
    file_chars = defaultdict(set)
    skipped_files = []

    for item in workbook:
        tgt = item.get("tgt", "")
        fname = item.get("file", "")
        if not tgt:
            continue
        if skip_no_font and fname not in has_font_files:
            if fname not in skipped_files:
                skipped_files.append(fname)
            continue
        for ch in tgt:
            if ord(ch) > 0x7E:
                char_files[ch].add(fname)
                char_freq[ch] += 1
                file_chars[fname].add(ch)

    # ---- 2. must_global: 无字库段文件的所有字符强制全局 ----
    must_global = set()
    no_font_files = []
    for fname in file_chars:
        if fname not in has_font_files:
            must_global |= file_chars[fname]
            no_font_files.append(fname)

    # ---- 3. 全局分配 ----
    # 3a. must_global 优先 (按频率)
    must_sorted = sorted(must_global, key=lambda c: -char_freq[c])
    global_chars = list(must_sorted)
    # 3b. 剩余名额: 其他字符按 (跨文件数, 频率) 降序
    def value_key(ch):
        return (len(char_files[ch]), char_freq[ch])
    others = sorted((c for c in char_freq if c not in must_global),
                    key=value_key, reverse=True)
    cap = MAIN_CAP + SMALL_CAP
    for ch in others:
        if len(global_chars) >= cap:
            break
        global_chars.append(ch)

    global_main = {}
    global_small = {}
    for ch in global_chars[:MAIN_CAP]:
        global_main[ch] = len(global_main)
    for ch in global_chars[MAIN_CAP:cap]:
        global_small[ch] = len(global_small)
    gset = set(global_main) | set(global_small)

    # ---- 4. 场景分配 (仅有字库段的文件) ----
    scene = {}
    overflow = defaultdict(list)
    unencodable = []
    for fname, chars in file_chars.items():
        need = sorted(chars - gset, key=lambda c: (-char_freq[c], c))
        if fname not in has_font_files:
            # 无字库段文件: 需求必须为 0 (全部已全局)
            if need:
                unencodable.append((fname, need[:10]))
            continue
        d = {}
        for ch in need[:scene_target]:
            d[ch] = 349 + len(d)
        if len(need) > scene_target:
            overflow[fname] = need[scene_target:]
        if d:
            scene[fname] = d

    # ---- 5. 报告 ----
    per_file = {}
    for fname in sorted(file_chars.keys()):
        chars = file_chars[fname]
        need = chars - gset
        sm = scene.get(fname, {})
        per_file[fname] = {
            "total_chars": len(chars),
            "global_hit": len(chars - need),
            "scene_needed": len(need),
            "scene_allocated": len(sm),
            "scene_overflow": len(overflow.get(fname, [])),
            "has_font_seg": fname in has_font_files,
        }

    alloc = {
        "global_main": global_main,
        "global_small": global_small,
        "scene": scene,
        "small_font_inherent": {},
        "scene_max": scene_target,
        "skipped_files": sorted(skipped_files),
        "stats": {
            "global_main": len(global_main),
            "global_small": len(global_small),
            "must_global": len(must_global),
            "no_font_files": sorted(no_font_files),
            "total_distinct": len(char_freq),
            "scene_files": len(scene),
            "scene_avg": round(sum(len(s) for s in scene.values()) / max(1, len(scene)), 1),
            "scene_max_used": max((len(s) for s in scene.values()), default=0),
            "overflow_files": len(overflow),
            "unencodable": len(unencodable),
            "skipped_files": len(skipped_files),
        },
    }
    report = {
        "per_file": per_file,
        "overflow": {k: v for k, v in overflow.items()},
        "unencodable": unencodable[:50],
        "scene_target": scene_target,
        "skipped_files": sorted(skipped_files),
    }
    return alloc, report


def main():
    parser = argparse.ArgumentParser(description="龙战士4 字符用量分析与字库分配 v2.1")
    parser.add_argument("workbook", help="翻译工作簿 JSON")
    parser.add_argument("original_bin", help="原始日版 BIN (用于扫描字库段归属)")
    parser.add_argument("--scene-target", type=int, default=128,
                        help="每场景字库上限 (默认 128; 原版 21-71)")
    parser.add_argument("--skip-no-font-seg", action="store_true",
                        help="无字库段的文件 (CAMP/SHOP 等系统界面) 暂不汉化, 待后续方案")
    parser.add_argument("--alloc-out", default="font_alloc_v2.json")
    parser.add_argument("--report-out", default="font_usage_report.json")
    args = parser.parse_args()

    with open(args.workbook, "r", encoding="utf-8") as f:
        workbook = json.load(f)
    print("工作簿: %d 条" % len(workbook))

    print("扫描 ISO 字库段归属...")
    has_font, _ = scan_font_seg_files(args.original_bin)
    print("  有字库段的文件: %d 个" % len(has_font))

    alloc, report = analyze(workbook, args.scene_target, has_font, skip_no_font=args.skip_no_font_seg)

    with open(args.alloc_out, "w", encoding="utf-8") as f:
        json.dump(alloc, f, ensure_ascii=False, indent=1)
    with open(args.report_out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    st = alloc["stats"]
    print("\n===== 分配统计 (v2.1) =====")
    print("  全游戏不同字符   : %d" % st["total_distinct"])
    print("  must_global      : %d (无字库段文件强制全局)" % st["must_global"])
    print("  无字库段文件     : %s" % ", ".join(st["no_font_files"]))
    print("  global_main      : %d / 349" % st["global_main"])
    print("  global_small     : %d / 205" % st["global_small"])
    print("  含场景字的文件数 : %d" % st["scene_files"])
    print("  场景字平均/最大  : %.1f / %d (上限 %d)" % (
        st["scene_avg"], st["scene_max_used"], args.scene_target))
    print("  场景溢出文件     : %d" % st["overflow_files"])
    print("  不可编码         : %d" % st["unencodable"])
    print("  跳过的无字库文件 : %d %s" % (st["skipped_files"], alloc.get("skipped_files", [])[:8]))

    if report["unencodable"]:
        print("\n!! 不可编码 (无字库段文件但字符未全局):")
        for fname, chs in report["unencodable"][:10]:
            print("   %s: %s" % (fname, chs))
    if st["overflow_files"]:
        print("\n!! 场景溢出文件:")
        for fname, chars in list(report["overflow"].items())[:10]:
            print("   %s: %d 字放不下: %s" % (fname, len(chars), chars[:8]))

    print("\n已输出: %s" % args.alloc_out)
    print("已输出: %s" % args.report_out)

    needs = sorted((v["scene_needed"] for v in report["per_file"].values()), reverse=True)
    if needs:
        print("\n场景需求 Top10: %s" % needs[:10])


if __name__ == "__main__":
    main()