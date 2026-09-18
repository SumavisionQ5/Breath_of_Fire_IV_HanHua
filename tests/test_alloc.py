# -*- coding: utf-8 -*-
"""
test_alloc.py — 字库分配与场景字库独立性测试

覆盖:
  - 建议 8: Scene Font 编码依赖文件名 (每个 EMI 独立场景映射)
            绝不能只生成一个全局 scene_font.bin
  - 建议 21: 字库分配一致性检查 (容量/索引范围/互斥/重复索引)
  - 建议 22: 固定 font_alloc.json 不被自动重新分配

运行:
    python -m unittest tests/test_alloc.py -v
"""

import os
import sys
import json
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools', 'lib'))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))

from bof4lib import (
    encode_char, encode_text,
    MAIN_FONT_COUNT, SMALL_FONT_COUNT, SCENE_FONT_BASE,
)

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "patch_bin_mod", os.path.join(HERE, '..', 'tools', 'patch_bin.py'))
_pb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pb)


class TestSceneFontIndependence(unittest.TestCase):
    """建议 8: 场景字库按文件独立。"""

    def setUp(self):
        # 两个文件对同一索引位置 349 分配了不同字符
        self.alloc = {
            "global_main": {"龙": 0},
            "global_small": {},
            "small_font_inherent": {},
            "scene": {
                "WORLD/A.EMI": {"甲": 349, "乙": 350},
                "WORLD/B.EMI": {"丙": 349, "丁": 350},
            },
        }

    def test_same_index_different_char_per_file(self):
        """同一场景索引在不同文件中指向不同字符。"""
        self.assertEqual(encode_char("甲", "WORLD/A.EMI", self.alloc), b'\x13\x5d')
        self.assertEqual(encode_char("丙", "WORLD/B.EMI", self.alloc), b'\x13\x5d')
        # 交叉查询必须失败 (场景字不跨文件共享)
        with self.assertRaises(ValueError):
            encode_char("甲", "WORLD/B.EMI", self.alloc)
        with self.assertRaises(ValueError):
            encode_char("丙", "WORLD/A.EMI", self.alloc)

    def test_scene_not_shared_globally(self):
        """场景字不得被其他文件当作全局字使用。"""
        with self.assertRaises(ValueError):
            encode_char("甲", "WORLD/C.EMI", self.alloc)

    def test_encode_text_uses_filename(self):
        a = encode_text("龙甲", "WORLD/A.EMI", self.alloc)
        b = encode_text("龙丙", "WORLD/B.EMI", self.alloc)
        self.assertEqual(a, b'\x12\x00\x13\x5d')
        self.assertEqual(b, b'\x12\x00\x13\x5d')
        # 相同的字节序列在不同文件中代表不同字符
        self.assertEqual(a, b)


class TestAllocConsistency(unittest.TestCase):
    """建议 21: 字库分配一致性检查。"""

    def _base(self):
        return {
            "global_main": {"龙": 0, "战": 1},
            "global_small": {"的": 0},
            "small_font_inherent": {},
            "scene": {"WORLD/A.EMI": {"甲": 349}},
        }

    def test_valid_alloc_passes(self):
        _pb.check_alloc_consistency(self._base())

    def test_main_overflow(self):
        alloc = self._base()
        alloc["global_main"] = {"c%d" % i: i for i in range(MAIN_FONT_COUNT + 1)}
        with self.assertRaises(AssertionError):
            _pb.check_alloc_consistency(alloc)

    def test_small_overflow(self):
        alloc = self._base()
        alloc["global_small"] = {"s%d" % i: i for i in range(SMALL_FONT_COUNT + 1)}
        with self.assertRaises(AssertionError):
            _pb.check_alloc_consistency(alloc)

    def test_main_small_overlap(self):
        """建议 21: global_main ∩ global_small 必须为空。"""
        alloc = self._base()
        alloc["global_small"] = {"龙": 0}   # 与 global_main 重叠
        with self.assertRaises(AssertionError):
            _pb.check_alloc_consistency(alloc)

    def test_scene_overlap_with_global(self):
        """建议 21: 场景字不得出现在全局字库。"""
        alloc = self._base()
        alloc["scene"] = {"WORLD/A.EMI": {"龙": 349}}
        with self.assertRaises(AssertionError):
            _pb.check_alloc_consistency(alloc)

    def test_duplicate_index(self):
        """建议 21: 同一字库内索引不得重复。"""
        alloc = self._base()
        alloc["global_main"] = {"龙": 0, "战": 0}   # 重复索引 0
        with self.assertRaises(AssertionError):
            _pb.check_alloc_consistency(alloc)

    def test_scene_index_out_of_range(self):
        alloc = self._base()
        alloc["scene"] = {"WORLD/A.EMI": {"甲": 512}}   # 超出 0x13 编码上限
        with self.assertRaises(AssertionError):
            _pb.check_alloc_consistency(alloc)

    def test_main_index_out_of_range(self):
        alloc = self._base()
        alloc["global_main"] = {"龙": MAIN_FONT_COUNT}   # 越界
        with self.assertRaises(AssertionError):
            _pb.check_alloc_consistency(alloc)


class TestNoAutoRealloc(unittest.TestCase):
    """建议 22: 固定分配方案, 禁止自动重新分配。"""

    def test_build_font_block_missing_glyph_raises(self):
        """索引缺失字形时必须报错 (禁止静默补零)。"""
        with self.assertRaises(ValueError) as ctx:
            _pb.build_font_block({"龙": 5}, {}, 10)
        self.assertIn("Missing glyph", str(ctx.exception))

    def test_build_font_block_bad_size(self):
        with self.assertRaises(ValueError):
            _pb.build_font_block({"龙": 0}, {"龙": b'\x00' * 10}, 1)

    def test_build_font_block_ok(self):
        g = b'\x11' * 72
        data = _pb.build_font_block({"龙": 1}, {"龙": g}, 3)
        self.assertEqual(len(data), 3 * 72)
        # 槽 0 空, 槽 1 为字形, 槽 2 空
        self.assertEqual(data[:72], b'\x00' * 72)
        self.assertEqual(data[72:144], g)


if __name__ == "__main__":
    unittest.main()
