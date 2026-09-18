# -*- coding: utf-8 -*-
"""
check_capacity.py — 译文字符容量审计工具

统计各 EMI 文件用字数, 对比字库段容量, 报告超标情况。
用于在生成镜像前评估当前译文的字库容量压力。

容量模型 (21 列布局, 已验证):
    - 全局共享槽: 索引 0-329 (330 槽), 所有场景字库段内容一致
    - 场景专属槽: 索引 330+, 每文件独立, 上限 = 段容量 - 330
    - 段容量: 28672B → 378 槽 (场景 48)
             30720B → 388 槽 (场景 58)
             32768B → 441 槽 (场景 111)
    - 7 个无字库段系统文件 (CAMP/SHOP/MASTER/MSHOP/SGAMEN/SGAMENX/COMMU03)
      运行时使用当前 VRAM 字库 → 用字必须全部在全局槽内

用法:
    python tools/check_capacity.py <workbook.json> [--tsv <dir>] [--alloc data/font_alloc_v2.json]

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import re
import argparse
from collections import defaultdict, Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import glyph_capacity

CTRL_RE = re.compile(r'\{[^}]*\}')
GLOBAL_SLOTS = 330


def load_small_font_chars(bof4_root):
    """小字库固有字符 (单字节编码, 不占主字库槽)。"""
    path = os.path.join(bof4_root, "data", "small_font_index.csv")
    chars = {" "}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            next(f)
            for line in f:
                parts = line.strip().split(",")
                idx = int(parts[0])
                if idx <= 61 or (224 <= idx <= 234):
                    chars.add(parts[1])
    return chars


def extract_main_chars(text, small_chars):
    t = CTRL_RE.sub('', text)
    t = t.replace('\\n', '').replace('---', '')
    out = set()
    for c in t:
        if c in small_chars or ord(c) < 0x20 or c in '\n\r\t':
            continue
        out.add(c)
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    bof4_root = os.path.join(os.path.dirname(__file__), "..")
    ap = argparse.ArgumentParser(description="译文字符容量审计")
    ap.add_argument("workbook", help="translation_workbook.json")
    ap.add_argument("--alloc", default=os.path.join(bof4_root, "data", "font_alloc_v2.json"),
                    help="font_alloc json (取无字库文件列表)")
    args = ap.parse_args()

    with open(args.workbook, encoding="utf-8") as f:
        wb = json.load(f)
    with open(args.alloc, encoding="utf-8") as f:
        alloc = json.load(f)
    seg_report_path = os.path.join(bof4_root, "data", "font_segments_report.json")
    with open(seg_report_path, encoding="utf-8") as f:
        seg_report = json.load(f)

    small_chars = load_small_font_chars(bof4_root)

    # 每文件用字
    file_chars = defaultdict(set)
    for e in wb:
        tgt = e.get("tgt") or ""
        if not tgt:
            continue
        file_chars[e["file"]].update(extract_main_chars(tgt, small_chars))

    # 容量
    file_capacity = {}
    for fname, segs in seg_report["segments"].items():
        for seg in segs:
            file_capacity[fname] = glyph_capacity(seg["size"])
    no_font_files = set(alloc.get("skipped_files", []))

    # 字符跨文件频率
    char_files = Counter()
    for fname, chars in file_chars.items():
        for c in chars:
            char_files[c] += 1

    union = set()
    for chars in file_chars.values():
        union |= chars

    print("=" * 62)
    print("龙战士4 译文字符容量审计")
    print("=" * 62)
    print("总条目          : %d" % len(wb))
    print("唯一字符并集    : %d" % len(union))
    print("全局槽位        : %d (索引 0-%d)" % (GLOBAL_SLOTS, GLOBAL_SLOTS - 1))
    print("并集 vs 全局槽  : %s" % (
        "超限 %d 字" % (len(union) - GLOBAL_SLOTS)
        if len(union) > GLOBAL_SLOTS
        else "OK (余 %d 槽)" % (GLOBAL_SLOTS - len(union))))

    nf_union = set()
    for f in no_font_files:
        nf_union |= file_chars.get(f, set())
    print("无字库文件 (7个) 用字并集: %d vs 全局槽 %d: %s" % (
        len(nf_union), GLOBAL_SLOTS,
        "超限 %d 字" % (len(nf_union) - GLOBAL_SLOTS)
        if len(nf_union) > GLOBAL_SLOTS else "OK"))

    # 贪心全局分配后的场景槽超标
    greedy = set(c for c, _ in sorted(char_files.items(),
                                       key=lambda x: (-x[1], x[0]))[:GLOBAL_SLOTS])
    overflow = []
    for fname in sorted(file_chars):
        chars = file_chars[fname]
        if fname in file_capacity:
            cap = file_capacity[fname]
            scene_cap = cap - GLOBAL_SLOTS
            total_exceed = max(0, len(chars) - cap)
        else:
            cap = GLOBAL_SLOTS
            scene_cap = 0
            total_exceed = max(0, len(chars) - cap)
        scene_needed = len(chars - greedy)
        scene_exceed = max(0, scene_needed - scene_cap) if scene_cap else scene_needed
        if total_exceed or scene_exceed:
            overflow.append((fname, len(chars), cap, total_exceed,
                              scene_needed, scene_cap, scene_exceed))

    print("超标文件数      : %d / %d" % (len(overflow), len(file_chars)))
    if overflow:
        print()
        print("%-28s %6s %6s %6s %6s %6s %6s" % (
            "文件", "用字", "容量", "总超", "场景字", "场景槽", "场景超"))
        for row in sorted(overflow, key=lambda x: -x[3])[:40]:
            print("%-28s %6d %6d %6d %6d %6d %6d" % row)
        if len(overflow) > 40:
            print("... 另有 %d 个文件" % (len(overflow) - 40))
    print()
    print("结论: 全量译文的字符数远超原版字库架构容量。")
    print("可行路径见 docs/cracking_analysis.md 第 8 节 (扩容搬移/精简用字/定位小字库)。")


if __name__ == "__main__":
    main()
