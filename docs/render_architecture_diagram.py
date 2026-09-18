#!/usr/bin/env python3
"""Regenerate docs/architecture_flow.png from architecture_row{1,2}.mmd.

Renders each row separately via mermaid-cli (subgraph `direction LR` isn't
honoured reliably across mermaid-cli versions, so a single combined diagram
comes out far too tall), then stacks the two rows with labels using Pillow.

Usage:
    pip install pillow          # one-off dev tool, not a project dependency
    python docs/render_architecture_diagram.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

DOCS = pathlib.Path(__file__).resolve().parent
CONFIG = DOCS / "mermaid_config.json"
ROWS = [
    (DOCS / "architecture_row1.mmd", "Interpretation  (Siyam — app/interpretation/)"),
    (
        DOCS / "architecture_row2.mmd",
        "Energy & Verification  (Daddy — app/energy/, app/verification/)",
    ),
]
OUT = DOCS / "architecture_flow.png"

PAD, LABEL_H, GAP = 40, 70, 50


def render_row(mmd_path: pathlib.Path, out_path: pathlib.Path) -> None:
    subprocess.run(
        [
            "npx", "-y", "@mermaid-js/mermaid-cli",
            "-i", str(mmd_path), "-o", str(out_path),
            "-b", "white", "-s", "3", "-c", str(CONFIG),
        ],
        check=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        rendered = []
        for mmd_path, label in ROWS:
            row_png = tmp_path / f"{mmd_path.stem}.png"
            render_row(mmd_path, row_png)
            rendered.append((Image.open(row_png), label))

        width = max(img.width for img, _ in rendered) + PAD * 2
        height = sum(img.height + LABEL_H for img, _ in rendered) + GAP * (len(rendered) - 1) + PAD

        canvas = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
        except OSError:
            font = ImageFont.load_default()

        y = 10
        for i, (img, label) in enumerate(rendered):
            draw.text((PAD, y), label, fill="black", font=font)
            y += LABEL_H
            canvas.paste(img, ((width - img.width) // 2, y))
            y += img.height
            if i < len(rendered) - 1:
                y += GAP

        canvas.save(OUT)
        print(f"wrote {OUT} ({canvas.size[0]}x{canvas.size[1]})")


if __name__ == "__main__":
    sys.exit(main())
