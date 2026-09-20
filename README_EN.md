---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '9ee65c80-20fe-4fb6-a1f5-ed4f66c82c5b'
  PropagateID: '9ee65c80-20fe-4fb6-a1f5-ed4f66c82c5b'
  ReservedCode1: '84576f3e-56a4-4377-9320-90d5ff0db2a6'
  ReservedCode2: '84576f3e-56a4-4377-9320-90d5ff0db2a6'
---

# Breath of Fire IV — Simplified Chinese Translation Project

> A complete Chinese localization engineering project for the PS1 game
> *Breath of Fire IV - Utsurowazaru Mono* (Japanese version):
> full text extraction, full retranslation, font pixel layout reverse-engineering,
> glyph generation, and image building tools.
> This repository contains all translations, tools, and reverse-engineering docs
> so that future contributors can fully reproduce the work.

## Current Status (2026-09-20)

| Module | Status | Notes |
|--------|--------|-------|
| Text extraction | ✅ Done | 17,676 strings / 270 text segments / 262 EMI files |
| Full retranslation | ✅ Done | 15,049 non-empty strings, 100%, finalized in 24 TSV batches |
| Translation QA | ✅ Done | Control codes / newlines / separators all consistent, 0 kana, 0 missing |
| Font layout RE | ✅ Done | 21-column grid + low-nibble-left (verified byte-by-byte against VRAM dumps) |
| **Font capacity** | ✅ **Resolved** | 4-set 1bpp CLUT banking (Path E implemented; shipped in the v15 full build) |
| **Full translated image** | ✅ **Built** | v15 full build (story/dialog) + v16e system-text backfill, tested in-game |
| System text backfill | ✅ v16e | 62 save/load/settings/naming strings tested in-game; remaining 1,138 translated, backfill pending (v16f) |
| Glyph pipeline | ✅ Done | XP SimSun 12px bitmap; outline = 8-neighborhood ring (corrected in v16e) |
| Emulator test | ✅ Passed | v16e naming screen: white core + dark outline clearly readable; title/graphics no regression |

Current baseline image `bof4_chinese_v16e.bin` (740,731,544 B, SHA256 eeada38a…):
the v15 full localization (story/dialog, 4-set font banking) plus the v16e system-text
backfill (62 translations in DEMO seg2 + SYSTEM font packed as V1 outline / V9 white core
+ INIT win0[9] whitened). Build instructions under "Build the full image (v15/v16e)" below;
the v16 technical findings are documented in
[docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md) (Chinese) and
[CHANGELOG.md](CHANGELOG.md) v0.8.2.

## Font Capacity Problem (Resolved: Path E, 4-set CLUT banking, shipped in v15)

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
- **Path E★ (IMPLEMENTED)**: multiple glyph sets sharing pixels (CLUT banking) —
  pack four glyph sets into the same 12×12 slot with distinct pixel indices; at runtime the game's
  native `{色XX}` palette-window switch (64 windows) selects the visible set. Static RE confirmed:
  no pre-rasterized glyph cache, per-glyph CLUT field is a runtime variable, and palette content
  comes from EMI CLUT segments we fully control → capacity ×4, fitting the entire translation
  with zero relocation. See [docs/clut_banking_design.md](docs/clut_banking_design.md) (Chinese).
  **Shipped since v15**: 4-set architecture (global pool 330×4 + per-scene (cap-330)×4 +
  native color-code forced sets + set-switch codes; build script `tools/bof4_v15_full_build.py`)

## Repository Layout

```
bof4-chinese/
├── README.md                    # Chinese readme (primary)
├── README_EN.md                 # This file
├── CHANGELOG.md                 # v0.1 ~ v0.8.2 history
├── LICENSE                      # MIT
├── translation_workbook.json    # Translation workbook (17,676 entries, final translations)
│
├── texts/
│   ├── tsv/                     # ★ 24 translation TSV batches (final, collaborative format)
│   │   ├── batch_01~24.tsv      #   id / file / seg / src (Japanese) / tgt (Chinese)
│   │   ├── SPEC.md              #   Translation spec (kana ban, transliteration, glossary, control codes)
│   │   ├── TSV_README.md        #   TSV usage notes
│   │   └── system_text/         #   ★ System text (62 backfilled in v16e + 1,138 translated, pending v16f)
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
│   ├── apply_patch.py           # BDIF patch application
│   ├── bof4_v15_full_build.py   # ★ v15 full image build (4-set CLUT banking)
│   ├── bof4_v16e_build.py       # ★ v16e = v15 + system-text backfill (DEMO seg2 + seg4 pool copy)
│   ├── bof4_v16e_demo_verify.py # ★ v16e DEMO/SYSTEM focused verification
│   ├── bof4_v16e_full_verify.py # ★ v16e full read-back verification (470 EMI / CLUT / fonts)
│   ├── bof4_export_remaining.py    # Untranslated system-text export (1,138 strings)
│   └── bof4_translate_remaining.py  # System-text translation fill-back into TSV (for v16f)
│
├── data/
│   ├── font_alloc_v2.json       # Font allocation plan (based on old translations, reference)
│   ├── font_alloc_4set.json     # ★ v15 4-set allocation (used by the v15/v16e builds)
│   ├── font_alloc_4set_v16.json # v16 4-set allocation (used by v16e verification)
│   ├── font_segments_report.json# Report of all 297 font segments
│   ├── main_font_index.csv      # Original main font index table
│   ├── small_font_index.csv     # Original small font index table
│   ├── scene_map_original.json  # Original scene font mapping, 5,388 entries
│   └── text_blocks_original.json# Original text blocks (hex + decoded, v0.6 rebuild)
│
├── docs/                        # All in Chinese
│   ├── cracking_analysis.md     # ★ Cracking technical document (formats/encoding/fonts/capacity)
│   ├── v16_system_text_backfill.md # ★ v16 system-text backfill findings (seg2/CLUT/glyph spec)
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

> Note: `patch_bin.py` is the v0.x scene-level verification tool (allocation based on the old
> translation's character set). **The full build now goes through the v15/v16e chain** — see below.
> Recommended font: **Windows XP SimSun simsun.ttc** (12px built-in bitmap glyphs).

### Build the full image (v15/v16e, current baseline)

```bash
# v16e build = v15 full build (imports bof4_v15_full_build) first, then
#   DEMO seg2 62-string backfill + SYSTEM font packed V1-outline/V9-white-core + INIT win0[9] whitening
python tools/bof4_v16e_build.py

# Double static verification (read-only, no image writes)
python tools/bof4_v16e_demo_verify.py
python tools/bof4_v16e_full_verify.py
```

Produces `bof4_chinese_v16e.bin` (740,731,544 B, SHA256 eeada38a…).
Inputs: the original Japanese image, `translation_workbook.json`,
`data/font_alloc_4set.json`, the 62-string system TSV, simsun.ttc.
Paths in the script headers are machine-specific — adjust as needed.
Architecture details: [docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md).

v16f (planned): backfill the 1,138 translated system strings
(`texts/tsv/system_text/system_text_remaining_translated.tsv`); requires adapting
the non-standard seg2 tables of COMMU03/SGAMEN/SHOP (tbl[0]≠512) first.

### Scene-level verification image (historical, v12-era)

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

### 3. Glyph values + outline (v12 final; corrected by v16e evidence)

| Value | Meaning |
|-------|---------|
| 1 | Stroke body (white) |
| 8 | Right/bottom 1px stroke extension (shadow — critical for visibility on light backgrounds) |
| 0 | Background |

Pure value-1 glyphs "occasionally disappear" on light backgrounds.
Three variants were compared (none / 3-direction thick / right-bottom thin);
**right-bottom 2-direction thin outline** was chosen.

**v16e correction**: pixel-value statistics of the original glyphs (INIT seg7) show a
double peak **V=1 (24.9%, dark outline) + V=8 (25.9%, bright core)** with 9-15 at zero;
the outline structure is an **8-neighborhood ring** (80.9% coverage — not
"right-bottom 2-direction"). Text palette = INIT seg1 win0: [1]=(7,7,7) dark outline,
**[8]=(19,19,15) exactly the naming-screen panel background (must never be touched)**,
[9]=(20,21,22) gray-scale peak. The v16e SYSTEM font packs outline→V=1 + core→V=9
with INIT seg1/3/4 win0[9] whitened to 7FFF. See
[docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md).

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

**System text (seg2) encoding differs from main text** (deciphered in v16, see
[docs/v16_system_text_backfill.md](docs/v16_system_text_backfill.md)):
single byte 0x20-0xFF → small-font idx 0-223; `0x15 XX` → icon codes
(×=15 01 △=15 02 □=15 03 』=15 0A); `0x12/0x13` → main-font global pool.

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

1. **Read the docs**: `docs/cracking_analysis.md` (format/layout/capacity facts, Chinese) →
   `docs/clut_banking_design.md` (Path E architecture, Chinese) →
   `docs/v16_system_text_backfill.md` (v16 findings, Chinese) → [CHANGELOG.md](CHANGELOG.md)
2. **Run the tests**: `python -m unittest discover -s tests`
3. **Verify the font**: `dump_font.py` + `import_font.py` round-trip
4. **Reproduce the baseline**: `tools/bof4_v16e_build.py` → `bof4_v16e_demo_verify.py` +
   `bof4_v16e_full_verify.py` → compare SHA256 against the current baseline
5. **Continue with v16f**: backfill the 1,138 translated strings in
   `texts/tsv/system_text/system_text_remaining_translated.tsv`
   (requires adapting the non-standard seg2 tables of COMMU03/SGAMEN/SHOP), or continue with
   scene-text outlines / VRAM font-upload transform RE (see CHANGELOG v0.8.2 known limits)
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