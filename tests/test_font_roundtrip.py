# -*- coding: utf-8 -*-
"""
test_font_roundtrip.py — 字库布局 round-trip 单元测试

覆盖:
  - glyph_offset / get_glyph / set_glyph 三者对称 (21 列网格布局)
  - 任意 glyph 写入后提取 == 原数据
  - 跨 VRAM 块边界的 glyph (如 10, 20) 不互相覆盖
  - 段容量计算

背景: 早期版本误按 "64B/行 x 10 glyph 带" 实现, 导致字模写入错位、
      游戏中字形显示为碎片。已由 xcheck 系列实验证伪, 改为 21 列布局。

运行:
    python tests/test_font_roundtrip.py
"""

import os
import sys
import random
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools', 'lib'))
from bof4lib import (
    GLYPH_SIZE, FONT_GRID_COLS, FONT_CELL_ROWS, FONT_CELL_ROW_BYTES,
    FONT_BLOCK_COL_BYTES, FONT_BLOCK_ROWS,
    glyph_offset, glyph_cell, glyph_capacity, get_glyph, set_glyph,
)


def rand_glyph(seed):
    rnd = random.Random(seed)
    return bytes(rnd.randrange(256) for _ in range(GLYPH_SIZE))


class TestFontLayout(unittest.TestCase):

    def test_offsets_simple(self):
        # glyph 0 首行在段内偏移 0
        self.assertEqual(glyph_offset(0), 0)
        # glyph 1 同行下一列: 6 字节
        self.assertEqual(glyph_offset(1), 6)
        # glyph 9 仍在左块内: 9*6 = 54
        self.assertEqual(glyph_offset(9), 54)
        # glyph 10 列 = 60, 已到左块末尾 (6 字节中 4 字节在左块, 2 字节在右块)
        self.assertEqual(glyph_cell(10), (0, 60))
        # glyph 20 列 = 120 >= 64, 落入右块 (段行 32)
        self.assertEqual(glyph_cell(20), (0, 120))
        self.assertEqual(glyph_offset(20),
                         FONT_BLOCK_ROWS * FONT_BLOCK_COL_BYTES + (120 - 64))
        # glyph 21 换行: VRAM 行 = 12
        self.assertEqual(glyph_cell(21), (FONT_CELL_ROWS, 0))
        # 列数常量自检
        self.assertEqual(FONT_GRID_COLS, 21)

    def test_roundtrip_single(self):
        seg = bytearray(28672)
        g = rand_glyph(1)
        set_glyph(seg, 5, g)
        self.assertEqual(get_glyph(seg, 5), g)

    def test_roundtrip_many(self):
        seg = bytearray(28672)
        cap = glyph_capacity(28672)
        glyphs = {i: rand_glyph(i) for i in range(cap)}
        for i, g in glyphs.items():
            set_glyph(seg, i, g)
        for i, g in glyphs.items():
            self.assertEqual(get_glyph(seg, i), g, "glyph %d mismatch" % i)

    def test_cross_block_no_overlap(self):
        """跨块 glyph (10, 20) 与相邻 glyph 不得互相覆盖"""
        seg = bytearray(28672)
        targets = [9, 10, 11, 19, 20, 21, 29, 30, 31, 32]
        glyphs = {i: rand_glyph(100 + i) for i in targets}
        for i in targets:
            set_glyph(seg, i, glyphs[i])
        for i in targets:
            self.assertEqual(get_glyph(seg, i), glyphs[i], "glyph %d 被覆盖" % i)

    def test_capacity(self):
        # 21 列布局下的实际容量 (由 glyph_capacity 精确计算)
        #   28672 段 (14 块) -> 378 槽
        #   30720 段 (15 块) -> 388 槽 (第 8 层只有左块, 右半列不可用)
        #   32768 段 (16 块) -> 441 槽 (21 列 x 21 行)
        self.assertEqual(glyph_capacity(28672), 378)
        self.assertEqual(glyph_capacity(30720), 388)
        self.assertEqual(glyph_capacity(32768), 441)

    def test_out_of_range_safe(self):
        """超容量索引读取不得抛异常, 且返回全 0"""
        seg = bytes(28672)
        self.assertEqual(get_glyph(seg, 5000), b'\x00' * GLYPH_SIZE)

    def test_row_pixels_high_nibble(self):
        # 验证"高 nibble 在前"的像素布局约定
        g = bytes([0x87]) + b'\x00' * (GLYPH_SIZE - 1)
        rows = []
        for r in range(12):
            row = []
            for b in g[r * 6:(r + 1) * 6]:
                row.append((b >> 4) & 0xF)
                row.append(b & 0xF)
            rows.append(row[:12])
        self.assertEqual(rows[0][0], 8)
        self.assertEqual(rows[0][1], 7)


if __name__ == "__main__":
    unittest.main()
