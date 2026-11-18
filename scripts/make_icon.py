"""
Generate the application icon.

The mark is a descending three-bar chart inside a green ring: it reads as
"resource usage going down" at 16 px without imitating Spotify's own logo.

Run:  python scripts/make_icon.py
Outputs: assets/icon.ico (16-256 px) and assets/icon.png (256 px).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

MASTER = 1024
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

GREEN = (30, 215, 96, 255)
GREEN_DIM = (24, 170, 78, 255)
WHITE = (245, 247, 250, 255)
TOP = (22, 27, 34)
BOTTOM = (11, 13, 16)


def _background() -> Image.Image:
    image = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (1, MASTER))
    for y in range(MASTER):
        ratio = y / (MASTER - 1)
        colour = tuple(
            round(TOP[i] + (BOTTOM[i] - TOP[i]) * ratio) for i in range(3)
        )
        gradient.putpixel((0, y), (*colour, 255))
    gradient = gradient.resize((MASTER, MASTER))

    mask = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, MASTER - 1, MASTER - 1], radius=224, fill=255
    )
    image.paste(gradient, (0, 0), mask)
    return image


def _draw_mark() -> Image.Image:
    image = _background()
    draw = ImageDraw.Draw(image)

    # Outer ring: the "measurement" frame.
    margin, ring = 118, 58
    draw.ellipse(
        [margin, margin, MASTER - margin, MASTER - margin],
        outline=GREEN_DIM, width=ring,
    )
    # Brighter cap on the upper-right quarter, so the ring is not flat.
    draw.arc(
        [margin, margin, MASTER - margin, MASTER - margin],
        start=-80, end=10, fill=GREEN, width=ring,
    )

    # Descending bars: tallest on the left, shortest on the right.
    bar_width, gap = 96, 44
    heights = (300, 208, 116)
    baseline = 706
    total = bar_width * 3 + gap * 2
    x = (MASTER - total) // 2
    for height in heights:
        draw.rounded_rectangle(
            [x, baseline - height, x + bar_width, baseline],
            radius=bar_width // 2,
            fill=WHITE,
        )
        x += bar_width + gap

    return image


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    master = _draw_mark()
    ico_path = assets / "icon.ico"
    png_path = assets / "icon.png"

    master.save(png_path, format="PNG")
    master.save(ico_path, format="ICO", sizes=SIZES)

    # Also write the exact 256 px frame for README rendering.
    master.resize((256, 256), Image.LANCZOS).save(png_path, format="PNG")

    print(f"icon written: {ico_path} ({ico_path.stat().st_size} bytes)")
    print(f"preview written: {png_path} ({png_path.stat().st_size} bytes)")
    print(f"sizes: {', '.join(f'{w}x{h}' for w, h in SIZES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
