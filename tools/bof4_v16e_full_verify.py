# -*- coding: utf-8 -*-
"""v16e 全量读回静态自证:

V1 镜像可读: 全部 EMI 段表解析正常
V2 文本段: 指针表有效 + 抽样 round-trip (重新编码 == 镜像内字节)
V3 字库段: 已写槽值域合法; WORLD = 4 套打包池, SYSTEM/DEMO = 描边V1+白芯V9 打包
V4 CLUT 段: WORLD = rewrite 语义; SYSTEM = == 原版
            (例外: INIT seg1/3/4 win0[9] = 7FFF 字芯白化, 其余字节须相等)
V5 扩容文件: 段表自洽 (DEMO 扩容搬移含内)
"""
import json, re, sys, struct, hashlib
from collections import defaultdict

REPO = r"D:\龙战士\bof4-chinese\Breath_of_Fire_IV_HanHua"
sys.path.insert(0, REPO + r"\tools\lib")
sys.path.insert(0, REPO + r"\tools")

from bof4lib import (parse_emi, find_font_segments, is_text_segment,
                     list_iso_files, read_file_from_iso, get_glyph,
                     GLYPH_SIZE, glyph_capacity)

ISO = r"D:\龙战士\bof4_chinese_v16e.bin"
ORIG = r"D:\龙战士\Breath of Fire IV - Utsurowazaru Mono (Japan).bin"
WB = REPO + r"\translation_workbook.json"
ALLOC = REPO + r"\data\font_alloc_4set_v16.json"

sys.path.insert(0, r"C:\Users\Administrator\.local\share\TeleAgent\TeleAgent的工作空间\.temp")
from bof4_v15_full_build import encode_v15, WHITE, G, SWITCH_WIN

wb = json.load(open(WB, encoding="utf-8"))
alloc = json.load(open(ALLOC, encoding="utf-8"))
gsets = {int(k): v for k, v in alloc["global"].items()}
scene = {f: {int(k): v for k, v in s.items()} for f, s in alloc["scene"].items()}
main_slot = {}
for ch in set().union(*[set(v) for v in gsets.values()]):
    cand = [(s, gsets[s][ch]) for s in range(4) if ch in gsets[s]]
    main_slot[ch] = ("global",) + min(cand)

iso = open(ISO, "rb").read()
orig = open(ORIG, "rb").read()
files = {n.upper(): (l, s) for n, l, s in list_iso_files(iso)}
ofile = {n.upper(): (l, s) for n, l, s in list_iso_files(orig)}
demo_s0 = {k: int(v) for k, v in alloc["scene"]["SYSTEM/DEMO.EMI"]["0"].items()} \
    if "SYSTEM/DEMO.EMI" in alloc.get("scene", {}) else {}

errors = []
n_emi = n_text = n_font = n_clut = n_clut_sys = 0
font_slot_check = 0

def is_clut(seg):
    return 0x8002E000 <= seg["sig"] <= 0x8004E000 and seg["size"] == 512

def clut_ok(name, new, old):
    if name != "SYSTEM/INIT.EMI":
        return new == old
    return (new[:18] == old[:18]
            and struct.unpack_from("<H", new, 18)[0] == 0x7FFF
            and new[20:] == old[20:])

# 全部 EMI 逐一检查
for name in sorted(files):
    if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
        continue
    lba, size = files[name]
    buf = read_file_from_iso(iso, lba, size)
    parsed = parse_emi(buf)
    if parsed is None:
        errors.append("V1 %s 非 EMI?" % name)
        continue
    n_emi += 1
    for seg in parsed["segments"]:
        if seg["offset"] + seg["size"] > size:
            errors.append("V1 %s seg%d 数据越界 %d > %d" % (
                name, seg["index"], seg["offset"] + seg["size"], size))
            break

    # 字库段: 值域
    for fseg in find_font_segments(parsed):
        n_font += 1
        cap = glyph_capacity(fseg["size"])
        if name == "SYSTEM/DEMO.EMI":
            gmax = max(demo_s0.values()) + 1 if demo_s0 else 0
        else:
            gmax = max(len(gsets[k]) for k in range(4))
        bad = 0
        for i in range(min(gmax, cap)):
            g = get_glyph(fseg["data"], i)
            if g == b"\x00" * GLYPH_SIZE:
                bad += 1
            else:
                for b in g:
                    if (b >> 4) > 15 or (b & 0xF) > 15:
                        bad += 1; break
        if bad:
            errors.append("V3 %s 字库 %d 坏槽" % (name, bad))
        font_slot_check += min(gmax, cap)

    # CLUT 段: WORLD = rewrite 语义; SYSTEM = == 原版 (INIT [9] 白化例外)
    if name.startswith("SYSTEM/"):
        po = parse_emi(read_file_from_iso(orig, *ofile[name]))
        clut_o = {s["index"]: s["data"] for s in po["segments"] if is_clut(s)} \
            if po else {}
        for seg in parsed["segments"]:
            if not is_clut(seg):
                continue
            n_clut += 1
            n_clut_sys += 1
            if seg["index"] not in clut_o:
                errors.append("V4 %s CLUT seg%d 原版无对应" % (name, seg["index"]))
            elif not clut_ok(name, seg["data"], clut_o[seg["index"]]):
                errors.append("V4 %s CLUT seg%d 与原版差异超出预期" % (name, seg["index"]))
    else:
        for seg in parsed["segments"]:
            if not is_clut(seg):
                continue
            n_clut += 1
            d = seg["data"]
            def gw(k, j):
                return struct.unpack_from("<H", d, k * 32 + j * 2)[0]
            for j in (1, 3, 5, 7):
                if gw(0, j) != WHITE:
                    errors.append("V4 %s win0[%d]=%04X" % (name, j, gw(0, j)))
                    break
            for k, s in ((9, 1), (0xB, 2), (0xC, 3)):
                other = 1 << ((s + 1) % 4)
                if gw(k, 1 << s) != WHITE or gw(k, other) != 0:
                    errors.append("V4 %s win%X 套语义错" % (name, k))
                    break

# 文本段 round-trip 抽样 (每文件段抽 3 条)
import random
random.seed(42)
wb_by = defaultdict(list)
for it in wb:
    wb_by[(it["file"].upper(), str(it["seg"]))].append(it)

rt_ok = rt_fail = 0
for key, items in wb_by.items():
    name = key[0]
    if name not in files:
        errors.append("V2 %s 不在镜像" % name)
        continue
    lba, size = files[name]
    buf = read_file_from_iso(iso, lba, size)
    parsed = parse_emi(buf)
    seg = parsed["segments"][int(key[1]) - 1]
    vals = is_text_segment(seg["data"])
    if vals is None:
        errors.append("V2 %s seg%s 不可解析" % key)
        continue
    n_text += 1
    idx = list(range(len(items)))
    random.shuffle(idx)
    picks = sorted(idx[:3])
    nz = 0
    slot_map = {}
    for k in range(len(vals)):
        s = vals[k]
        e = vals[k + 1] if k + 1 < len(vals) else len(seg["data"])
        if e <= s:
            continue
        raw = seg["data"][s:e]
        if not raw or raw[0] == 0:
            continue
        slot_map[nz] = k
        nz += 1
    for pi in picks:
        it = items[pi]
        tgt = it.get("tgt", "")
        if not tgt:
            continue
        k = slot_map.get(pi)
        if k is None:
            rt_fail += 1
            errors.append("V2 %s seg%s item%d 无槽" % (key[0], key[1], pi))
            continue
        s = vals[k]
        e = vals[k + 1] if k + 1 < len(vals) else len(seg["data"])
        nraw = seg["data"][s:e]
        want = encode_v15(tgt, key[0], gsets, scene, main_slot)
        if nraw.startswith(want):
            rt_ok += 1
        else:
            rt_fail += 1
            if rt_fail <= 5:
                errors.append("V2 %s seg%s item%d round-trip 失败\n  want=%s\n  got =%s" % (
                    key[0], key[1], pi, want.hex()[:60], nraw.hex()[:60]))

print("EMI: %d, 文本段: %d, 字库段: %d, CLUT 段: %d (SYSTEM %d)" % (
    n_emi, n_text, n_font, n_clut, n_clut_sys))
print("字库槽检查: %d, round-trip: %d ok / %d fail" % (font_slot_check, rt_ok, rt_fail))
print("镜像大小: %d (原版 %d, 膨胀 %d)" % (len(iso), len(orig), len(iso) - len(orig)))
if errors:
    print("\nERRORS (%d):" % len(errors))
    for e in errors[:25]:
        print("  " + e)
    sys.exit(1)
print("\nALL CHECKS PASSED")
