"""Combine aligned documentation screenshots without changing their UI pixels.

Run after capture-docs.cjs. Requires Pillow (python -m pip install Pillow).
"""

from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    images = Path(__file__).resolve().parents[2] / "docs" / "images"
    light = Image.open(images / "01-charger-light.png").convert("RGBA")
    dark = Image.open(images / "02-charger-dark.png").convert("RGBA")
    if light.size != dark.size:
        raise ValueError("Light and dark screenshots must have identical dimensions")

    width, height = light.size
    # Smooth only the diagonal mask; keep the original screenshots at full size.
    scale = 4
    mask = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(mask).polygon(
        [(0, 0), (0, height * scale), (width * scale, 0)],
        fill=255,
    )
    mask = mask.resize(light.size, Image.Resampling.LANCZOS)
    result = Image.composite(light, dark, mask)
    destination = images / "charger-light-dark-split.png"
    result.save(destination, optimize=True)
    print(destination)


if __name__ == "__main__":
    main()
