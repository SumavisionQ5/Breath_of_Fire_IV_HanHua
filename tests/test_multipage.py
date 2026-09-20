# -*- coding: utf-8 -*-
"""build_text_segment 页级多页语义测试 (CHANGELOG v0.8 全项目多页修复)。

覆盖:
  - 单页槽替换 (与旧版行为一致)
  - 多页槽尾页保留 (未提供翻译时逐字节原样)
  - extra_pages 页 2+ 替换
  - 空译文槽整槽保留原文 (取代旧版清空行为)
  - trailing_nul / 无尾 0x00 两种槽结构保持
  - 编码列表耗尽/未耗尽报错
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "lib"))

import unittest
from bof4lib import build_text_segment, split_pages


def make_seg(slot_raws):
    """按槽原始字节列表构造文本段 (指针表 + 顺序数据)。返回 (seg, vals)。"""
    n = len(slot_raws)
    ptsize = n * 2
    vals = []
    off = ptsize
    for raw in slot_raws:
        vals.append(off)
        off += len(raw)
    seg = bytearray()
    import struct
    seg.extend(struct.pack('<%dH' % n, *vals))
    for raw in slot_raws:
        seg.extend(raw)
    return bytes(seg), tuple(vals)


# 槽样本:
#  S0 单页: 页1=\x12\x01 + 终止 0x00
S0 = b'\x12\x01\x00'
#  S1 多页 + 尾 0x00: 页1=\x12\x02, 页2=\x12\x03, 尾 0x00 (trailing_nul)
S1 = b'\x12\x02\x00\x12\x03\x00'
#  S2 多页无尾 0x00: 页1=\x12\x04, 页2=\x12\x05 (页2 无终止符)
S2 = b'\x12\x04\x00\x12\x05'
#  S3 全零空槽
S3 = b'\x00\x00\x00'


class TestBuildTextSegmentMultipage(unittest.TestCase):

    def setUp(self):
        self.seg, self.vals = make_seg([S0, S1, S2, S3])

    def test_single_page_replace(self):
        # 单页槽替换: enc 无终止符 → join 补 0x00 (与旧版行为一致)
        out = build_text_segment(self.seg, self.vals, ["1220", "1221", "1222"])
        self.assertEqual(out[8:11], b'\x12\x20\x00')

    def test_multipage_tail_pages_preserved(self):
        # 多页槽未提供 extra → 尾页逐字节保留 (v13.1 bug 2 修复核心)
        out = build_text_segment(self.seg, self.vals, ["1220", "1221", "1222"])
        # 槽1 (vals[1]=11..17): 页1 替换 + 页2 保留 + 尾 0x00
        self.assertEqual(out[11:17], b'\x12\x21\x00\x12\x03\x00')
        # 槽2 (17..22): 页1 替换 + 页2 保留, 无尾 0x00
        self.assertEqual(out[17:22], b'\x12\x22\x00\x12\x05')

    def test_extra_page_replaced(self):
        # extra_pages 页2 替换, 页1 正常消耗 encoded_list
        out = build_text_segment(
            self.seg, self.vals, ["1220", "1221", "1222"],
            extra_pages={1: ["1230"], 2: ["1231"]})
        self.assertEqual(out[11:17], b'\x12\x21\x00\x12\x30\x00')
        self.assertEqual(out[17:22], b'\x12\x22\x00\x12\x31')

    def test_extra_page_gap(self):
        # 页号跳跃: 页2 空串(保留原文) + 页3 替换 → 空串占位
        out = build_text_segment(
            self.seg, self.vals, ["1220", "1221", "1222"],
            extra_pages={1: ["", "1233"]})
        # 槽1 只有 2 页: extra[1]="" (页2 保留), extra[2]="1233" 无对应页 → 忽略
        self.assertEqual(out[11:17], b'\x12\x21\x00\x12\x03\x00')

    def test_empty_tgt_preserves_whole_slot(self):
        # 空译文 → 整槽保留原文 (取代旧版清空 b'\x00' 行为)
        out = build_text_segment(self.seg, self.vals, ["", "", ""])
        self.assertEqual(out[8:11], S0)
        self.assertEqual(out[11:17], S1)
        self.assertEqual(out[17:22], S2)

    def test_empty_slot_not_consumed(self):
        # 全零槽不消耗编码列表, 规范化为标准空槽 b'\x00' (旧版既有行为)
        out = build_text_segment(self.seg, self.vals, ["1220", "1221", "1222"])
        self.assertEqual(out[22:23], b'\x00')

    def test_page_count_invariant(self):
        # 重组后每槽页数不变 (含尾空位语义); 全零槽规范化为 b'\x00' 跳过
        import struct
        out = build_text_segment(
            self.seg, self.vals, ["1220", "1221", "1222"],
            extra_pages={1: ["1230"]})
        nvals = struct.unpack_from('<4H', out, 0)
        for k in range(4):
            raw_o = self.seg[self.vals[k]:self.vals[k + 1] if k + 1 < 4 else 25]
            if raw_o == b'\x00' * len(raw_o):
                continue          # 全零槽 → 标准空槽, 无页语义
            s = nvals[k]
            e = nvals[k + 1] if k + 1 < 4 else len(out)
            po = split_pages(raw_o)
            pn = split_pages(out[s:e])
            self.assertEqual(
                [p == b'' for p in po], [p == b'' for p in pn],
                "slot %d page-emptiness mismatch" % k)

    def test_exhausted_list_raises(self):
        with self.assertRaises(ValueError):
            build_text_segment(self.seg, self.vals, [])

    def test_not_fully_consumed_raises(self):
        with self.assertRaises(ValueError):
            build_text_segment(self.seg, self.vals, ["1220", "1221", "1222", "1223"])

    def test_trailing_nul_kept_with_extra(self):
        # trailing 0x00 在 extra 替换后仍保留
        out = build_text_segment(
            self.seg, self.vals, ["1220", "1221", "1222"],
            extra_pages={1: ["1230"]})
        self.assertTrue(out[16:17] == b'\x00' and out[11:16] == b'\x12\x21\x00\x12\x30')


if __name__ == "__main__":
    unittest.main()
