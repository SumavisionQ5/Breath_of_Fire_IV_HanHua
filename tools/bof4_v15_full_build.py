# -*- coding: utf-8 -*-
"""v15 全量汉化镜像构建: 4 套 1bpp CLUT 分页 (正式版)。

架构:
  - 全局池: 330 物理 x 4 套 = 1,320 虚拟槽 (系统字全装 + 高频跨文件字)
  - 场景区: 每文件 (cap-330) x 4 套 (该文件独有字, 跨文件重复占槽)
  - 强制套: 原生色码区间字固定套 ({色01}->1 {色02}->2 {色03}->3 {色04+}->0)
  - 套切换码: 原版未用窗口 {色09}(套1) {色0B}(套2) {色0C}(套3) {色00}(套0)
    -> 原生变色 100% 保留; 0x05 单层保存槽与外侧切换天然兼容 (逆向实证)
  - CLUT: 每文本场景条目 win0/4-8/A/D 原版渐变保留+套位主色,
          win1-3 原版保留+套位主色, win9/B/C 纯套白窗口
  - 文本: v0.8 页级 build_text_segment + extra_pages; 超限段 emi_expand
"""
import json, re, sys, os, struct, hashlib
from collections import Counter, defaultdict

REPO = r"D:\龙战士\bof4-chinese\Breath_of_Fire_IV_HanHua"
sys.path.insert(0, REPO + r"\tools\lib")
sys.path.insert(0, REPO + r"\tools")

from bof4lib import (CTRL_CODES, CTRL_LEN, parse_emi, find_font_segments,
                     is_text_segment, list_iso_files, read_file_from_iso,
                     write_file_to_iso, set_glyph, get_glyph, GLYPH_SIZE,
                     trim, split_pages, build_text_segment, glyph_capacity)
from emi_expand import expand_emi_in_iso

ISO = r"D:\龙战士\Breath of Fire IV - Utsurowazaru Mono (Japan).bin"
OUT = r"D:\龙战士\bof4_chinese_v15.bin"
WB = REPO + r"\translation_workbook.json"
MP = REPO + r"\data\multi_page_translations.json"
FSR = REPO + r"\data\font_segments_report.json"
ALLOC_OUT = REPO + r"\data\font_alloc_4set.json"
FONT = r"C:\Windows\Fonts\simsun.ttc"

G = 330
WHITE = 0x7FFF
SWITCH_WIN = {1: 0x09, 2: 0x0B, 3: 0x0C}    # 套 -> {色XX} 参数
NATIVE_WINS = {1, 2, 3, 4, 5, 6, 7, 8, 0xA, 0xD, 0x3C}

code_re = re.compile(r"\{([^}]*)\}")
color_re = re.compile(r"\{色([0-9A-Fa-f]{2})\}")

def win_to_set(win):
    if win in (1, 2, 3):
        return win
    if win in (4, 5, 6, 7, 8, 0xA, 0xD, 0x3C):
        return 0
    return None

# ============================================================
# 1. 扫描: 强制套 / 文件用字 / 频率
# ============================================================

def scan_all():
    wb = json.load(open(WB, encoding="utf-8"))
    mp = json.load(open(MP, encoding="utf-8"))
    entries = []
    for it in wb:
        entries.append((it["file"].upper(), it.get("seg"), it.get("tgt", "")))
    for e in mp:
        for pno, tgt in e.get("pages", {}).items():
            if tgt:
                entries.append((e["file"].upper(), e.get("seg"), tgt))

    char_forced = defaultdict(set)
    char_files = defaultdict(set)
    freq = Counter()
    for f, seg, t in entries:
        saved = 0
        cur = 0
        i = 0
        while i < len(t):
            m = color_re.match(t, i)
            if m:
                xx = int(m.group(1), 16) & 0x3F
                saved = cur
                cur = xx
                i = m.end(); continue
            if t[i:i+4] == "{/色}":
                cur = saved
                i += 4; continue
            m2 = code_re.match(t, i)
            if m2:
                i = m2.end(); continue
            if t[i] == "\n":
                i += 1; continue
            if t[i:i+3] == "---":
                i += 3; continue
            ch = t[i]
            if ord(ch) > 0x7E:
                fs = win_to_set(cur)
                if fs is not None:
                    char_forced[ch].add(fs)
                char_files[ch].add(f)
                freq[ch] += 1
            i += 1
    return wb, mp, char_forced, char_files, freq

# ============================================================
# 2. 分配
# ============================================================

def allocate(char_forced, char_files, freq, cap_of):
    no_font = set(f for f in set().union(*char_files.values()) if f not in cap_of)
    sys_chars = set(ch for ch, fl in char_files.items() if fl & no_font)
    nfiles = {ch: len(fl) for ch, fl in char_files.items()}

    gsets = {k: {} for k in range(4)}       # 套 -> {char: slot}
    def put_global(ch, s):
        if len(gsets[s]) >= G:
            return False
        if ch in gsets[s]:
            return True
        gsets[s][ch] = len(gsets[s])
        return True

    # a. 系统强制字 -> 对应套
    fail = []
    for ch in sorted(sys_chars & set(char_forced)):
        for s in char_forced[ch]:
            if not put_global(ch, s):
                fail.append((ch, s))
    if fail:
        raise RuntimeError("系统强制字装不下: %s" % fail[:10])

    # b. 系统非强制字 -> 套 0 优先溢出 1/3/2
    for ch in sorted(sys_chars - set(char_forced), key=lambda c: -freq[c]):
        for s in (0, 1, 3, 2):
            if put_global(ch, s):
                break
        else:
            raise RuntimeError("系统字溢出: %r" % ch)

    # c. 剩余全局槽 -> 跨文件字按 (文件数, 频率) 贪心
    #    强制字只入强制套 (不 fallback, 缺口由场景区补)
    cross = [ch for ch in char_files
             if nfiles[ch] >= 2 and ch not in sys_chars]
    cross.sort(key=lambda c: (-nfiles[c], -freq[c]))
    for ch in cross:
        placed_any = False
        # 强制套优先 (全部满足才算了结; 部分满足也保留)
        for s in sorted(char_forced.get(ch, set())):
            if put_global(ch, s):
                placed_any = True
        if ch in gsets and any(ch in gsets[s] for s in range(4)):
            placed_any = True
        if not placed_any and ch not in char_forced:
            for s in (0, 1, 3, 2):
                if put_global(ch, s):
                    placed_any = True
                    break
        if not placed_any and not any(ch in gsets[s] for s in range(4)):
            continue    # 全局无位, 场景区解决

    global_chars = set()
    for k in range(4):
        global_chars |= set(gsets[k])

    # d. 场景区: 补两类缺口
    #    1) 强制套缺口: ch 在该文件需要套 s, 但全局套 s 没有且未在本文件场景套 s
    #    2) 主套缺口: ch 无任何全局槽 (单文件字 / 全局没挤进的跨文件字)
    scene = {}    # file -> {set: {char: slot}}
    scene_fail = []
    for f in sorted(set(cap_of)):
        fchars = [ch for ch, fl in char_files.items() if f in fl]
        ssets = {k: {} for k in range(4)}
        cap = cap_of[f]
        scen = cap - G
        need_forced = {}     # ch -> set(缺的强制套)
        need_free = []       # 无全局槽的字
        for ch in fchars:
            g_have = {s for s in range(4) if ch in gsets[s]}
            forced = char_forced.get(ch, set())
            missing = forced - g_have
            if missing:
                need_forced[ch] = missing
            if not g_have:
                need_free.append(ch)
        # 强制缺口 -> 对应套
        for ch in sorted(need_forced):
            for s in need_forced[ch]:
                if len(ssets[s]) >= scen:
                    scene_fail.append((f, ch, s))
                elif ch not in ssets[s]:
                    ssets[s][ch] = G + len(ssets[s])
        # 自由字轮转
        need_free.sort(key=lambda c: -freq[c])
        k = 0
        for ch in need_free:
            placed = False
            for _ in range(4):
                if len(ssets[k]) < scen:
                    ssets[k][ch] = G + len(ssets[k])
                    placed = True
                    break
                k = (k + 1) % 4
            if not placed:
                scene_fail.append((f, ch, "free"))
                break
        scene[f] = ssets
    if scene_fail:
        raise RuntimeError("场景区超限: %s (共 %d)" % (scene_fail[:6], len(scene_fail)))

    # 主套表 (普通上下文用): char -> 全局或每文件场景 (set, slot)
    # 优先全局 (任意套, 取其最小套), 否则该文件场景最小套
    main_slot = {}
    for ch in char_files:
        cand = [(s, gsets[s][ch]) for s in range(4) if ch in gsets[s]]
        if cand:
            main_slot[ch] = ("global",) + min(cand)
        # 场景的在编码时按文件查

    alloc = {
        "global": {str(k): v for k, v in ((k, gsets[k]) for k in range(4))},
        "scene": {f: {str(k): v for k, v in ssets.items()} for f, ssets in scene.items()},
        "stats": {
            "unique_chars": len(char_files),
            "forced_chars": len(char_forced),
            "global_slots": sum(len(gsets[k]) for k in range(4)),
            "per_set": {str(k): len(gsets[k]) for k in range(4)},
            "scene_files": sum(1 for f in scene if any(scene[f][k] for k in range(4))),
        },
    }
    return alloc, gsets, scene, main_slot

# ============================================================
# 3. 字形渲染 (1bpp 无描边) + 4 套打包
# ============================================================

def render_1bpp(chars, font_path, size=12, threshold=96):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, size)
    mats = {}
    for ch in chars:
        img = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(img)
        try:
            bbox = font.getbbox(ch)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x, y = (size - w) // 2 - bbox[0], (size - h) // 2 - bbox[1]
        except Exception:
            x, y = 0, 0
        draw.text((x, y), ch, fill=255, font=font)
        mats[ch] = [[1 if img.getpixel((c, r)) >= threshold else 0
                     for c in range(size)] for r in range(size)]
    return mats

def pack_four(ml, size=12):
    data = bytearray()
    for r in range(size):
        row = []
        for c in range(size):
            idx = 0
            for k, m in enumerate(ml):
                if m is not None and m[r][c]:
                    idx |= 1 << k
            row.append(idx & 0xF)
        for c in range(0, size, 2):
            data.append((row[c] & 0xF) | ((row[c + 1] & 0xF) << 4))  # 低 nibble 左
    return bytes(data)

# ============================================================
# 4. 编码器 (栈/单层槽模拟 + 套切换 + ASCII 保护)
# ============================================================

def encode_v15(text, fname, gsets, scene, main_slot):
    """编码单页文本。返回 bytes。违规立即 raise。"""
    out = bytearray()
    saved = 0
    cur = 0          # 当前窗口
    i = 0
    # 字符 -> (set, slot) 解析: 全局优先, 场景次之
    def lookup(ch, s):
        if ch in gsets[s]:
            return gsets[s][ch]
        ss = scene.get(fname, {}).get(s, {})
        if ch in ss:
            return ss[ch]
        return None
    while i < len(text):
        ch = text[i]
        m = color_re.match(text, i)
        if m:
            xx = int(m.group(1), 16) & 0x3F
            out += bytes((0x05, xx))
            saved = cur
            cur = xx
            i = m.end(); continue
        if text[i:i+4] == "{/色}":
            out.append(0x06)
            cur = saved
            i += 4; continue
        m2 = code_re.match(text, i)
        if m2:
            name = m2.group(1)
            if " " in name:
                name0, param = name.split(" ", 1)
            else:
                name0, param = name, ""
            byte = None
            for cand in sorted(CTRL_CODES, key=len, reverse=True):
                if name0.startswith(cand):
                    byte = CTRL_CODES[cand]; break
            if byte is None:
                raise ValueError("unknown ctrl {%s} in %s" % (name, fname))
            out.append(byte)
            plen = CTRL_LEN.get(byte, 1) - 1
            if plen > 0:
                for k in range(0, len(param), 2):
                    try:
                        out.append(int(param[k:k+2], 16))
                    except ValueError:
                        out.append(ord(param[k]) if k < len(param) else 0)
            i = m2.end(); continue
        if ch == "\n":
            out.append(0x01); i += 1; continue
        if text[i:i+3] == "---":
            out.append(0x02); i += 3; continue
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            # ASCII: 必须在窗口 0 或原生窗口下输出 (切换窗口会丢灰度)
            if cur not in ({0} | NATIVE_WINS):
                out += bytes((0x05, 0x00))
                saved = cur
                cur = 0
            out.append(cp)
            i += 1; continue
        # 汉字
        if cur in NATIVE_WINS:
            fs = win_to_set(cur)
            slot = lookup(ch, fs)
            if slot is None:
                raise ValueError("强制套缺失: %r win=%02X file=%s" % (ch, cur, fname))
        else:
            # 窗口 0 或切换窗口: 用当前套 (若已有) 或主套
            cur_set = None
            for s in range(4):
                if SWITCH_WIN.get(s) == cur:
                    cur_set = s; break
            if cur_set is None:
                cur_set = 0 if cur == 0 else None
            slot = None
            if cur_set is not None:
                slot = lookup(ch, cur_set)
            if slot is None:
                # 主套 + 切换
                if ch in main_slot and main_slot[ch][0] == "global":
                    ms, mslot = main_slot[ch][1], main_slot[ch][2]
                else:
                    # 场景主套: 该文件任一套
                    ms, mslot = None, None
                    for s in range(4):
                        v = lookup(ch, s)
                        if v is not None:
                            ms, mslot = s, v; break
                    if ms is None:
                        raise ValueError("unmapped char %r in %s" % (ch, fname))
                if ms != cur_set:
                    out += bytes((0x05, SWITCH_WIN.get(ms, 0x00)))
                    saved = cur
                    cur = SWITCH_WIN.get(ms, 0x00)
                slot = mslot
        if slot >= 256:
            out += bytes((0x13, slot - 256))
        else:
            out += bytes((0x12, slot))
        i += 1
    return bytes(out)

# ============================================================
# 5. CLUT 改写
# ============================================================

def rewrite_clut(orig_512):
    """512B=16 窗口 -> 4 套语义 (原版渐变保留, 套位改主色/白)。"""
    w = bytearray(orig_512)
    def getw(k, j):
        return struct.unpack_from("<H", w, k * 32 + j * 2)[0]
    def setw(k, j, v):
        struct.pack_into("<H", w, k * 32 + j * 2, v)
    # win0: 套 0 位 (奇数 j) -> 白; 偶数保留原版 (ASCII 渐变)
    for j in range(16):
        if j & 1:
            setw(0, j, WHITE)
    # win1-3: 原版保留 + 套位 (j 含 bit k) -> 该窗口原版主色 [1]
    for k in (1, 2, 3):
        main = getw(k, 1)
        for j in range(16):
            if (j >> k) & 1 and getw(k, j) == 0:
                setw(k, j, main if main else WHITE)
    # win4-8,A,D: 套 0 位 (奇数 j) 若原版 0 -> 主色
    for k in (4, 5, 6, 7, 8, 0xA, 0xD):
        main = getw(k, 1)
        for j in range(16):
            if j & 1 and getw(k, j) == 0:
                setw(k, j, main if main else WHITE)
    # win9/B/C: 纯套白窗口 (我们的切换窗口, ASCII 不进)
    for k, s in ((9, 1), (0xB, 2), (0xC, 3)):
        for j in range(16):
            setw(k, j, WHITE if (j >> s) & 1 else 0)
    return bytes(w)

# ============================================================
# 6. 主流程
# ============================================================

def patch_emi_segment(emi_buf, parsed, seg_index, new_data):
    seg = parsed["segments"][seg_index]
    if len(new_data) > seg["padded_size"]:
        return False        # 需要扩容
    off = seg["offset"]
    emi_buf[off:off + len(new_data)] = new_data
    for k in range(len(new_data), seg["padded_size"]):
        emi_buf[off + k] = 0
    if len(new_data) != seg["size"]:
        struct.pack_into("<I", emi_buf, seg["table_offset"], len(new_data))
    return True

def sync_exe_lba_table(iso, orig_files, new_files):
    """同步 SLPS_027.28 硬编码 LBA 表 (搬移文件后必须, 否则游戏按旧地址读)。

    表: 文件偏移 0x07ACE4, 516 项 x u32 LBA (递增, 覆盖 WORLD/SYSTEM)。
    映射: 原版表项值 -> 原版该 LBA 的文件 -> 新 LBA (未搬移则不变)。
    """
    import struct as _st
    # 定位 SLPS
    from bof4lib import parse_dir, DSZ, SEC, DOFF
    root = parse_dir(bytes(iso), 22, DSZ)
    slps = None
    for nm, lba, sz, isd in root:
        if nm.startswith("SLPS"):
            slps = (lba, sz)
            break
    if slps is None:
        raise RuntimeError("SLPS 未找到")
    exe = bytearray(read_file_from_iso(bytes(iso), slps[0], slps[1]))

    # old_lba -> new_lba
    lba_map = {}
    for name, (ol, osz) in orig_files.items():
        nl, nsz = new_files[name]
        if nl != ol:
            lba_map[ol] = nl

    FT_OFF = 0x07ACE4
    n_upd = 0
    off = FT_OFF
    end = len(exe) - 4
    while off < end:
        v = _st.unpack_from("<I", exe, off)[0]
        if not (90000 <= v <= 300000):
            break
        if v in lba_map:
            _st.pack_into("<I", exe, off, lba_map[v])
            n_upd += 1
        off += 4
    print("  EXE LBA 表同步: %d 项更新 (搬移文件 %d)" % (n_upd, len(lba_map)))

    # 写回 SLPS (原地, 大小不变)
    lba, size = slps
    write_file_to_iso(iso, lba, bytes(exe), size)
    return n_upd


def main():
    print("=" * 64)
    print("BOF4 v15 全量构建: 4 套 1bpp CLUT 分页")
    print("=" * 64)

    fsr = json.load(open(FSR, encoding="utf-8"))["segments"]
    cap_of = {}
    for f, segs in fsr.items():
        cap_of[f.upper()] = glyph_capacity(segs[0]["size"])

    print("[1/7] 扫描译文...")
    wb, mp, char_forced, char_files, freq = scan_all()
    print("  唯一字 %d, 强制套 %d, 文件 %d" % (
        len(char_files), len(char_forced),
        len(set().union(*char_files.values()))))

    print("[2/7] 字库分配...")
    alloc, gsets, scene, main_slot = allocate(char_forced, char_files, freq, cap_of)
    print("  全局槽: %s" % alloc["stats"]["per_set"])
    print("  场景文件: %d" % alloc["stats"]["scene_files"])
    json.dump(alloc, open(ALLOC_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("[3/7] 渲染字形 (%d 字)..." % len(char_files))
    mats = render_1bpp(set(char_files), FONT)
    print("  渲染完成")

    print("[4/7] 编码全部文本...")
    # workbook: (file, seg) 分组保序
    wb_by = defaultdict(list)
    for it in wb:
        wb_by[(it["file"].upper(), str(it["seg"]))].append(it)
    encoded = {}    # (file, seg) -> [首页 hex...]
    enc_err = []
    for key, items in wb_by.items():
        lst = []
        for it in items:
            tgt = it.get("tgt", "")
            if not tgt:
                lst.append("")
                continue
            try:
                lst.append(encode_v15(tgt, key[0], gsets, scene, main_slot).hex())
            except ValueError as exc:
                enc_err.append(str(exc))
        encoded[key] = lst
    # multipage 页 2+
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
                hex_list[pi - 2] = encode_v15(tgt, f, gsets, scene, main_slot).hex()
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

    print("[5/7] 打包字库槽...")
    # 全局槽字形: 槽 i 的 4 套 = gsets[k] 中 slot==i 的字符
    inv_g = [{v: k for k, v in gsets[k].items()} for k in range(4)]
    gcap_max = max(len(gsets[k]) for k in range(4))
    g_packed = {}
    for i in range(gcap_max):
        four = [mats.get(inv_g[k].get(i)) for k in range(4)]
        if all(m is None for m in four):
            continue
        g_packed[i] = pack_four(four)
    # 场景槽字形: 每文件
    s_packed = {}
    for f, ssets in scene.items():
        inv_s = [{v: k for k, v in ssets[k].items()} for k in range(4)]
        smax = max(len(ssets[k]) for k in range(4))
        if smax == 0:
            s_packed[f] = {}
            continue
        d = {}
        for j in range(smax):
            four = [mats.get(inv_s[k].get(j + G)) for k in range(4)]
            if all(m is None for m in four):
                continue
            d[j + G] = pack_four(four)
        s_packed[f] = d
    print("  全局槽 %d, 场景文件 %d" % (len(g_packed), len(s_packed)))

    print("[6/7] 写入镜像...")
    iso = bytearray(open(ISO, "rb").read())
    files = {n.upper(): (l, s) for n, l, s in list_iso_files(bytes(iso))}
    orig_files = dict(files)     # 搬移前 LBA (EXE 表同步用)
    emi_replacements = defaultdict(dict)    # name -> {seg_index: data}
    in_place = 0
    n_clut = 0
    n_font = 0

    # 全部 EMI: CLUT 段改写 + 字库段写入 + 文本段写入
    # 关键: 每文件先收集全部段修改; 有任一段超限 -> 全部段走 expand 重建
    # (否则 expand 从原始文件 rebuild, 丢掉其他段的原地修改 — v15 实证 bug)
    orig_iso = open(ISO, "rb").read()
    for name in sorted(files):
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        lba, size = files[name]
        emi_buf = bytearray(read_file_from_iso(bytes(iso), lba, size))
        parsed = parse_emi(bytes(emi_buf))
        if parsed is None:
            continue
        seg_final = {}       # seg_index -> 最终数据 (本文件全部修改)
        has_overflow = False

        # CLUT 段 (512B, sig=0x8002xxxx 主表条目)
        for seg in parsed["segments"]:
            sig = seg["sig"]
            if 0x8002E000 <= sig <= 0x8004E000 and seg["size"] == 512:
                seg_final[seg["index"]] = rewrite_clut(seg["data"])
                n_clut += 1

        # 字库段 (sig=0x1C000200)
        fsegs = find_font_segments(parsed)
        if fsegs:
            fseg = fsegs[0]
            fdata = bytearray(fseg["data"])
            for i, g in g_packed.items():
                set_glyph(fdata, i, g)
            for i, g in s_packed.get(name, {}).items():
                set_glyph(fdata, i, g)
            seg_final[fseg["index"]] = bytes(fdata)
            n_font += 1

        # 文本段
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

        # 分流: 任一段超 padded -> 全部走 expand; 否则原地逐段写
        for si, data in seg_final.items():
            if len(data) > parsed["segments"][si]["padded_size"]:
                has_overflow = True
                break
        if has_overflow:
            emi_replacements[name] = seg_final
        else:
            for si, data in seg_final.items():
                patch_emi_segment(emi_buf, parsed, si, data)
            if seg_final:
                write_file_to_iso(iso, lba, bytes(emi_buf), size)
                in_place += 1

    print("  CLUT 段: %d, 字库段: %d, 原地写入: %d" % (n_clut, n_font, in_place))

    # 扩容搬移
    if emi_replacements:
        print("  扩容段: %d 个文件..." % len(emi_replacements))
        moved = 0
        for name, reps in emi_replacements.items():
            res = expand_emi_in_iso(iso, name, reps)
            if res["moved"]:
                moved += 1
        print("  搬移: %d" % moved)

    # EXE LBA 表同步 (搬移后必须)
    new_files = {n.upper(): (l, s) for n, l, s in list_iso_files(bytes(iso))}
    sync_exe_lba_table(iso, orig_files, new_files)

    print("[7/7] 保存...")
    with open(OUT, "wb") as f:
        f.write(bytes(iso))
    print("output: %s" % OUT)
    print("size: %d (orig %d)" % (len(iso), os.path.getsize(ISO)))
    print("sha256: %s" % hashlib.sha256(bytes(iso)).hexdigest())

if __name__ == "__main__":
    main()
