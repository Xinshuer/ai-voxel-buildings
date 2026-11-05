"""Comparison sheet: one row per building, images side by side with a label under each
(e.g. old text-to-image concept, blockout, redraws at several strengths; or concept vs. voxel model render).

Usage:
  python compare_sheet.py --out work/compare.png --row "Hall" "Blockout=examples/blockouts/hall-single.png" "Strength 1.0=work/tests/example_hall-edit40.png"
                          [--row "Court" "Label=path" ...] [--height 420]
  python compare_sheet.py --out work/compare.png --spec sheet.json
spec JSON: [{"title": "Hall", "cells": [["Blockout", "path.png"], ["Redraw", "path2.png"]]}, ...]  (paths relative to the JSON)
Missing images are skipped. Labels can be in any language if a CJK-capable font is found.
"""
import argparse, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BG = (250, 247, 240)
GAP, LABEL = 16, 40
# Tried in order; Pillow searches the system font folders for bare file names.
FONTS = ["msyh.ttc", "NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf", "PingFang.ttc", "Hiragino Sans GB.ttc",
         "wqy-microhei.ttc", "DejaVuSans.ttf", "arial.ttf"]
FONTS_BOLD = ["msyhbd.ttc", "NotoSansCJK-Bold.ttc", "NotoSansCJKsc-Bold.otf"] + FONTS


def font(names, size, override=None):
    for n in ([override] if override else []) + names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser(description="Side-by-side comparison sheet.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--row", nargs="+", action="append", metavar=("TITLE", "LABEL=PATH"), help="a row: title then label=path cells")
    ap.add_argument("--spec", help="JSON spec instead of --row")
    ap.add_argument("--height", type=int, default=420, help="image height in each row (px)")
    ap.add_argument("--font", help="font file to use for labels")
    a = ap.parse_args()

    rows_in = []
    if a.spec:
        sp = Path(a.spec)
        for r in json.loads(sp.read_text("utf-8")):
            rows_in.append((r["title"], [(lab, sp.parent / p) for lab, p in r["cells"]]))
    for r in a.row or []:
        rows_in.append((r[0], [(c.split("=", 1)[0], Path(c.split("=", 1)[1])) for c in r[1:]]))
    if not rows_in:
        ap.error("give --row or --spec")

    H = a.height
    f_label, f_title = font(FONTS, 22, a.font), font(FONTS_BOLD, 28, a.font)
    rows = []
    for title, cells in rows_in:
        ims = [(lab, Image.open(p).convert("RGB")) for lab, p in cells if p.exists()]
        ims = [(lab, im.resize((int(im.width * H / im.height), H))) for lab, im in ims]
        w = sum(im.width for _, im in ims) + GAP * (len(ims) + 1)
        row = Image.new("RGB", (max(w, 400), H + LABEL + 50), BG)
        d = ImageDraw.Draw(row)
        d.text((GAP, 8), title, fill=(40, 40, 40), font=f_title)
        x = GAP
        for lab, im in ims:
            row.paste(im, (x, 50))
            d.text((x, 50 + H + 6), lab, fill=(60, 60, 60), font=f_label)
            x += im.width + GAP
        rows.append(row)
    W = max(r.width for r in rows)
    sheet = Image.new("RGB", (W, sum(r.height for r in rows)), BG)
    y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.out)
    print(a.out, sheet.size)


if __name__ == "__main__":
    main()
