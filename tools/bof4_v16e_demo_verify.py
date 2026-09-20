# -*- coding: utf-8 -*-
"""v16e DEMO.EMI + SYSTEM 字库专项验证:

1. DEMO 5 段结构 (seg4 = 0x1C000200, 32768B), 整文件重建后扩容搬移
2. seg2 偏移表+页结构 round-trip: 58 译文页 encode_sys == 镜像字节, 385 未译页 == 原版
3. seg4 字形逐槽比对: 0-329 = 全局池 (暗边V1+白芯V9 打包), 330-429 = DEMO 专属字, 430+ 空
4. INIT seg7 = 同款打包 (与 seg4 池复制一致)
5. SYSTEM CLUT == 原版, 例外: INIT seg1/3/4 win0[9] = 7FFF (字芯白化), 其余字节须相等
6. WORLD CLUT rewrite 仍生效
7. EXE LBA 表指向 DEMO 新 LBA
"""
import struct, sys, json

REPO = r"D:\龙战士\bof4-chinese\Breath_of_Fire_IV_HanHua"
TEMP = r"C:\Users\Administrator\.local\share\TeleAgent\TeleAgent的工作空间\.temp"
sys.path.insert(0, REPO + r"\tools\lib")
sys.path.insert(0, REPO + r"\tools")
sys.path.insert(0, TEMP)

from bof4lib import (parse_emi, find_font_segments, list_iso_files,
                     read_file_from_iso, split_pages, get_glyph,
                     GLYPH_SIZE, glyph_capacity, DSZ, parse_dir)
import bof4_v15_full_build as v15
import bof4_v16e_build as v16

ISO_ORIG = v16.ISO
ISO_V16E = r"D:\龙战士\bof4_chinese_v16e.bin"

iso_o = open(ISO_ORIG, "rb").read()
iso_v = open(ISO_V16E, "rb").read()
files_o = {n.upper(): (l, s) for n, l, s in list_iso_files(iso_o)}
files_v = {n.upper(): (l, s) for n, l, s in list_iso_files(iso_v)}

def is_clut(seg):
    return 0x8002E000 <= seg["sig"] <= 0x8004E000 and seg["size"] == 512

def clut_ok(name, new, old):
    """v16e: INIT 三块允许 win0[9]=7FFF, 其余字节必须与原版一致。"""
    if name != "SYSTEM/INIT.EMI":
        return new == old
    return (new[:18] == old[:18]
            and struct.unpack_from("<H", new, 18)[0] == 0x7FFF
            and new[20:] == old[20:])

fails = []

# ---- 准备: 分配与字形 ----
alloc = json.load(open(REPO + r"\data\font_alloc_4set_v16.json", encoding="utf-8"))
gsets16 = {int(k): v for k, v in alloc["global"].items()}
DEMO = "SYSTEM/DEMO.EMI"
demo_s0 = {k: int(v) for k, v in alloc["scene"][DEMO]["0"].items()}
g0 = gsets16[0]
assert sorted(g0.values()) == list(range(330)), "池套 0 应槽 0-329 双射"
need = set(g0.keys()) | set(demo_s0.keys())
mats = v16.v15.render_1bpp(need, v16.v15.FONT)

# ---- 1. DEMO 结构 ----
lba_o, size_o = files_o[DEMO]
lba_v, size_v = files_v[DEMO]
print("DEMO.EMI: 原版 LBA=%d size=%d -> v16e LBA=%d size=%d" % (lba_o, size_o, lba_v, size_v))
if lba_v == lba_o or size_v <= size_o:
    fails.append("DEMO 应扩容搬移 (LBA 变化, size 增大)")
parsed_o = parse_emi(read_file_from_iso(iso_o, lba_o, size_o))
parsed_v = parse_emi(read_file_from_iso(iso_v, lba_v, size_v))
print("DEMO 段数: %d -> %d" % (len(parsed_o["segments"]), len(parsed_v["segments"])))
if len(parsed_v["segments"]) != 5:
    fails.append("v16e DEMO 应 5 段, 实得 %d" % len(parsed_v["segments"]))
seg4 = parsed_v["segments"][4]
if seg4["sig"] != 0x1C000200:
    fails.append("seg4 sig=%X 应 0x1C000200" % seg4["sig"])
if seg4["size"] != 32768:
    fails.append("seg4 size=%d 应 32768" % seg4["size"])
print("seg4: sig=%08X size=%d (容量 %d 槽)" % (seg4["sig"], seg4["size"], glyph_capacity(32768)))
for idx in range(4):
    if idx == 2:
        continue
    if parsed_o["segments"][idx]["data"] != parsed_v["segments"][idx]["data"]:
        fails.append("DEMO 段 %d 被意外改动" % idx)
print("DEMO 段 0/1/3 一致性: OK" if not any("段 %d 被意外" % i in f for f in fails for i in (0, 1, 3)) else "FAIL")

# ---- 2. seg2 round-trip ----
seg2_o = [s for s in parsed_o["segments"] if s["sig"] == 0x801EC800][0]
seg2_v = [s for s in parsed_v["segments"] if s["sig"] == 0x801EC800][0]
D_o, D_v = seg2_o["data"], seg2_v["data"]
tbl_o = [struct.unpack_from("<H", D_o, i * 2)[0] for i in range(256)]
tbl_v = [struct.unpack_from("<H", D_v, i * 2)[0] for i in range(256)]
if tbl_v[0] != 512:
    fails.append("seg2 表首项应 512")
for i in range(255):
    if tbl_v[i] > tbl_v[i + 1]:
        fails.append("seg2 表非单调 @%d" % i)
        break
spans_o = [D_o[tbl_o[i]: (tbl_o[i + 1] if i < 255 else seg2_o["size"])] for i in range(256)]
spans_v = [D_v[tbl_v[i]: (tbl_v[i + 1] if i < 255 else seg2_v["size"])] for i in range(256)]
SYS_ROWS = v16.load_sys_tsv()
mapping = v16.slot_page_map(tbl_o, spans_o, SYS_ROWS, seg2_o["offset"])
print("映射页数: %d" % len(mapping))
n_repl, n_keep = 0, 0
for i in range(256):
    pages_o = split_pages(spans_o[i])
    pages_v = split_pages(spans_v[i])
    if len(pages_o) != len(pages_v):
        fails.append("槽 %d 页数变化: %d -> %d" % (i, len(pages_o), len(pages_v)))
        continue
    for pi in range(len(pages_o)):
        key = (i, pi)
        if key in mapping:
            try:
                enc = v16.encode_sys(mapping[key], g0, demo_s0)
            except ValueError as exc:
                fails.append("槽 %d 页 %d 编码失败: %s" % (i, pi, exc))
                continue
            if enc != pages_v[pi]:
                fails.append("槽 %d 页 %d 译文不匹配" % (i, pi))
            else:
                n_repl += 1
        else:
            if pages_o[pi] != pages_v[pi]:
                fails.append("槽 %d 页 %d 未译页被改动!" % (i, pi))
            else:
                n_keep += 1
print("seg2 页验证: 译文 round-trip %d OK, 未译页保留 %d OK" % (n_repl, n_keep))

# ---- 3. seg4 字形逐槽比对 (描边V1+白芯V9 打包) ----
fdata = seg4["data"]
n_ok = n_bad = n_empty = 0
inv_g0 = {v: k for k, v in g0.items()}
for slot in range(330):
    ch = inv_g0.get(slot)
    if ch is None:
        fails.append("池套 0 槽 %d 无字?" % slot)
        continue
    want = v16.sys_pack_glyph(mats[ch])
    got = get_glyph(fdata, slot)
    if want != got:
        n_bad += 1
        if n_bad <= 5:
            fails.append("seg4 池槽 %d (%r) 字形不匹配" % (slot, ch))
    else:
        n_ok += 1
demo_inv = {v: k for k, v in demo_s0.items()}
for slot in range(330, 430):
    ch = demo_inv.get(slot)
    if ch is None:
        fails.append("DEMO 专属槽 %d 无字?" % slot)
        continue
    want = v16.sys_pack_glyph(mats[ch])
    got = get_glyph(fdata, slot)
    if want != got:
        n_bad += 1
        if n_bad <= 5:
            fails.append("seg4 专属槽 %d (%r) 字形不匹配" % (slot, ch))
    else:
        n_ok += 1
for slot in range(430, glyph_capacity(32768)):
    if any(get_glyph(fdata, slot)):
        fails.append("seg4 槽 %d 非空 (应为零)" % slot)
        break
    n_empty += 1
print("seg4 字形: %d OK, %d BAD, 空槽 %d" % (n_ok, n_bad, n_empty))

# ---- 4. INIT seg7 打包比对 ----
INIT = "SYSTEM/INIT.EMI"
pv_i = parse_emi(read_file_from_iso(iso_v, *files_v[INIT]))
po_i = parse_emi(read_file_from_iso(iso_o, *files_o[INIT]))
fseg_v = find_font_segments(pv_i)[0]
fseg_o = find_font_segments(po_i)[0]
d_v, d_o = fseg_v["data"], fseg_o["data"]
n_iok = n_ibad = 0
for slot in range(330):
    ch = inv_g0.get(slot)
    want = v16.sys_pack_glyph(mats[ch])
    got = get_glyph(d_v, slot)
    if want != got:
        n_ibad += 1
        if n_ibad <= 5:
            fails.append("INIT seg7 池槽 %d 字形不匹配 (应 描边V1+白芯V9)" % slot)
    else:
        n_iok += 1
tail_bad = sum(1 for s in range(330, min(len(d_v), len(d_o)) // GLYPH_SIZE)
               if get_glyph(d_v, s) != get_glyph(d_o, s))
if tail_bad:
    fails.append("INIT seg7 槽 330+ 与原版不一致: %d 槽" % tail_bad)
print("INIT seg7: 新打包 %d OK / %d BAD, 槽 330+ 原版一致" % (n_iok, n_ibad))

# ---- 5. SYSTEM CLUT == 原版 (例外: INIT 三块 win0[9]) ----
n_sys_clut = 0
for name in sorted(files_v):
    if not name.startswith("SYSTEM/"):
        continue
    pv = parse_emi(read_file_from_iso(iso_v, *files_v[name]))
    po = parse_emi(read_file_from_iso(iso_o, *files_o[name]))
    if pv is None or po is None:
        fails.append("%s 解析失败" % name)
        continue
    clut_v = {s["index"]: s["data"] for s in pv["segments"] if is_clut(s)}
    clut_o = {s["index"]: s["data"] for s in po["segments"] if is_clut(s)}
    if set(clut_v) != set(clut_o):
        fails.append("%s CLUT 段集合变化" % name)
        continue
    for idx, dd in clut_v.items():
        if clut_ok(name, dd, clut_o[idx]):
            n_sys_clut += 1
        else:
            fails.append("%s CLUT seg%d 与原版差异超出 win0[9] 白化!" % (name, idx))
print("SYSTEM CLUT 符合预期 (原版+INIT[9]白化): %d 段" % n_sys_clut)
if n_sys_clut != 66:
    fails.append("SYSTEM CLUT 段数应 66, 实得 %d" % n_sys_clut)

# ---- 6. WORLD CLUT rewrite 仍生效 ----
n_world, n_diff = 0, 0
for name in sorted(files_v):
    if not name.startswith("WORLD/"):
        continue
    pv = parse_emi(read_file_from_iso(iso_v, *files_v[name]))
    po = parse_emi(read_file_from_iso(iso_o, *files_o[name]))
    if pv is None or po is None:
        continue
    clut_v = {s["index"]: s["data"] for s in pv["segments"] if is_clut(s)}
    clut_o = {s["index"]: s["data"] for s in po["segments"] if is_clut(s)}
    for idx, dd in clut_v.items():
        n_world += 1
        if idx in clut_o and dd != clut_o[idx]:
            n_diff += 1
print("WORLD CLUT: %d 段, rewrite %d 段" % (n_world, n_diff))
if n_diff == 0:
    fails.append("WORLD CLUT rewrite 应生效")

# ---- 7. EXE LBA ----
exe_v = None
root = parse_dir(iso_v, 22, DSZ)
for nm, lba, sz, isd in root:
    if nm.startswith("SLPS"):
        exe_v = read_file_from_iso(iso_v, lba, sz)
        break
hits = 0
off = 0x07ACE4
while off < len(exe_v) - 4:
    val = struct.unpack_from("<I", exe_v, off)[0]
    if not (90000 <= val <= 300000):
        break
    if val == lba_v:
        hits += 1
    off += 4
print("EXE LBA 表中 DEMO 新 LBA %d 出现 %d 次" % (lba_v, hits))
if hits == 0:
    fails.append("EXE LBA 表未同步 DEMO 新 LBA!")

print()
if fails:
    print("=== 失败 %d ===" % len(fails))
    for f in fails[:20]:
        print("  " + f)
    sys.exit(1)
print("=== v16e DEMO+字库专项验证全部通过 ===")
