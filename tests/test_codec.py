# -*- coding: utf-8 -*-
"""
test_codec.py — 文本编码/解码单元测试

覆盖 (建议6/7):
  - encode_char 单字符编码
  - 未映射字符必须抛 ValueError (禁止静默变 0x12 0x00)
  - encode_text 控制码/换行/分隔线
  - build_encoded_map 按 ID 精确匹配
  - build_text_segment 缺失翻译报错

运行:
    python tests/test_codec.py   (无依赖, 纯标准库)
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools', 'lib'))
from bof4lib import (
    encode_char, encode_text, build_encoded_map, build_text_segment,
    trim, split_pages, CTRL_LEN,
)


class TestCodec(unittest.TestCase):

    def setUp(self):
        self.alloc = {
            "global_main": {"龙": 0, "战": 1, "士": 2, "是": 3},
            "global_small": {"的": 0, "爱": 1},
            "small_font_inherent": {"！": 0, "？": 1},
            "scene": {
                "SYSTEM/CAMP.EMI": {"你": 349, "我": 350},
                "WORLD/AREAD000.EMI": {"大": 349},
            },
        }

    def test_encode_char_main(self):
        self.assertEqual(encode_char("龙", "SYSTEM/CAMP.EMI", self.alloc), b'\x12\x00')
        self.assertEqual(encode_char("士", "SYSTEM/CAMP.EMI", self.alloc), b'\x12\x02')

    def test_encode_char_small(self):
        self.assertEqual(encode_char("的", "SYSTEM/CAMP.EMI", self.alloc), b'\x15\x01')

    def test_encode_char_ascii(self):
        self.assertEqual(encode_char("A", "SYSTEM/CAMP.EMI", self.alloc), b'A')

    def test_encode_char_unmapped_raises(self):
        with self.assertRaises(ValueError):
            encode_char("未", "SYSTEM/CAMP.EMI", self.alloc)

    def test_encode_char_scene(self):
        self.assertEqual(encode_char("你", "SYSTEM/CAMP.EMI", self.alloc), b'\x13\x5d')  # 349-256=93=0x5D
        with self.assertRaises(ValueError):
            encode_char("大", "SYSTEM/CAMP.EMI", self.alloc)  # 大只在 AREAD000

    def test_encode_text(self):
        enc = encode_text("龙战士", "SYSTEM/CAMP.EMI", self.alloc)
        self.assertEqual(enc, b'\x12\x00\x12\x01\x12\x02')

    def test_encode_text_control(self):
        enc = encode_text("龙{框06}士", "SYSTEM/CAMP.EMI", self.alloc)
        self.assertEqual(enc, b'\x12\x00\x0c\x06\x12\x02')

    def test_encode_text_newline(self):
        enc = encode_text("龙\n士", "SYSTEM/CAMP.EMI", self.alloc)
        self.assertEqual(enc, b'\x12\x00\x01\x12\x02')

    def test_encode_text_sep(self):
        enc = encode_text("龙---士", "SYSTEM/CAMP.EMI", self.alloc)
        self.assertEqual(enc, b'\x12\x00\x02\x12\x02')

    def test_build_encoded_map_order(self):
        ets = [
            {"file": "X", "id": "000208", "seg": 1, "encoded_hex": "aa"},
            {"file": "X", "id": "000209", "seg": 1, "encoded_hex": "bb"},
            {"file": "X", "id": "000210", "seg": 1, "encoded_hex": "cc"},
        ]
        m = build_encoded_map(ets)
        # 按工作簿顺序的列表 (id 是全局编号, 匹配按组内顺序)
        self.assertEqual(m, ["aa", "bb", "cc"])

    def test_build_text_segment_missing(self):
        # 原始段: 指针表 2 个指针, 一个非空字符串
        orig = b'\x04\x00\x08\x00' + b'\x12\x00\x00'  # 指针表 2 条 + 数据
        vals = (4, 8)
        with self.assertRaises(ValueError):
            build_text_segment(orig, vals, {})

    def test_trim(self):
        self.assertEqual(trim(b'\x12\x00\x12\x01\x00rest'), b'\x12\x00\x12\x01')

    # ---- 2026-09-18 修复: trim 参数感知 + split_pages 多页切分 ----

    def test_trim_control_param_zero(self):
        # {立绘80 00}: 0x17 2 参数, 第 2 参数为 0x00, 不得误判为终止符
        self.assertEqual(trim(b'\x17\x80\x00\x77\x5f\x00next'), b'\x17\x80\x00\x77\x5f')

    def test_trim_color_param(self):
        # {色01} = 0x05 0x01, 参数不是 0x00, 后随字符正常
        self.assertEqual(trim(b'\x05\x01\x82\x00rest'), b'\x05\x01\x82')

    def test_trim_code14_three_params(self):
        # 0x14 = 3 参数 (CAMP 对齐实证): 参数区整体跳过
        self.assertEqual(trim(b'\x14\x82\x0c\x82\x77\x00rest'), b'\x14\x82\x0c\x82\x77')

    def test_split_pages_identity(self):
        # 恒等式: b'\x00'.join(pages) == raw
        for raw in (b'A\x00B\x00', b'A\x00B', b'\x00', b'ABC', b'',
                    b'\x17\x80\x00\x77\x00X\x00', b'\x00\x00A'):
            self.assertEqual(b'\x00'.join(split_pages(raw)), raw, repr(raw))

    def test_split_pages_param_aware(self):
        # {立绘80 00} 参数 0x00 不切页; 真终止符才切
        raw = b'\x17\x80\x00\x77\x5f\x00\x82\x77\x00'
        pages = split_pages(raw)
        self.assertEqual(pages, [b'\x17\x80\x00\x77\x5f', b'\x82\x77', b''])

    def test_split_pages_trailing_nul(self):
        # raw 以 0x00 结尾 → 尾部多一个 b'' (存储空位, 消费方按需丢弃)
        self.assertEqual(split_pages(b'A\x00B\x00'), [b'A', b'B', b''])

    def test_encode_decode_unknown_codes_reversible(self):
        # 未定位语义码的 decode/encode 可逆性 (名字格式 {码XX})
        # encode: {码03} → 0x03; {码14820C82} → 14 82 0C 82 (前缀分支每 2 hex 一字节)
        self.assertEqual(encode_text("{码03}", "X", self.alloc), b'\x03')
        self.assertEqual(encode_text("{码14820C82}", "X", self.alloc), b'\x14\x82\x0c\x82')
        self.assertEqual(encode_text("A B", "X", self.alloc), b'\x41\x20\x42')  # 空格直通

    def test_ctrl_len_table_consistency(self):
        # CTRL_LEN 覆盖 0x01-0x20 全部码 (0x00 终止符除外)
        missing = [b for b in range(1, 0x21) if b not in CTRL_LEN]
        self.assertEqual(missing, [])
        # 已知关键码的总长 (反汇编/对齐实证)
        for code, total in ((0x05, 2), (0x0c, 2), (0x14, 4), (0x17, 3),
                            (0x19, 3), (0x12, 2), (0x20, 1)):
            self.assertEqual(CTRL_LEN[code], total, "0x%02X" % code)

    def test_encode_space_control_code_hex_pairs(self):
        # 2026-09-18 修复: 带空格的控制码 (如 {引2 5A40}) 参数应按 2 位 hex 为 1 字节编码
        # 旧 bug: 逐字符编码 → 19 05 0A 04 00 (5 字节, 每个 hex 数字当独立字节)
        # 修复后: 19 5A 40 (3 字节 = CTRL_LEN[0x19])
        self.assertEqual(encode_text("{引2 5A40}", "X", self.alloc), b'\x19\x5a\x40')
        self.assertEqual(encode_text("{引2 0A00}", "X", self.alloc), b'\x19\x0a\x00')

    def test_encode_space_vs_no_space_equivalent(self):
        # 带空格 {引2 5A40} 与无空格 {引25A40} 编码结果应一致
        self.assertEqual(
            encode_text("{引2 5A40}", "X", self.alloc),
            encode_text("{引25A40}", "X", self.alloc),
        )


if __name__ == "__main__":
    import struct
    unittest.main()