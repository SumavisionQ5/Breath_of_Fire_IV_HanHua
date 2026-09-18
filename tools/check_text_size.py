# -*- coding: utf-8 -*-
"""
check_text_size.py — 文本段空间预检查 (建议19)

功能:
    对翻译工作簿的每个 (file, seg) 文本段, 先编码文本,
    统计新旧字节数, 标记所有 new_padded > old_padded 的超长段,
    输出 check_text_size_report.json。

    注意: 此工具只做预算, 不修改任何文件。
    超长段需要 tools/rebuild_emi.py 做 EMI relocation 解决。

用法:
    python tools/check_text_size.py <original.bin> <translation_workbook.json> \
        --alloc data/font_alloc.json [--out check_text_size_report.json]

依赖:
    pip install pillow (仅 encode 文本不需要, 但保持与 patch_bin 一致)

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
from bof4lib import (
    DSZ,
    read_file_from_iso, list_iso_files, parse_emi,
    is_text_segment, trim, encode_text, encode_char, build_encoded_map, build_text_segment,
)


def load_alloc(path):
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    if not txt.lstrip().startswith('{'):
        txt = txt[txt.index('{'):]
    return json.loads(txt)


def encode_text_lenient(tgt, fname, alloc):
    """宽容编码 (仅用于空间估算, 建议19)。

    未映射字符按 2 字节占位计入长度, 使空间检查能在字库未完成时
    仍然给出分段分类; 与严格模式结果可能有微小差异。
    """
    result = bytearray()
    i = 0
    while i < len(tgt):
        ch = tgt[i]
        if ch == '{':
            j = tgt.find('}', i)
            if j > 0:
                try:
                    result.extend(encode_text(tgt[i:j + 1], fname, alloc))
                except ValueError:
                    result.extend(b'\x12\x00')
                i = j + 1
                continue
        if ch == '\n':
            result.append(0x01)
            i += 1
            continue
        if tgt[i:i + 3] == '---':
            result.append(0x02)
            i += 3
            continue
        try:
            result.extend(encode_char(ch, fname, alloc, i))
        except ValueError:
            result.extend(b'\x12\x00')
        i += 1
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description="龙战士4 文本段空间预检查")
    parser.add_argument("original_bin", help="原始日版 BIN 镜像")
    parser.add_argument("workbook", help="翻译工作簿 JSON")
    parser.add_argument("--alloc", required=True, help="固定字库分配方案 JSON")
    parser.add_argument("--out", default="check_text_size_report.json")
    parser.add_argument("--tolerate-unmapped", action="store_true",
                        help="未映射字符按 2 字节占位计入 (仅用于空间估算)")
    args = parser.parse_args()

    alloc = load_alloc(args.alloc)

    with open(args.workbook, "r", encoding="utf-8") as f:
        workbook = json.load(f)

    with open(args.original_bin, 'rb') as f:
        iso_data = f.read()

    files = list_iso_files(iso_data)

    # 预编码全部文本 (未映射字符会抛错, 与 patch_bin 一致)
    encoded_texts = []
    errors = []
    for item in workbook:
        tgt = item.get("tgt", "")
        fname = item.get("file", "")
        seg = item.get("seg", 0)
        eid = item.get("id", "")
        if not tgt:
            encoded_texts.append({"file": fname, "id": eid, "seg": seg, "encoded_hex": ""})
            continue
        try:
            enc = encode_text(tgt, fname, alloc)
        except ValueError as exc:
            errors.append(str(exc))
            if args.tolerate_unmapped:
                enc = encode_text_lenient(tgt, fname, alloc)
            else:
                continue
        encoded_texts.append({"file": fname, "id": eid, "seg": seg, "encoded_hex": enc.hex()})
    if errors:
        if args.tolerate_unmapped:
            print("注意: %d 处未映射字符, 已按 2 字节占位 (仅空间估算), 首条: %s" % (
                len(errors), errors[0]))
        else:
            print("文本编码失败: %d 处未映射字符, 首条: %s" % (len(errors), errors[0]))
            sys.exit(1)

    enc_by_fileseg = defaultdict(list)
    for et in encoded_texts:
        enc_by_fileseg[(et["file"], et["seg"])].append(et)

    report = {"overlong": [], "ok": 0, "segments_checked": 0, "unmapped": len(errors)}

    for name, lba, size in files:
        if not (name.startswith("WORLD/") or name.startswith("SYSTEM/")):
            continue
        emi_buf = read_file_from_iso(iso_data, lba, size)
        parsed = parse_emi(emi_buf)
        if parsed is None:
            continue
        for seg in parsed["segments"]:
            vals = is_text_segment(seg["data"])
            if vals is None:
                continue
            blk_seg = seg["index"] + 1
            key = (name, blk_seg)
            if key not in enc_by_fileseg:
                continue
            encoded_map = build_encoded_map(enc_by_fileseg[key])
            new_seg_data = build_text_segment(seg["data"], vals, encoded_map)
            new_size = len(new_seg_data)
            new_padded = new_size + (-new_size % DSZ)
            old_padded = seg["padded_size"]
            report["segments_checked"] += 1
            if new_padded <= old_padded:
                report["ok"] += 1
            else:
                report["overlong"].append({
                    "file": name,
                    "seg": blk_seg,
                    "old_size": seg["size"],
                    "old_padded": old_padded,
                    "new_size": new_size,
                    "new_padded": new_padded,
                    "overflow": new_padded - old_padded,
                })

    # 排序输出
    report["overlong"].sort(key=lambda x: (-x["overflow"], x["file"]))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("检查完成:")
    print("  文本段总数   : %d" % report["segments_checked"])
    print("  可原地写入   : %d" % report["ok"])
    print("  超长段       : %d" % len(report["overlong"]))
    for o in report["overlong"][:20]:
        print("    %s seg%d: %d -> %d (+%d)" % (
            o["file"], o["seg"], o["old_padded"], o["new_padded"], o["overflow"]
        ))
    print("  报告已输出   : %s" % args.out)


if __name__ == "__main__":
    main()