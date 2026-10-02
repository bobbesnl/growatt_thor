"""Add numbered margin annotations to documentation PNGs without altering UI pixels.

Requires Pillow. Geometry and handbook destinations live in docs/images/annotations.json.
Explanations are edited directly in the handbook; this script writes only PNGs.
Set THOR_ANNOTATION_FONT to override the handwriting font on non-macOS systems.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / 'docs/images'
SCALE = 3
RED = (187, 62, 57, 255)


def font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        os.environ.get('THOR_ANNOTATION_FONT', ''),
        '/System/Library/Fonts/Supplemental/Chalkboard.ttc',
        'DejaVuSans.ttf',
    ]
    for name in candidates:
        if name:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
    raise RuntimeError('Set THOR_ANNOTATION_FONT to an available TrueType handwriting font')


def annotate(figure: dict) -> Path:
    original = Image.open(IMAGES / figure['source']).convert('RGBA')
    if list(original.size) != figure['source_size']:
        raise ValueError(f"Recheck annotation positions after resizing {figure['source']}")
    width, height = original.size
    unit = width / 1040
    gutter = math.ceil(126 * unit)
    # Supersample only the drawn margin. Never rescale or paint over screenshot pixels.
    margin = Image.new('RGBA', (gutter * SCALE, height * SCALE))
    draw = ImageDraw.Draw(margin)
    def line(points: list[tuple[float, float]], stroke: float = 3.1) -> None:
        draw.line([(round(x * SCALE), round(y * SCALE)) for x, y in points],
                  fill=RED, width=max(1, round(stroke * unit * SCALE)), joint='curve')
    last_bottom = 0
    for number, note in enumerate(figure['callouts'], 1):
        top, bottom = note['top'] * height, note['bottom'] * height
        if not 0 <= top < bottom <= height:
            raise ValueError(f"Invalid range in {figure['id']}, note {number}")
        cy = (top + bottom) / 2
        cx, radius = 80 * unit, 25 * unit
        if cy - radius < last_bottom:
            raise ValueError(f"Overlapping annotation numbers in {figure['id']}")
        last_bottom = cy + radius
        # A slightly uneven bracket and connector give the appearance of a pen stroke.
        line([(5 * unit, top + unit), (18 * unit, top), (17 * unit, top + 8 * unit),
              (19 * unit, cy), (17 * unit, bottom - 8 * unit),
              (18 * unit, bottom), (5 * unit, bottom - unit)])
        line([(19 * unit, cy + unit), (34 * unit, cy - unit), (52 * unit, cy)])
        circle = []
        for step in range(101):
            angle = step / 100 * 2 * math.pi
            r = radius * (1 + .028 * math.sin(3 * angle + number) + .018 * math.cos(5 * angle))
            circle.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        draw.polygon([(round(x * SCALE), round(y * SCALE)) for x, y in circle],
                     fill=(255, 249, 245, 255))
        line(circle, 3.4)
        draw.text((cx * SCALE, (cy - unit) * SCALE), str(number),
                  font=font(round(35 * unit * SCALE)), fill=RED, anchor='mm')
    margin = margin.resize((gutter, height), Image.Resampling.LANCZOS)
    result = Image.new('RGBA', (width + gutter, height))
    result.paste(original, (0, 0))
    result.paste(margin, (width, 0))
    assert result.crop((0, 0, width, height)).tobytes() == original.tobytes()
    output = IMAGES / 'annotated' / f"{figure['id']}.png"
    output.parent.mkdir(exist_ok=True)
    result.save(output, optimize=True)
    return output


def main() -> None:
    figures = json.loads((IMAGES / 'annotations.json').read_text())['figures']
    for figure in figures:
        document, anchor = figure['manual'].split('#', 1)
        manual = ROOT / 'docs' / document
        if f'<a id="{anchor}"></a>' not in manual.read_text():
            raise ValueError(f"Missing handbook destination: {figure['manual']}")
        annotate(figure)
    print(f"Created {len(figures)} annotated PNGs. Handbook prose was not modified.")


if __name__ == '__main__':
    main()
