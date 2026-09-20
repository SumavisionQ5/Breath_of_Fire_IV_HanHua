# -*- coding: utf-8 -*-
"""导出 DEMO.EMI seg2 中 385 页未翻译日文 + 检查 START.EMI 文本段。

解码规则 (系统文本编码):
  0x20-0xFF → small_font_index.csv (byte → 字符)
  0x12 XX   → main_font_index.csv slot XX (原版日文)
  0x13 XX   → main_font_index.csv slot XX+256
  0x15 XX   → 图标码 (×△□』)
  0x01      → \n
  0x02      → \n---\n
  0x05 XX   → {色XX}
  0x06      → {/色}
  其他控制码 → CTRL_NAME 格式
"""
import sys, struct, csv, json, os, re

REPO = r"D:\龙战士\bof4-chinese\Breath_of_Fire_IV_HanHua"
TEMP = r"C:\Users\Administrator\.local\share\TeleAgent\TeleAgent的工作空间\.temp"
sys.path.insert(0, REPO + r"\tools\lib")
sys.path.insert(0, REPO + r"\tools")
sys.path.insert(0, TEMP)

from bof4lib import (parse_emi, list_iso_files, read_file_from_iso,
                     split_pages, CTRL_CODES, CTRL_LEN, CTRL_NAME,
                     is_text_segment)
import bof4_v16e_build as v16

ISO = r"D:\龙战士\Breath of Fire IV - Utsurowazaru Mono (Japan).bin"
iso = open(ISO, "rb").read()
files = {n.upper(): (l, s) for n, l, s in list_iso_files(iso)}

# ---- 1. 构建解码表 ----
# 小字库: byte -> char (手动解析, CSV 有未转义引号和特殊行)
sf = {}
raw = open(REPO + r"\data\small_font_index.csv", encoding="utf-8-sig").read()
for line in raw.splitlines()[1:]:
    parts = line.split(",")
    if len(parts) >= 3:
        ch = parts[1] if parts[1] else " "
        enc_str = parts[2].strip()
        try:
            enc = int(enc_str, 16)
        except ValueError:
            continue
        sf[enc] = ch

# 主字库: slot -> char (原版日文, 文件内 \n 为字面量需替换)
mf = {}
raw2 = open(REPO + r"\data\main_font_index.csv", encoding="utf-8-sig").read()
for line in raw2.replace("\\n", "\n").splitlines()[1:]:  # 跳过表头
    parts = line.split(",")
    if len(parts) >= 4:
        idx = int(parts[0])
        ch = parts[3] if parts[3] else ""
        if ch:
            mf[idx] = ch

print("小字库: %d 项, 主字库: %d 项" % (len(sf), len(mf)))

# 图标码 0x15 XX
ICON = {0x01: "×", 0x02: "△", 0x03: "□", 0x0A: "』"}

def decode_sys_page(buf):
    """将系统文本字节解码为可读文本。"""
    out = []
    i = 0
    while i < len(buf):
        b = buf[i]
        if b == 0x00:
            break  # 页终止
        if b in CTRL_LEN:
            clen = CTRL_LEN[b]
            if b == 0x01:
                out.append("\n")
            elif b == 0x02:
                out.append("\n---\n")
            elif b == 0x15:
                # 图标码
                if i + 1 < len(buf):
                    param = buf[i + 1]
                    out.append(ICON.get(param, "{符号2 %02X}" % param))
            elif b == 0x12:
                if i + 1 < len(buf):
                    slot = buf[i + 1]
                    out.append(mf.get(slot, "{槽%d}" % slot))
            elif b == 0x13:
                if i + 1 < len(buf):
                    slot = buf[i + 1] + 256
                    out.append(mf.get(slot, "{槽%d}" % slot))
            elif b in CTRL_NAME:
                name = CTRL_NAME[b]
                # 填充参数
                plen = clen - 1
                if plen > 0 and i + plen < len(buf):
                    params = [buf[i + 1 + k] for k in range(plen)]
                    try:
                        out.append(name % tuple(params))
                    except Exception:
                        out.append(name)
                else:
                    out.append(name)
            else:
                out.append("{码%02X}" % b)
            i += clen
        elif 0x20 <= b <= 0xFF:
            # 小字库
            ch = sf.get(b, "")
            if ch:
                out.append(ch)
            else:
                out.append("{byte%02X}" % b)
            i += 1
        else:
            out.append("{byte%02X}" % b)
            i += 1
    return "".join(out)

# ---- 2. 解析 seg2, 找出未翻译页 ----
DEMO = "SYSTEM/DEMO.EMI"
lba, size = files[DEMO]
parsed = parse_emi(read_file_from_iso(iso, lba, size))
seg2 = [s for s in parsed["segments"] if s["sig"] == 0x801EC800][0]
tbl, spans = v16.parse_seg2(seg2["data"], seg2["size"])

# 已翻译页的映射
SYS_ROWS = v16.load_sys_tsv()
mapping = v16.slot_page_map(tbl, spans, SYS_ROWS, seg2["offset"])
translated_keys = set(mapping.keys())
print("已翻译页: %d, 未翻译页目标: %d" % (len(translated_keys), 256 * 0))

# 遍历所有槽所有页, 收集未翻译页
rows_out = []
n_untranslated = 0
n_empty = 0
for slot_idx in range(256):
    pages = split_pages(spans[slot_idx])
    for page_idx, page_bytes in enumerate(pages):
        if not page_bytes or page_bytes == b"\x00":
            n_empty += 1
            continue
        key = (slot_idx, page_idx)
        if key in translated_keys:
            continue
        decoded = decode_sys_page(page_bytes)
        if not decoded.strip():
            n_empty += 1
            continue
        rows_out.append({
            "id": "sys2_%03d" % (len(rows_out) + 1),
            "slot": slot_idx,
            "page": page_idx,
            "hex": page_bytes.hex(),
            "src": decoded.replace("\n", "\\n"),
        })
        n_untranslated += 1

print("未翻译页: %d (空页 %d)" % (n_untranslated, n_empty))

# ---- 3. 写 TSV ----
out_path = os.path.join(TEMP, "system_text_remaining.tsv")
with open(out_path, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["id", "slot", "page", "hex", "src", "tgt"])
    for r in rows_out:
        w.writerow([r["id"], r["slot"], r["page"], r["hex"], r["src"], ""])
print("已写出: %s (%d 条)" % (out_path, len(rows_out)))

# ---- 4. 检查所有 SYSTEM EMI 的 seg2 并导出 ----
print("\n=== 扫描所有 SYSTEM EMI 的 seg2 ===")
all_rows = list(rows_out)  # DEMO 的 128 条已收集
for name in sorted(files):
    if not name.startswith("SYSTEM/") or not name.endswith(".EMI"):
        continue
    if name == DEMO:
        continue  # 已处理
    lba2, size2 = files[name]
    p = parse_emi(read_file_from_iso(iso, lba2, size2))
    if p is None:
        continue
    seg2_list = [s for s in p["segments"] if s["sig"] == 0x801EC800]
    if not seg2_list:
        continue
    seg = seg2_list[0]
    try:
        stbl, sspans = v16.parse_seg2(seg["data"], seg["size"])
    except AssertionError:
        print("  %s: seg2 表结构不兼容 (tbl[0]!=512), 跳过" % name)
        continue
    n_pages = 0
    for si in range(256):
        pgs = split_pages(sspans[si])
        for pi, pb in enumerate(pgs):
            if not pb or pb == b"\x00":
                continue
            dec = decode_sys_page(pb)
            if not dec.strip():
                continue
            n_pages += 1
            all_rows.append({
                "id": "sys2_%03d" % (len(all_rows) + 1),
                "slot": si,
                "page": pi,
                "hex": pb.hex(),
                "src": dec.replace("\n", "\\n"),
                "file": name,
            })
    print("  %s: %d 页" % (name, n_pages))

# 合并写出
out_path = os.path.join(TEMP, "system_text_remaining.tsv")
with open(out_path, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["id", "file", "slot", "page", "hex", "src", "tgt"])
    for r in all_rows:
        fname = r.get("file", DEMO)
        w.writerow([r["id"], fname, r["slot"], r["page"], r["hex"], r["src"], ""])
print("\n合并写出: %s (%d 条)" % (out_path, len(all_rows)))
