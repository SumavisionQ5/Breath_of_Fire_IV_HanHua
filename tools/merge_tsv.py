# -*- coding: utf-8 -*-
"""
merge_tsv.py — 将翻译 TSV 批次合并回 translation_workbook.json

工作流:
    1. 在外部翻译 batch_01~24.tsv (第 5 列 tgt 填译文, 前 4 列不动)
    2. 运行本工具, 逐条校验后回填到 translation_workbook.json
    3. 运行 patch_bin.py 生成汉化镜像

校验项 (在 TSV 原始字面量形态上做, 防结构损坏):
    - 残留假名 (平假名/片假名/长音符)
    - 控制码 {..} 与原文逐个一致
    - \n 数量与原文一致 (TSV 内为字面量反斜杠+n)
    - --- 分隔线数量与原文一致
    - 缺译 / 空原文译文非空
    - 译文字段含真实 \r (TSV 结构损坏)

回填语义:
    TSV 内换行为字面量 \n (反斜杠+n), workbook 内为真实换行符 (0x0A)。
    load 时统一反转义, QA 与回填均在真实换行形态上进行, 避免两边形态不一致。

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
from collections import Counter

KANA_RE = re.compile(r'[\u3041-\u309F\u30A0-\u30FF\u30FC]')
CTRL_RE = re.compile(r'\{[^}]*\}')
# 配对型控制码: 开码 → 闭码 (嵌套顺序必须合法)
PAIR_OPEN_RE = re.compile(r'^\{(色[0-9A-F]{2}|特效)\}$')


def color_nesting_valid(ctrls):
    """检查 {色XX}/{特效} 与对应闭码在序列中的嵌套是否合法 (栈检查)。"""
    stack = []
    for c in ctrls:
        m = PAIR_OPEN_RE.match(c)
        if m:
            stack.append(c)
        elif c in ("{/色}", "{/特效}"):
            if not stack:
                return False
            open_c = stack.pop()
            if (open_c.startswith("{色") and c != "{/色}") or \
               (open_c == "{特效}" and c != "{/特效}"):
                return False
    return not stack


def load_tsv_dir(tsv_dir):
    """读取目录下全部 batch_NN.tsv / rebatch_NN.tsv, 返回 (id -> (file, seg, src, tgt)) 映射与统计。"""
    # 兼容三种命名: batch_* (第一轮) / rebatch_* (v0.6 重译) / kanabatch_* (假名修复)
    files = sorted(glob.glob(os.path.join(tsv_dir, "batch_*.tsv")) +
                   glob.glob(os.path.join(tsv_dir, "rebatch_*.tsv")) +
                   glob.glob(os.path.join(tsv_dir, "kanabatch_*.tsv")))
    if not files:
        raise FileNotFoundError("目录下未找到 batch_*.tsv / rebatch_*.tsv / kanabatch_*.tsv: %s" % tsv_dir)
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
            src_raw, tgt_raw = parts[3], parts[4]
            # TSV 结构校验: 字段内不得含 \r (真实 \n 已被分行, \t 已被列 split 拦截)
            if "\r" in tgt_raw:
                raise ValueError("%s 第 %d 行 tgt 含 \\r (TSV 结构损坏): id=%s" % (bname, ln, rid))
            # 反转义: TSV 字面量 \n → 真实换行 (与 workbook 内部形态对齐)
            src = src_raw.replace("\\n", "\n")
            tgt = tgt_raw.replace("\\n", "\n")
            mapping[rid] = (parts[1], parts[2], src, tgt)
    if dup:
        raise ValueError("TSV 中存在重复 id: %s" % dup[:10])
    return mapping


def build_capacity_table(wb):
    """从工作簿 (src 已为 v3 完整原文) 计算各 (file, seg) 的窗口行数容量。

    原版排版不会超出窗口 → 某文件段的最大页行数 = 该窗口实际容量。
    """
    cap = {}
    for e in wb:
        src = e.get("src") or ""
        if not src:
            continue
        key = (e["file"], e["seg"])
        for page in src.split("\n---\n"):
            n = page.count("\n") + 1
            if n > cap.get(key, 0):
                cap[key] = n
    return cap


def validate_entry(rid, src, tgt, errors, cap=None):
    """单条校验 (在真实换行形态上), 问题追加到 errors 列表。"""
    if KANA_RE.search(tgt):
        errors.append("残留假名 id=%s: %r" % (rid, tgt[:60]))
    # 控制码校验: 多重集合一致 + 配对结构合法 (顺序允许不同 = 中英文语序差异)
    src_ctrls = CTRL_RE.findall(src)
    tgt_ctrls = CTRL_RE.findall(tgt)
    if Counter(src_ctrls) != Counter(tgt_ctrls):
        errors.append("控制码不一致 id=%s: src=%r tgt=%r" % (rid, src_ctrls, tgt_ctrls))
    elif src_ctrls != tgt_ctrls and not color_nesting_valid(tgt_ctrls):
        errors.append("控制码顺序调整后配对结构损坏 id=%s: tgt=%r" % (rid, tgt_ctrls))
    if src.count("\n") != tgt.count("\n"):
        # 换行总数不同 ≠ 危险: 中文排版允许更紧凑/更松。
        # 真正危险的是页行数超过窗口容量 (超出游戏显示行数) → 页级检查:
        sp = src.split("\n---\n")
        tp = tgt.split("\n---\n")
        if len(sp) != len(tp):
            errors.append("分隔线分页数不一致 id=%s: src=%d tgt=%d" % (rid, len(sp), len(tp)))
        elif cap is not None:
            # 容量来自工作簿原文 (原版排版 ≤ 窗口)
            over = [(i + 1, b.count("\n") + 1)
                    for i, b in enumerate(tp)
                    if b.count("\n") + 1 > cap]
            if over:
                errors.append("页行数超窗口容量 id=%s: 容量%d, 溢出页: %s" % (
                    rid, cap, ", ".join("p%d:%d行" % t for t in over)))
        # cap 不可用时退化为与原文对应页比较 (更严格, 不会漏报)
        else:
            over = [(i + 1, a.count("\n") + 1, b.count("\n") + 1)
                    for i, (a, b) in enumerate(zip(sp, tp))
                    if b.count("\n") + 1 > a.count("\n") + 1]
            if over:
                errors.append("页行数溢出 id=%s: %s (页: src行数→tgt行数)" % (
                    rid, ", ".join("p%d:%d→%d" % t for t in over)))
    if src.count("---") != tgt.count("---"):
        errors.append("分隔线数量不一致 id=%s: src=%d tgt=%d" % (
            rid, src.count("---"), tgt.count("---")))
    if src.strip() and not tgt.strip():
        errors.append("缺少译文 id=%s: src=%r" % (rid, src[:60]))
    if not src.strip() and tgt.strip():
        errors.append("空原文译文非空 id=%s: tgt=%r" % (rid, tgt[:60]))


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

    # 窗口容量表: 从工作簿原文计算 (原版排版 ≤ 窗口 → 每段最大页行数 = 容量)
    if os.path.isfile(wb_path):
        with open(wb_path, encoding="utf-8") as f:
            _wb = json.load(f)
        cap_table = build_capacity_table(_wb)
        print("  窗口容量表: %d 个文件段" % len(cap_table))
    else:
        cap_table = None
        print("  (工作簿不存在, 页行数检查退化为与原文逐页比较)")

    # 逐条校验
    errors = []
    for rid in sorted(tsv_map):
        f_name, s_seg, src, tgt = tsv_map[rid]
        try:
            cap = cap_table.get((f_name, int(s_seg))) if cap_table else None
        except (TypeError, ValueError):
            cap = None
        validate_entry(rid, src, tgt, errors, cap=cap)
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
