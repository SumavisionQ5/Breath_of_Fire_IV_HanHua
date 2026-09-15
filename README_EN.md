---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'c74a5e65-3507-4433-9e92-de0945995ba9'
  PropagateID: 'c74a5e65-3507-4433-9e92-de0945995ba9'
  ReservedCode1: '997fe231-69c1-48cf-913d-b9bbebcfa969'
  ReservedCode2: '997fe231-69c1-48cf-913d-b9bbebcfa969'
---

# Breath of Fire IV — Simplified Chinese Translation Project

## Overview

This project provides a Simplified Chinese translation patch for the PlayStation 1 game *Breath of Fire IV - Utsurowazaru Mono* (Japanese version).

The translation work includes:
- Full Japanese text extraction (17,676 strings across 270 text segments in 262 EMI files)
- Complete Chinese translation (15,049 non-empty strings, 100% complete)
- 12×12 pixel Chinese font generation (349 global main + 205 small font + 261 scene fonts)
- Game image patching

## Project Status

⚠️ **The translation patch is a work in progress and not fully functional yet.**

| Feature | Status |
|---------|--------|
| Text extraction | ✅ Complete |
| Chinese translation | ✅ Complete (100%) |
| Font allocation | ✅ Complete |
| Glyph generation | ✅ Complete |
| Text encoding | ✅ Complete |
| BIN image patching | ✅ Complete (262/270 segments) |
| Emulator testing | ⚠️ Game boots, text display needs fixing |
| Scene font writing | ❌ Pending |
| Pixel format validation | ⚠️ Format confirmed, pixel layout needs verification |

## File Structure

```
bof4-chinese/
├── README.md                    # Chinese readme
├── README_EN.md                 # This file
├── docs/
│   └── cracking_analysis.md     # Technical documentation (Chinese)
├── texts/
│   ├── original_japanese.txt    # Original Japanese text
│   ├── original_hex_comparison.txt # Hex comparison
│   └── translated_chinese.txt   # Translated Chinese text
├── tools/
│   ├── lib/
│   │   └── bof4lib.py           # Shared library (ISO/EMI/encoding)
│   ├── export_text.py          # Text export tool
│   └── patch_bin.py            # One-click patching tool
├── data/
│   ├── font_alloc.json          # Font allocation scheme
│   ├── main_font_index.csv     # Main font index table
│   ├── small_font_index.csv    # Small font index table
│   └── merged_font_index.csv   # Merged index table
└── patch/
    └── (patch file — to be generated)
```

## Quick Start

### Requirements

- Python 3.8+
- PIL/Pillow (for glyph generation)

```bash
pip install pillow
```

### One-Click Patching

```bash
python tools/patch_bin.py "Breath of Fire IV - Utsurowazaru Mono (Japan).bin" \
    translation_workbook.json \
    bof4_chinese.bin \
    data/font_alloc.json
```

### Export Original Text

```bash
python tools/export_text.py "Breath of Fire IV - Utsurowazaru Mono (Japan).bin" output/
```

## Translation Statistics

- **Total entries**: 17,676
- **Non-empty entries**: 15,049
- **Translation coverage**: 100%
- **Text segments**: 270
- **EMI files**: 262
- **Control codes**: 17 types (all preserved)
- **Unique characters**: 1,804 (349 main + 205 small + 261 scene)

## Technical Details

See [cracking_analysis.md](docs/cracking_analysis.md) for full technical documentation (in Chinese).

### Encoding Rules

| Byte sequence | Meaning |
|---------------|---------|
| 0x12 XX | Main font index XX (0-255) |
| 0x13 XX | Main font index XX+256 or scene font |
| 0x15 XX | Small font index XX+224 |
| Byte B (≥0x21) | Small font index B-32 |
| Byte B (<0x21) | Control code |

### Font Structure

- **Main font**: 349 glyphs, stored in INIT.EMI Seg7 (VRAM 0x1C000200)
- **Small font**: 205 glyphs (extension)
- **Scene fonts**: Up to 97 per scene (index 349-445)

### Glyph Format

- Size: 12×12 pixels
- Color depth: 4bpp (4 bits per pixel)
- Data size: 72 bytes per glyph (12 rows × 6 bytes/row)
- Grayscale: 9 levels (0-8, 0=transparent, 8=opaque)

## License

This project is for educational and research purposes only. Please support the official game release.

> AI生成