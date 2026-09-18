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
    trim,
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


if __name__ == "__main__":
    import struct
    unittest.main()