---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'c33cf19e-13c6-42f8-a7de-ce61a2c4d8bd'
  PropagateID: 'c33cf19e-13c6-42f8-a7de-ce61a2c4d8bd'
  ReservedCode1: '121a7964-5a3e-4fdf-9e2a-3d648a8ce7ad'
  ReservedCode2: '121a7964-5a3e-4fdf-9e2a-3d648a8ce7ad'
---

# Breath of Fire IV — Simplified Chinese Translation Project

> A complete Chinese localization engineering project for the PS1 game
> *Breath of Fire IV - Utsurowazaru Mono* (Japanese version):
> full text extraction, full retranslation, font pixel layout reverse-engineering,
> glyph generation, and image building tools.
> This repository contains all translations, tools, and reverse-engineering docs
> so that future contributors can fully reproduce the work.

## Current Status (2026-09-18)

| Module | Status | Notes |
|--------|--------|-------|
| Text extraction | ✅ Done | 17,676 strings / 270 text segments / 262 EMI files |
| Full retranslation | ✅ Done | 15,049 non-empty strings, 100%, finalized in 24 TSV batches |
| Translation QA | ✅ Done | Control codes / newlines / separators all consistent, 0 kana, 0 missing |
| Font layout RE | ✅ Done | 21-column grid + low-nibble-left (verified byte-by-byte against VRAM dumps) |
| Glyph pipeline | ✅ Done | XP SimSun 12px bitmap + right/bottom 2-direction thin outline (v12 final) |
| Emulator test | ✅ Passed | v12 verification image displays Chinese correctly (desert meteor scene) |
| **Font capacity** | ❌ **Unresolved** | 2,087 unique chars > architecture capacity; **Path E (CLUT banking) passed static verification, awaiting v13 prototype**. See "Core Bottleneck" |

⚠️ **A full translated image cannot be built yet**: translation and rendering
technology are ready; the capacity model is being redesigned — **Path E
(CLUT banking) has passed static verification and only needs a v13 prototype test**.
Please read [docs/cracking_analysis.md](docs/cracking_analysis.md) (Chinese) and the
"Core Bottleneck" section below before continuing.

## Core Bottleneck: Font Capacity

Original font architecture (measured values under the 21-column layout):

| Item | Value |
|------|-------|
| Global shared slots (identical in all scene font segments) | 330 (index 0-329) |
| Scene-specific slots | 48 (28672B seg) / 58 (30720B) / 111 (32768B) |
| 7 system files without a font segment | can only use global slots |

Measured pressure from the full translation (output of `tools/check_capacity.py`):

| Metric | Value |
|--------|-------|
| Unique character union in translation | **2,087** (only 330 global slots; over by 1,757) |
| Char union of the 7 no-font system files | **1,134** (over by 804 — the worst bottleneck) |
| Files overflowing their segment capacity alone | 15 |
| Files overflowing scene slots after greedy global allocation | 124 |

**Root cause**: Japanese kana goes through the small font (1 byte, no main-font
slot), while every Chinese character must occupy a main-font slot (2 bytes).
The capacity model must be redesigned. Feasible paths (by invasiveness):

- **Path A**: minimal playable version — translate story scenes only, keep system UI Japanese
- **Path B**: constrained vocabulary — retranslate with a limited char set (~1,500 common chars), zero relocation
- **Path C**: segment expansion — grow font segments to 53,248 bytes each (`tools/emi_expand.py` ready; image grows)
- **Path D**: locate the small-font glyph resource (+225 slots, still insufficient alone; combine with others)
- **Path E★ (NEW, static verification passed)**: multiple glyph sets sharing pixels (CLUT banking) —
  pack 2/4 glyph sets into the same 12×12 slot with distinct pixel indices; at runtime the game's
  native `{色XX}` palette-window switch (64 windows) selects the visible set. Static RE confirmed:
  no pre-rasterized glyph cache, per-glyph CLUT field is a runtime variable, and palette content
  comes from EMI CLUT segments we fully control → capacity ×2 (keeps outline) / ×4
  (fits the entire translation with zero relocation).
  See [docs/clut_banking_design.md](docs/clut_banking_design.md) (Chinese)

## Repository Layout

```
bof4-chinese/
├── README.md                    # Chinese readme (primary)
├── README_EN.md                 # This file
├── CHANGELOG.md                 # v0.1 ~ v0.4 history
├── LICENSE                      # MIT
├── translation_workbook.json    # Translation workbook (17,676 entries, final translations)
│
├── texts/
│   ├── tsv/                     # ★ 24 translation TSV batches (final, collaborative format)
│   │   ├── batch_01~24.tsv      #   id / file / seg / src (Japanese) / tgt (Chinese)
│   │   ├── SPEC.md              #   Translation spec (kana ban, transliteration, glossary, control codes)
│   │   └── TSV_README.md        #   TSV usage notes
│   ├── original_japanese.txt    # Full decoded original text (multi-page, v0.6 rebuild)
│   ├── translated_chinese.txt   # Full JP/CN parallel text
│   └── original_hex_comparison.txt
│
├── tools/                       # Full toolchain (Python 3.8+)
│   ├── lib/bof4lib.py           # Shared lib: ISO r/w, EMI parsing, 21-col font layout, text codec
│   ├── merge_tsv.py             # ★ Merge TSV translations back into the workbook (with full QA)
│   ├── check_capacity.py        # ★ Character capacity audit (per-file usage vs segment capacity)
│   ├── patch_bin.py             # ★ One-click build: workbook + font → translated image
│   ├── export_text.py           # Text export (multi-page + scene font map, fixed in v0.6)
│   ├── dump_font.py             # Original font extraction → PNG + meta.json
│   ├── import_font.py           # Original font restoration (round-trip verification)
│   ├── scan_fonts.py            # Scan all 297 font segments
│   ├── check_text_size.py       # Text segment space pre-check
│   ├── rebuild_emi.py           # EMI segment replacement/expansion rebuild
│   ├── emi_expand.py            # EMI expansion + ISO file moving (for Path C)
│   ├── move_file_in_iso.py      # ISO9660 file relocation
│   ├── analyze_font_usage.py    # Character usage analysis (allocation planning)
│   ├── analyze_slps.py          # SLPS_027.28 reverse engineering (requires capstone)
│   ├── make_patch.py            # BDIF diff patch generation
│   └── apply_patch.py           # BDIF patch application
│
├── data/
│   ├── font_alloc_v2.json       # Font allocation plan (based on old translations, reference)
│   ├── font_segments_report.json# Report of all 297 font segments
│   ├── main_font_index.csv      # Original main font index table
│   ├── small_font_index.csv     # Original small font index table
│   ├── scene_map_original.json  # Original scene font mapping, 5,388 entries
│   └── text_blocks_original.json# Original text blocks (hex + decoded, v0.6 rebuild)
│
├── docs/                        # All in Chinese
│   ├── cracking_analysis.md     # ★ Cracking technical document (formats/encoding/fonts/capacity)
│   ├── clut_banking_design.md   # ★ Path E design doc (CLUT banking; static verification done)
│   ├── translation_guide.md     # Translation spec and glossary baseline
│   ├── slps_reverse_engineering.md # SLPS RE report (font loading path)
│   ├── font_source_experiment.md   # Font source experiments
│   ├── improvement_compliance.md   # Engineering compliance report
│   └── release_notes_v0.2.md    # Historical release notes
│
├── tests/
│   ├── test_codec.py            # Encoding/decoding tests (12)
│   ├── test_font_roundtrip.py   # 21-column layout tests (7)
│   ├── test_alloc.py            # Allocation consistency tests (14)
│   └── minimal_workbook.json
│
└── patch/                       # Historical patches (from old translations, reference only)
    ├── bof4_chinese_v0.2.bdiff
    ├── bof4_chinese_v0.2_data.json
    ├── bof4_chinese.bdiff        # v0.1-era patch
    └── patch_data.json
```

## Quick Start

### Requirements

- Python 3.8+
- Pillow (glyph rendering)

```bash
pip install pillow
```

Optional: capstone (only for `analyze_slps.py`).

### Workflow: edit translations, rebuild the image

**Step 1 — Edit translations**

Edit column 5 (`tgt`) of `texts/tsv/batch_NN.tsv`.
Keep columns 1-4 (`id`/`file`/`seg`/`src`) untouched.
Spec: `texts/tsv/SPEC.md` (Chinese; includes the transliteration table and glossary).

**Step 2 — Validate and merge back into the workbook**

```bash
python tools/merge_tsv.py texts/tsv translation_workbook.json
```

Checks kana residue, control codes, newline counts, separators, missing
translations. Any problem aborts without writing.

**Step 3 — Capacity audit (recommended)**

```bash
python tools/check_capacity.py translation_workbook.json
```

Prints per-file character usage vs. segment capacity and overflow lists.

**Step 4 — Build the translated image**

```bash
python tools/patch_bin.py "<original>.bin" translation_workbook.json output.bin \
    --alloc data/font_alloc_v2.json \
    --font C:/Windows/Fonts/simsun.ttc
```

> Note: `--alloc` is based on the old translation's character set; the new full
> translation will trigger capacity errors — exactly the "Core Bottleneck".
> Once the capacity model is resolved, this command produces the image end-to-end.
> Recommended font: **Windows XP SimSun simsun.ttc** (12px built-in bitmap glyphs).

### Scene-level verification image (technology already validated)

The v12 verification image (`bof4_verify_v12.bin`, zero relocation) was tested:
Chinese renders clearly with proper outline and control codes.

### Original font round-trip verification

```bash
python tools/dump_font.py "<original>.bin" --out font_dump --scale 4
python tools/import_font.py "<original>.bin" --dump font_dump
```

### Unit tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Key Technical Findings

### 1. Font pixel layout: 21-column grid

Font segment data maps to VRAM as a **21-column × 12px** grid (21×6=126 bytes
per row within the 256px region). Glyph `i` sits at `col = i % 21`,
`row = i // 21` (×12px). Segment offsets must be translated via
`_vram_to_seg()` (adjacent 2048-byte blocks sit side-by-side in VRAM).
Writing with the early "64B/row × 10 glyphs" hypothesis produced shattered
glyphs in-game — this was the root cause of all previous display failures.

### 2. Nibble order: low nibble = left pixel (PS1 standard)

4bpp packs 2 pixels per byte, **low nibble first**. Objective metrics:
isolated-pixel ratio 0.0036 (low-left) vs 0.0969 (high-left, 27× worse),
the latter showing as odd/even column misalignment in-game.

### 3. Glyph values + outline (v12 final)

| Value | Meaning |
|-------|---------|
| 1 | Stroke body (white) |
| 8 | Right/bottom 1px stroke extension (shadow — critical for visibility on light backgrounds) |
| 0 | Background |

Pure value-1 glyphs "occasionally disappear" on light backgrounds.
Three variants were compared (none / 3-direction thick / right-bottom thin);
**right-bottom 2-direction thin outline** was chosen.

### 4. Font loading path (confirmed via SLPS RE)

- Entering a scene uploads that scene EMI's font segment to VRAM, overwriting the global font
- `INIT.EMI`'s font segment is uploaded only at boot; it does not render in-game text
- 7 system files (CAMP/SHOP/MASTER/MSHOP/SGAMEN/SGAMENX/COMMU03) have no font
  segment and reuse whatever font is in VRAM — their characters must fit in global slots
- The EXE holds a 516-entry hardcoded LBA file table at RAM `0x8016BCE4`;
  ISO file moves that don't update this table break loading

### 5. Measured capacities (21-column layout)

| Segment size | Total slots | Scene-specific | Count |
|--------------|-------------|----------------|-------|
| 28672 (0x7000) | 378 | 48 | 210 |
| 30720 (0x7800) | 388 | 58 | 31 |
| 32768 (0x8000) | 441 | 111 | 56 |

Global/scene boundary = **330** (indices 0-329 identical across scenes;
the early documented value 349 was wrong).

### 6. Text encoding

| Bytes | Meaning |
|-------|---------|
| 0x12 XX | Main font index XX (0-255) |
| 0x13 XX | Main font index XX+256 (256-511) |
| 0x15 XX | Small font index XX+224 (glyph resource unlocated — do not rely on it) |
| Byte B (0x21-0x7E) | Small font index B-32 |
| Byte B (<0x21) | Control code (17 kinds: `{框}` `{立绘}` `{引2}` etc., preserved in translation) |

### 7. Small font: independent resource, location unknown

The small font (indices 0-61: ASCII/punctuation/kana) is an independent resource
not found in any of the 297 font segments. **Its inherent characters are usable
(1-byte encoding) but new characters cannot be added.**

## Translation Stats

| Item | Value |
|------|-------|
| Total entries | 17,676 |
| Translated (non-empty) | 15,049 |
| Text segments | 270 |
| EMI files | 262 |
| Unique Japanese source strings | 4,888 (67.5% dedup rate) |
| Control codes | 17, all preserved |
| QA result | 0 kana / 0 broken control codes / 0 newline mismatches / 0 missing |

## Handover Guide

1. **Read the docs**: `docs/cracking_analysis.md` (all format/layout/capacity facts, in Chinese) → this README's "Core Bottleneck" → `docs/clut_banking_design.md` (Path E, in Chinese)
2. **Run the tests**: `python -m unittest discover -s tests`
3. **Verify the font**: `dump_font.py` + `import_font.py` round-trip
4. **Pick a capacity path**: A/B/C/D/E above (Path E = CLUT banking, design doc ready, awaiting v13 prototype)
5. **Build**: `merge_tsv.py` → `patch_bin.py` end-to-end
6. **Test**: RetroArch (PCSX-ReArmed) or DuckStation

## Acknowledgments

- Capcom — the original game
- All translation and reverse-engineering contributors

## License

MIT License (see [LICENSE](LICENSE)).

This project is for study and research only. Please obtain and use a legitimate
copy of the game.

> AI-generated

> AI生成