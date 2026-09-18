# -*- coding: utf-8 -*-
"""
merge_tsv.py — 将翻译 TSV 批次合并回 translation_workbook.json

工作流:
    1. 在外部翻译 batch_01~24.tsv (第 5 列 tgt 填译文, 前 4 列不动)
    2. 运行本工具, 逐条校验后回填到 translation_workbook.json
    3. 运行 patch_bin.py 生成汉化镜像

校验项:
    - 残留假名 (平假名/片假名/长音符)
    - 控制码 {..} 与原文逐个一致
    - \n 数量与原文一致
    - --- 分隔线数量与原文一致
    - 缺译 / 空原文译文非空
    - 译文含真实 tab/换行 (TSV 结构损坏)

用法:
    python tools/merge_tsv.py <tsv_dir> [workbook.json] [--check-only]

    tsv_dir     : 存放 batch_01~24.tsv 的目录
    workbook    : 翻译工作簿路径 (默认: 仓库根 translation_workbook.json)
    --check-only: 只校验不写回

退出码: 0 = 通过, 1 = 发现问题 (不写回)

作者: TeleAgent 龙战士4汉化项目
许可: MIT License
"""

import os
import sys
import json
import re
import glob
import shutil
import argparse

KANA_RE = re.compile(r'[\u3041-\u309F\u30A0-\u30FF\u30FC]')
CTRL_RE = re.compile(r'\{[^}]*\}')


def load_tsv_dir(tsv_dir):
    """读取目录下全部 batch_NN.tsv, 返回 (id -> (file, seg, src, tgt)) 映射与统计。"""
    files = sorted(glob.glob(os.path.join(tsv_dir, "batch_*.tsv")))
    if not files:
        raise FileNotFoundError("目录下未找到 batch_*.tsv: %s" % tsv_dir)
    mapping = {}
    dup = []
    for fp in files:
        bname = os.path.basename(fp)
        with open(fp, "r", encoding="utf-8-sig", newline="") as f:
            raw = f.read()
        lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if not lines:
            continue
        header = lines[0].split("\t")
        if header[:4] != ["id", "file", "seg", "src"]:
            raise ValueError("%s 表头异常: %r" % (bname, header[:4]))
        for ln, line in enumerate(lines[1:], 1):
            parts = line.split("\t")
            if len(parts) < 5:
                raise ValueError("%s 第 %d 行列数 %d != 5" % (bname, ln, len(parts)))
            rid = parts[0]
            if rid in mapping:
                dup.append(rid)
            mapping[rid] = (parts[1], parts[2], parts[3], parts[4])
    if dup:
        raise ValueError("TSV 中存在重复 id: %s" % dup[:10])
    return mapping


def validate_entry(rid, src, tgt, errors):
    """单条校验, 问题追加到 errors 列表。"""
    if KANA_RE.search(tgt):
        errors.append("残留假名 id=%s: %r" % (rid, tgt[:60]))
    if CTRL_RE.findall(src) != CTRL_RE.findall(tgt):
        errors.append("控制码不一致 id=%s: src=%r tgt=%r" % (
            rid, CTRL_RE.findall(src), CTRL_RE.findall(tgt)))
    if src.count("\\n") != tgt.count("\\n"):
        errors.append("换行数不一致 id=%s: src=%d tgt=%d" % (
            rid, src.count("\\n"), tgt.count("\\n")))
    if src.count("---") != tgt.count("---"):
        errors.append("分隔线数量不一致 id=%s: src=%d tgt=%d" % (
            rid, src.count("---"), tgt.count("---")))
    if src.strip() and not tgt.strip():
        errors.append("缺少译文 id=%s: src=%r" % (rid, src[:60]))
    if not src.strip() and tgt.strip():
        errors.append("空原文译文非空 id=%s: tgt=%r" % (rid, tgt[:60]))
    if "\t" in tgt or "\n" in tgt or "\r" in tgt:
        errors.append("译文含真实tab/换行 id=%s" % rid)


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description="合并翻译 TSV 到工作簿")
    ap.add_argument("tsv_dir", help="batch_*.tsv 所在目录")
    ap.add_argument("workbook", nargs="?",
                    default=os.path.join(os.path.dirname(__file__), "..",
                                         "translation_workbook.json"),
                    help="translation_workbook.json 路径")
    ap.add_argument("--check-only", action="store_true",
                    help="只校验, 不写回")
    args = ap.parse_args()

    tsv_dir = args.tsv_dir
    wb_path = os.path.abspath(args.workbook)

    print("读取 TSV: %s" % tsv_dir)
    tsv_map = load_tsv_dir(tsv_dir)
    print("  条目数: %d" % len(tsv_map))

    # 逐条校验
    errors = []
    for rid in sorted(tsv_map):
        _f, _s, src, tgt = tsv_map[rid]
        validate_entry(rid, src, tgt, errors)
    if errors:
        print("校验失败: %d 个问题" % len(errors))
        for e in errors[:50]:
            print("  %s" % e)
        sys.exit(1)
    print("校验通过: 控制码/换行/分隔线/假名/缺译 全部 OK")

    if args.check_only:
        print("--check-only: 不写回")
        return

    # 写回 workbook
    if not os.path.isfile(wb_path):
        raise FileNotFoundError("工作簿不存在: %s" % wb_path)
    with open(wb_path, encoding="utf-8") as f:
        wb = json.load(f)

    bak = wb_path + ".bak"
    shutil.copyfile(wb_path, bak)

    updated = 0
    unmatched = set(tsv_map.keys())
    for e in wb:
        rid = e["id"]
        if rid in tsv_map:
            unmatched.discard(rid)
            new_tgt = tsv_map[rid][3]
            if e.get("tgt") != new_tgt:
                e["tgt"] = new_tgt
                updated += 1
    if unmatched:
        print("警告: %d 个 TSV id 在工作簿中不存在 (忽略): %s" % (
            len(unmatched), sorted(unmatched)[:10]))

    with open(wb_path, "w", encoding="utf-8") as f:
        json.dump(wb, f, ensure_ascii=False, indent=1)
    print("回填完成: 更新 %d 条, 原簿已备份为 %s" % (
        updated, os.path.basename(bak)))


if __name__ == "__main__":
    main()
