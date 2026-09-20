# -*- coding: utf-8 -*-
"""v16 全量汉化镜像构建 = v15 全量 + 62 条系统文本回填 (SYSTEM/DEMO.EMI seg2)。

新增架构 (相对 v15):
  - seg2 (sig=0x801EC800) 结构定案: 256 项 u16 段内偏移表 (512B) + 数据区,
    槽跨度 [tbl[i], tbl[i+1]) 内多页 0x00 分隔 (与主文本块同构, split_pages 兼容)
  - 系统文本编码规则 (与主文本不同):
      * 单字节 0x20-0xFF -> 原版小字库 idx 0-223 (ASCII/标点/假名字形, v15 未动)
      * 0x15 XX -> 图标控制码 (×=15 01 △=15 02 □=15 03 』=15 0A), CTRL_LEN[0x15]=2
      * 0x12/0x13 -> 主字库全局池 (汉字, 强制套 0)
  - 62 条译文映射到 (槽,页); 未映射页逐字节保留; b'\\x00'.join 恒等重组
  - v16d 分配: v15 复制 + DEMO seg4 池复制架构 (池 330 复制 + 专属字槽 G..)
  - v16d SYSTEM 字库专用打包: 套 0 字芯 -> V=8 (原版字形实证字芯值)
"""
import json, re, sys, os, struct, hashlib, csv
from collections import Counter, defaultdict

REPO = r"D:\龙战士\bof4-chinese\Breath_of_Fire_IV_HanHua"
TEMP = r"C:\Users\Administrator\.local\share\TeleAgent\TeleAgent的工作空间\.temp"
sys.path.insert(0, REPO + r"\tools\lib")
sys.path.insert(0, REPO + r"\tools")
sys.path.insert(0, TEMP)

from bof4lib import (CTRL_CODES, CTRL_LEN, DSZ, parse_emi, find_font_segments,
                     is_text_segment, list_iso_files, read_file_from_iso,
                     write_file_to_iso, set_glyph, get_glyph, GLYPH_SIZE,
                     trim, split_pages, build_text_segment, glyph_capacity,
                     glyph_seg_size, FONT_SEG_SIG)
from emi_expand import write_emi_to_iso, expand_emi_in_iso
import bof4_v15_full_build as v15

ISO = r"D:\龙战士\Breath of Fire IV - Utsurowazaru Mono (Japan).bin"
OUT = r"D:\龙战士\bof4_chinese_v16e.bin"
V15_ALLOC = REPO + r"\data\font_alloc_4set.json"
TSV = os.path.join(TEMP, "system_text.tsv")
DEMO = "SYSTEM/DEMO.EMI"
SEG2_SIG = 0x801EC800
G = 330    # 保持 v15 场景区基准 (AREAS041/042 等卡满文件硬约束)
DEMO_SEG4_SIZE = 32768  # seg4 尺寸 = 场景字库段同款 (容量 455 槽)
                        # v16c 实证: 花屏根因是 INIT CLUT rewrite; 三版 seg4
                        # (32768/28672/无) 花屏完全一致 -> seg4 尺寸非花屏因素
DEMO_FONT_IDX = 4 # DEMO 追加字库段的段索引 (原 4 段: 0-3)

code_re = re.compile(r"\{([^}]*)\}")
color_re = re.compile(r"\{色([0-9A-Fa-f]{2})\}")

# 系统文本符号 -> 字节 (全部来自原文块字节实证)
SYM = {
    "×": b"\x15\x01", "△": b"\x15\x02", "□": b"\x15\x03", "』": b"\x15\x0a",
    "·": b"\x40", "（": b"\x28", "）": b"\x29", "：": b"\x3a",
    "？": b"\x3f", "。": b"\x23", "、": b"\x24", "！": b"\x21",
    "―": b"\x2d", "－": b"\x2d", "～": b"\x5d",
}

# ============================================================
# 1. 加载 62 条 + 扫描扩展
# ============================================================

def load_sys_tsv():
    rows = []
    with open(TSV, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            r["tgt"] = r["tgt"].replace("\\n", "\n")
            r["src"] = r["src"].replace("\\n", "\n")
            rows.append(r)
    assert len(rows) == 62, "TSV 应 62 条, 实得 %d" % len(rows)
    return rows

def scan_all_v16():
    wb, mp, char_forced, char_files, freq = v15.scan_all()
    n0 = len(char_files)
    for r in SYS_ROWS:
        t = r["tgt"]
        i = 0
        saved = cur = 0
        while i < len(t):
            m = color_re.match(t, i)
            if m:
                xx = int(m.group(1), 16) & 0x3F
                saved, cur = cur, xx
                i = m.end(); continue
            if t[i:i+4] == "{/色}":
                cur = saved; i += 4; continue
            m2 = code_re.match(t, i)
            if m2:
                i = m2.end(); continue
            if t[i] == "\n":
                i += 1; continue
            if t[i:i+3] == "---":
                i += 3; continue
            ch = t[i]
            if ord(ch) > 0x7E and ch not in SYM:
                fs = v15.win_to_set(cur)
                if fs is not None:
                    char_forced[ch].add(fs)
                char_files[ch].add(DEMO)
                freq[ch] += 1
            i += 1
    print("  [sys] 62 条并入扫描: 新增用字 %d" % (len(char_files) - n0))
    return wb, mp, char_forced, char_files, freq

def allocate_v16(must_set0):
    """v16d 分配 = v15 分配结果原样复制 + DEMO 专属字入附加段 (池复制架构)。

    理由:
      - v15 全局池/场景区已被实测验证, 原样保持
      - 池复制架构: seg4 槽 0-329 = 全局池复制, DEMO 专属字 (池外套 0 字)
        槽 G.. -> DEMO 卸载后其他系统界面读槽 0-329 与 INIT 完全一致, 零污染
      - v16c 实证: 花屏根因 = INIT CLUT rewrite; 三版 seg4 (32768/28672/无)
        花屏完全一致 -> seg4 尺寸非花屏因素, 32768B (场景字库同款) 待实测
    """
    v15alloc = json.load(open(V15_ALLOC, encoding="utf-8"))
    gsets = {int(k): dict(v) for k, v in v15alloc["global"].items()}
    scene = {f: {int(k): dict(v) for k, v in ssets.items()}
             for f, ssets in v15alloc["scene"].items()}

    # demo_only: 62 条用字中不在全局池套 0 的字 -> 附加段槽 G.. (套 0)
    demo_chars = sorted(ch for ch in must_set0 if ch not in gsets[0])
    seg4_cap = glyph_capacity(DEMO_SEG4_SIZE)
    if len(gsets[0]) + len(demo_chars) > seg4_cap:
        raise RuntimeError("seg4 容量不足: %d+%d > %d" % (
            len(gsets[0]), len(demo_chars), seg4_cap))
    sd = scene.setdefault(DEMO, {0: {}, 1: {}, 2: {}, 3: {}})
    for idx, ch in enumerate(demo_chars):
        sd[0][ch] = G + idx      # 槽 G.., 池复制基准

    # main_slot 重算 (池内字)
    main_slot = {}
    for ch in set(sum((list(v.keys()) for v in gsets.values()), [])):
        cand = [(s, gsets[s][ch]) for s in range(4) if ch in gsets[s]]
        if cand:
            main_slot[ch] = ("global",) + min(cand)

    alloc = {
        "global": {str(k): gsets[k] for k in range(4)},
        "scene": {f: {str(k): ssets[k] for k in range(4)} for f, ssets in scene.items()},
        "demo_only": sorted(demo_chars),
        "stats": {
            "per_set": {str(k): len(gsets[k]) for k in range(4)},
            "scene_files": sum(1 for f in scene if any(scene[f][k] for k in range(4))),
            "demo_extra": len(demo_chars),
        },
    }
    return alloc, gsets, scene, main_slot, demo_chars

# ============================================================
# 2. 系统文本编码器 (DEMO.EMI seg2 专用)
# ============================================================

def encode_sys(tgt, g0, demo_s0):
    """系统文本块编码: 符号表 + ASCII 单字节 + 汉字主字库套 0/DEMO 附加段 + 控制码。
    不插入套切换码 (系统界面无变色需求, 全部套 0 语义)。"""
    out = bytearray()
    i = 0
    while i < len(tgt):
        ch = tgt[i]
        if ch == "{":
            j = tgt.find("}", i)
            if j > 0:
                name = tgt[i+1:j]
                if name.startswith("色") and len(name) == 3:
                    out += bytes((0x05, int(name[1:], 16)))
                elif name == "/色":
                    out.append(0x06)
                else:
                    matched = False
                    if " " in name:
                        n0, param = name.split(" ", 1)
                    else:
                        n0, param = name, ""
                    byte = None
                    for cand in sorted(CTRL_CODES, key=len, reverse=True):
                        if n0.startswith(cand):
                            byte = CTRL_CODES[cand]; break
                    if byte is None:
                        raise ValueError("unknown ctrl {%s}" % name)
                    out.append(byte)
                    plen = CTRL_LEN.get(byte, 1) - 1
                    if plen > 0:
                        for k in range(0, len(param), 2):
                            try:
                                out.append(int(param[k:k+2], 16))
                            except ValueError:
                                out.append(ord(param[k]) if k < len(param) else 0)
                    elif param:
                        raise ValueError("ctrl {%s} 不带参数但译文给了" % name)
                i = j + 1
                continue
        if ch == "\n":
            out.append(0x01); i += 1; continue
        if tgt[i:i+3] == "---":
            out.append(0x02); i += 3; continue
        if ch in SYM:
            out += SYM[ch]; i += 1; continue
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            out.append(cp); i += 1; continue
        # 汉字: 必须在套 0 (全局池) 或 DEMO 附加段套 0
        slot = None
        if ch in g0:
            slot = g0[ch]
        elif ch in demo_s0:
            slot = demo_s0[ch]
        if slot is None:
            raise ValueError("系统文本字不在套 0/DEMO 段: %r (%s)" % (ch, tgt[:20]))
        out += bytes((0x13, slot - 256)) if slot >= 256 else bytes((0x12, slot))
        i += 1
    return bytes(out)

# ============================================================
# 3. seg2 结构解析与重组
# ============================================================

def parse_seg2(D, size):
    tbl = [struct.unpack_from("<H", D, i * 2)[0] for i in range(256)]
    assert tbl[0] == 512, "表首项应 0x200, 实 0x%X" % tbl[0]
    # 单调检查
    for i in range(255):
        assert tbl[i] <= tbl[i+1], "表非单调 @%d" % i
    spans = []
    for i in range(256):
        end = tbl[i+1] if i < 255 else size
        spans.append(D[tbl[i]:end])
    return tbl, spans

def _walk_dangling(buf, start, length):
    """CTRL_LEN 感知遍历 buf[start:start+length], 返回尾部悬空控制码信息。
    返回 (opcode, missing): 尾部启动了控制码但参数不足; 无悬空返回 (None, 0)。"""
    i = 0
    while i < length:
        b = buf[start + i]
        if b < 0x21:
            need = CTRL_LEN.get(b, 1)
            if i + need > length:
                return b, need - (length - i)
            i += need
        else:
            i += 1
    return None, 0

def slot_page_map(tbl, spans, rows, seg_base):
    """TSV 62 条 -> (槽 i, 页 pi) -> 合并译文 映射。

    关键: TSV 是按"裸 0x00"切块的提取产物, 控制码参数中的 0x00
    (如 0x15 图标码参数) 会被误切成块边界。本函数按 CTRL_LEN 感知
    的 split_pages 定位真页, 组内多条 TSV 译文按序合并, 悬空控制码
    补齐还原为 {符号2 XX} 等标记插入拼接点。
    """
    mapping = {}
    rows_sorted = sorted(rows, key=lambda r: int(r["offset"]))
    n_merged = 0
    for i in range(256):
        raw = spans[i]
        base = tbl[i]
        pages = split_pages(raw)
        acc = base
        for pi, pg in enumerate(pages):
            if len(pg) == 0:
                # split_pages 尾部存储空位 (raw 以 00 结尾), 跳过匹配但保留重组
                acc += len(pg) + 1
                continue
            p_start, p_end = acc, acc + len(pg)
            grp = [r for r in rows_sorted
                   if p_start <= int(r["offset"]) - seg_base <= p_end]
            if grp:
                merged = ""
                for k, r in enumerate(grp):
                    r_rel = int(r["offset"]) - seg_base
                    hl = int(r["hex_len"])
                    merged += r["tgt"]
                    if k + 1 < len(grp):
                        # 与下一 TSV 条目之间: 悬空控制码 + 补齐字节
                        op, miss = _walk_dangling(pg, r_rel - p_start, hl)
                        if op is None:
                            # 无悬空: 中间 gap 字节应为空 (同页连续条目)
                            nxt = int(grp[k+1]["offset"]) - seg_base
                            gap = (r_rel + hl) - nxt if False else nxt - (r_rel + hl)
                            if gap != 0:
                                raise RuntimeError(
                                    "页 %d/%d: %s 与 %s 间 gap %d B 且无悬空控制码"
                                    % (i, pi, r["id"], grp[k+1]["id"], gap))
                            continue
                        # 悬空控制码: 补齐字节 = 真块内 hex_len 之后的 miss 字节
                        fill = pg[r_rel - p_start + hl: r_rel - p_start + hl + miss]
                        if len(fill) < miss:
                            raise RuntimeError("页 %d/%d: %s 悬空补齐越界" % (i, pi, r["id"]))
                        if op == 0x15:
                            # 图标码 (决定键 ○ 等), 语义必须保留
                            merged += "{符号2 %02X}" % fill[0]
                        elif op == 0x12 and fill[0] == 0x00:
                            # 主字库槽 0 引用 (sys_011/012 拼接处, 原文
                            # 'ゲーム'+[0x12 00]+'にセーブを' 的连接装饰),
                            # 中译文语义完整, 安全丢弃
                            pass
                        else:
                            raise RuntimeError(
                                "页 %d/%d: %s 悬空 op=%02X fill=%s 需人工审查"
                                % (i, pi, r["id"], op, fill.hex()))
                        n_merged += 1
                mapping[(i, pi)] = merged
            acc += len(pg) + 1
    print("  [map] 合并悬空切分组: %d 处" % n_merged)
    return mapping

def rebuild_seg2(tbl, spans, mapping, g0, demo_s0):
    """重组 seg2: 映射页替换译文, 其余页原样; 返回新段数据 + 审计信息。"""
    new_spans = []
    audit = {"replaced": 0, "kept_pages": 0, "shared_slots": 0}
    old2new = {}
    for i in range(256):
        pages = split_pages(spans[i])
        new_pages = []
        replaced_in_slot = 0
        for pi, pg in enumerate(pages):
            key = (i, pi)
            if key in mapping:
                enc = encode_sys(mapping[key], g0, demo_s0)
                new_pages.append(enc)
                audit["replaced"] += 1
                replaced_in_slot += 1
            else:
                new_pages.append(pg)
                audit["kept_pages"] += 1
        if replaced_in_slot > 1:
            audit["shared_slots"] += 1
        new_spans.append(b"\x00".join(new_pages))
        old2new[i] = (spans[i], new_spans[i])
    # 新表 (512B) + 数据区
    body = bytearray()
    new_tbl = [0] * 256
    for i in range(256):
        new_tbl[i] = 512 + len(body)
        body += new_spans[i]
    total = 512 + len(body)
    if total > 4096:
        raise RuntimeError("seg2 重组超 padded: %d > 4096" % total)
    out = bytearray(512)
    struct.pack_into("<256H", out, 0, *new_tbl)
    out += body
    return bytes(out), new_tbl, audit, old2new

# ============================================================
# 4. 主流程 (v15 流程 + seg2 注入)
# ============================================================

def main():
    global SYS_ROWS
    SYS_ROWS = load_sys_tsv()
    print("=" * 64)
    print("BOF4 v16e 全量构建: v16d + 系统文字 白芯V9/暗边V1 + INIT win0[9] 白化")
    print("=" * 64)

    fsr = json.load(open(REPO + r"\data\font_segments_report.json", encoding="utf-8"))["segments"]
    cap_of = {}
    for f, segs in fsr.items():
        cap_of[f.upper()] = glyph_capacity(segs[0]["size"])

    print("[1/7] 扫描译文 (含 62 条系统文本)...")
    wb, mp, char_forced, char_files, freq = scan_all_v16()
    print("  唯一字 %d, 强制套 %d" % (len(char_files), len(char_forced)))

    must_set0 = set()
    for r in SYS_ROWS:
        t = r["tgt"]; i = 0
        while i < len(t):
            m = code_re.match(t, i)
            if m:
                i = m.end(); continue
            if t[i:i+3] == "---":
                i += 3; continue
            ch = t[i]
            if ch != "\n" and ord(ch) > 0x7E and ch not in SYM:
                must_set0.add(ch)
            i += 1
    print("  强制套 0 用字: %d (符号走图标码/单字节, 不占槽)" % len(must_set0))

    print("[2/7] 字库分配 (v15 复制 + DEMO 附加段)...")
    alloc, gsets, scene, main_slot, demo_only = allocate_v16(must_set0)
    print("  全局槽: %s (v15 保持)" % alloc["stats"]["per_set"])
    print("  场景文件: %d, DEMO 附加段: %d 字" % (
        alloc["stats"]["scene_files"], alloc["stats"]["demo_extra"]))
    json.dump(alloc, open(REPO + r"\data\font_alloc_4set_v16.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("[3/7] 渲染字形 (%d 字)..." % len(char_files))
    mats = v15.render_1bpp(set(char_files), v15.FONT)
    g_packed, s_packed = pack_all(mats, gsets, scene)
    g_sys, s_sys = pack_sys(mats, gsets, scene)
    print("  渲染完成, 全局槽 %d, 场景文件 %d, 系统打包 %d" % (
        len(g_packed), len(s_packed), len(g_sys)))

    print("[4/7] 编码全部文本...")
    wb_by = defaultdict(list)
    for it in wb:
        wb_by[(it["file"].upper(), str(it["seg"]))].append(it)
    encoded = {}
    enc_err = []
    for key, items in wb_by.items():
        lst = []
        for it in items:
            tgt = it.get("tgt", "")
            if not tgt:
                lst.append("")
                continue
            try:
                lst.append(v15.encode_v15(tgt, key[0], gsets, scene, main_slot).hex())
            except ValueError as exc:
                enc_err.append(str(exc))
        encoded[key] = lst
    extra_by = defaultdict(dict)
    for e in mp:
        f = e["file"].upper()
        key = (f, str(e["seg"]))
        pages = e.get("pages", {})
        max_p = max(int(p) for p in pages) if pages else 1
        hex_list = [""] * max(0, max_p - 1)
        for pno, tgt in pages.items():
            pi = int(pno)
            if pi < 2 or not tgt:
                continue
            try:
                hex_list[pi - 2] = v15.encode_v15(tgt, f, gsets, scene, main_slot).hex()
            except ValueError as exc:
                enc_err.append(str(exc))
        extra_by[key][int(e["slot"])] = hex_list
    if enc_err:
        print("  编码错误 %d:" % len(enc_err))
        for e in enc_err[:15]:
            print("   ", e)
        raise RuntimeError("编码失败")
    n_enc = sum(1 for lst in encoded.values() for h in lst if h)
    print("  编码 %d 条非空 + 多页 %d 槽" % (n_enc, sum(len(v) for v in extra_by.values())))

    print("[5/7] seg2 系统文本重组...")
    iso0 = open(ISO, "rb").read()
    files0 = {n.upper(): (l, s) for n, l, s in list_iso_files(iso0)}
    lba0, size0 = files0[DEMO]
    parsed0 = parse_emi(read_file_from_iso(iso0, lba0, size0))
    seg2 = [s for s in parsed0["segments"] if s["sig"] == SEG2_SIG][0]
    tbl, spans = parse_seg2(seg2["data"], seg2["size"])
    mapping = slot_page_map(tbl, spans, SYS_ROWS, seg2["offset"])
    print("  62 条 -> (槽,页) 映射 %d 项" % len(mapping))
    new_seg2, new_tbl, audit, old2new = rebuild_seg2(
        tbl, spans, mapping, gsets[0], scene.get(DEMO, {}).get(0, {}))
    print("  替换页 %d (含共享槽 %d 个), 保留页 %d" % (
        audit["replaced"], audit["shared_slots"], audit["kept_pages"]))
    print("  seg2: %d -> %d B (padded 4096)" % (seg2["size"], len(new_seg2)))
    # 审计: 长度变化明细
    n_grow = sum(1 for i in range(256) if len(old2new[i][1]) > len(old2new[i][0]))
    n_shrink = sum(1 for i in range(256) if len(old2new[i][1]) < len(old2new[i][0]))
    print("  槽增长 %d, 缩短 %d, 持平 %d" % (n_grow, n_shrink, 256 - n_grow - n_shrink))

    print("[6/7] 写入镜像...")
    iso = bytearray(open(ISO, "rb").read())
    files = {n.upper(): (l, s) for n, l, s in list_iso_files(bytes(iso))}
    orig_files = dict(files)
    emi_replacements = defaultdict(dict)
    in_place = 0
    n_clut = 0
    n_font = 0
    n_moved = 0
    n_moved = 0
    n_moved = 0

    for name in sorted(files):
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        lba, size = files[name]
        emi_buf = bytearray(read_file_from_iso(bytes(iso), lba, size))
        parsed = parse_emi(bytes(emi_buf))
        if parsed is None:
            continue

        # v16d: DEMO 整文件重建 (seg2 替换 + 追加 seg4 池复制字库段), 需扩容搬移
        if name == DEMO:
            seg4 = bytearray(DEMO_SEG4_SIZE)
            for i, g in g_sys.items():
                set_glyph(seg4, i, g)
            for i, g in s_sys.get(name, {}).items():
                set_glyph(seg4, i, g)
            res = write_emi_to_iso(iso, name, build_demo_emi(
                emi_buf, parsed, new_seg2, bytes(seg4)))
            if res["moved"]:
                n_moved += 1
            in_place += 1
            continue

        seg_final = {}
        has_overflow = False

        for seg in parsed["segments"]:
            sig = seg["sig"]
            # v16c: SYSTEM/* 的 CLUT 保留原版 (系统界面图形调色板, rewrite 会
            # 破坏立绘/标题/窗口图形)
            # v16e: 例外 = INIT 三个块 win0[9] 白化 7FFF (系统文字字芯纯白)。
            # [8]=面板底色绝不能动; [9] v16 时代已被白化且命名 UI 无恙 (实证)。
            if name.startswith("SYSTEM/"):
                if (name == "SYSTEM/INIT.EMI" and seg["size"] == 512
                        and 0x8002E000 <= sig <= 0x8004E000):
                    d = bytearray(seg["data"])
                    struct.pack_into("<H", d, 18, 0x7FFF)
                    seg_final[seg["index"]] = bytes(d)
                    n_clut += 1
                continue
            if 0x8002E000 <= sig <= 0x8004E000 and seg["size"] == 512:
                seg_final[seg["index"]] = v15.rewrite_clut(seg["data"])
                n_clut += 1

        fsegs = find_font_segments(parsed)
        if fsegs:
            fseg = fsegs[0]
            fdata = bytearray(fseg["data"])
            # v16d: SYSTEM 字库用系统专用打包 (V=8 字芯), WORLD 保持 4 套打包
            if name.startswith("SYSTEM/"):
                gsrc, ssrc = g_sys, s_sys
            else:
                gsrc, ssrc = g_packed, s_packed
            for i, g in gsrc.items():
                set_glyph(fdata, i, g)
            for i, g in ssrc.get(name, {}).items():
                set_glyph(fdata, i, g)
            seg_final[fseg["index"]] = bytes(fdata)
            n_font += 1

        for seg in parsed["segments"]:
            vals = is_text_segment(seg["data"])
            if vals is None:
                continue
            key = (name, str(seg["index"] + 1))
            if key not in encoded:
                continue
            new_seg = build_text_segment(seg["data"], vals, encoded[key],
                                         extra_pages=extra_by.get(key))
            seg_final[seg["index"]] = new_seg

        for si, data in seg_final.items():
            if len(data) > parsed["segments"][si]["padded_size"]:
                has_overflow = True
                break
        if has_overflow:
            emi_replacements[name] = seg_final
        else:
            for si, data in seg_final.items():
                v15.patch_emi_segment(emi_buf, parsed, si, data)
            if seg_final:
                write_file_to_iso(iso, lba, bytes(emi_buf), size)
                in_place += 1

    print("  CLUT 段: %d, 字库段: %d, 原地写入: %d, DEMO 重建搬移: %d" % (
        n_clut, n_font, in_place, n_moved))

    if emi_replacements:
        print("  扩容段: %d 个文件..." % len(emi_replacements))
        moved = 0
        for name, reps in emi_replacements.items():
            res = expand_emi_in_iso(iso, name, reps)
            if res["moved"]:
                moved += 1
        print("  搬移: %d" % moved)

    new_files = {n.upper(): (l, s) for n, l, s in list_iso_files(bytes(iso))}
    v15.sync_exe_lba_table(iso, orig_files, new_files)

    print("[7/7] 保存...")
    with open(OUT, "wb") as f:
        f.write(bytes(iso))
    print("output: %s" % OUT)
    print("size: %d (orig %d)" % (len(iso), os.path.getsize(ISO)))
    print("sha256: %s" % hashlib.sha256(bytes(iso)).hexdigest())

def build_demo_emi(emi_buf, parsed, seg2_data, font_data):
    """DEMO.EMI 专用重建: 替换 seg2 + 追加字库段 (index 4, sig=0x1C000200)。
    段表 count 4 -> 5, 头部同步; 布局逻辑与 rebuild_emi 一致 (0x800 段表区,
    段数据 2048 对齐)。

    崩溃教训 (v16 首版实证): 段表 entry 的后 8 字节不是"保留", 是段类型
    配置参数。全游戏 296 个字库段实测均为 00 00 10 08 03 00 2e 2e;
    新段 entry 必须照抄标准配置, 否则游戏读段表即崩。
    """
    SEG_META = {
        0x1C000200: bytes.fromhex("0000100803002e2e"),   # 字库段标准配置
    }
    segs = []
    for s in parsed["segments"]:
        d = s["data"]
        if s["index"] == 2:
            d = seg2_data
        segs.append((s["sig"], d))
    n_orig = len(parsed["segments"])
    segs.append((FONT_SEG_SIG, font_data))

    header = bytearray(emi_buf[:0x10])
    struct.pack_into("<H", header, 0, len(segs))
    out = bytearray()
    out += header
    for i, (sig, data) in enumerate(segs):
        entry = bytearray(16)
        if i < n_orig:
            # 原有段: entry 原样保留 (含原版配置参数)
            entry = bytearray(emi_buf[0x10 + i * 16: 0x10 + i * 16 + 16])
        else:
            # 追加的新段: 按段类型填标准配置
            meta = SEG_META.get(sig)
            if meta is None:
                raise ValueError("追加段 sig=%08X 无标准配置, 需人工确认" % sig)
            entry[8:16] = meta
        struct.pack_into("<I", entry, 0, len(data))
        struct.pack_into("<I", entry, 4, sig)
        out += entry
    if len(out) > 0x800:
        raise ValueError("段表区域超过 0x800")
    out += b"\x00" * (0x800 - len(out))
    for sig, data in segs:
        pad = (-len(out)) % DSZ
        out += b"\x00" * pad
        out += data
    return bytes(out)

def pack_all(mats, gsets, scene):
    inv_g = [{v: k for k, v in gsets[k].items()} for k in range(4)]
    gcap_max = max(len(gsets[k]) for k in range(4))
    g_packed = {}
    for i in range(gcap_max):
        four = [mats.get(inv_g[k].get(i)) for k in range(4)]
        if all(m is None for m in four):
            continue
        g_packed[i] = v15.pack_four(four)
    s_packed = {}
    for f, ssets in scene.items():
        inv_s = [{v: k for k, v in ssets[k].items()} for k in range(4)]
        smax = max(len(ssets[k]) for k in range(4))
        if smax == 0:
            s_packed[f] = {}
            continue
        # v16d 池复制架构: 所有场景段槽位均带 G 偏移 (DEMO 附加段同基准)
        base = G
        d = {}
        for j in range(smax):
            four = [mats.get(inv_s[k].get(j + base)) for k in range(4)]
            if all(m is None for m in four):
                continue
            d[j + base] = v15.pack_four(four)
        s_packed[f] = d
    return g_packed, s_packed

def ring8_of(m):
    """12x12 矩阵的 8 邻域膨胀环 (不含芯), 与原版描边结构 80.9% 吻合。"""
    core = [[1 if m[r][c] else 0 for c in range(12)] for r in range(12)]
    ring = [[0] * 12 for _ in range(12)]
    for r in range(12):
        for c in range(12):
            if core[r][c]:
                continue
            hit = False
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < 12 and 0 <= cc < 12 and core[rr][cc]:
                        hit = True
            ring[r][c] = 1 if hit else 0
    return ring

def sys_pack_glyph(m):
    """系统字库单字打包: 描边 -> V=1 (bit0), 字芯 -> V=9 (bit0+bit3)。

    颜色语义 (INIT seg1 win0 实证): [1]=(7,7,7) 暗描边 (原版不动),
    [9] 白化 7FFF = 纯白字芯。白芯+暗边浅底/深底双可读 (outline_test2)。
    """
    ring = ring8_of(m)
    both = [[1 if (m[r][c] or ring[r][c]) else 0 for c in range(12)] for r in range(12)]
    return v15.pack_four([both, None, None, m])

def pack_sys(mats, gsets, scene):
    """系统字库专用打包: 暗描边 V=1 + 白字芯 V=9 (见 sys_pack_glyph)。"""
    g_sys = {}
    for slot, ch in {v: k for k, v in gsets[0].items()}.items():
        m = mats.get(ch)
        if m is None:
            continue
        g_sys[slot] = sys_pack_glyph(m)
    s_sys = {}
    for f, ssets in scene.items():
        d = {}
        for slot, ch in {v: k for k, v in ssets[0].items()}.items():
            m = mats.get(ch)
            if m is None:
                continue
            d[slot] = sys_pack_glyph(m)
        if d:
            s_sys[f] = d
    return g_sys, s_sys

if __name__ == "__main__":
    main()
