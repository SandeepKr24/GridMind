"""Turn team logo images into the small tiles the site shows beside team names.

    backend/.venv/Scripts/python frontend/scripts/team-tiles.py

Reads every image in Logo/teams/ (gitignored source artwork, named by team key:
mclaren.jpg, red_bull.png, ...) and writes frontend/public/teams/<key>.png.

Each logo is cropped to its content, centred on a square of its own background
colour, given rounded corners and saved at 64px, which stays sharp at the
20px display size on high-density screens. Nothing inside the logo is changed:
the background is detected from the corners, never removed.

Needs Pillow, which the backend's virtualenv already has.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Logo" / "teams"
OUTPUT = ROOT / "frontend" / "public" / "teams"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SIZE = 64
#: Breathing room around the logo, as a share of the tile.
MARGIN = 0.12
CORNER_RADIUS = 14
#: How far (0-255) a pixel must differ from the background to count as logo.
#: High enough to ignore JPEG noise around the edges.
THRESHOLD = 40


def background_of(image: Image.Image) -> tuple[int, int, int]:
    """The median of the four corner pixels: logos are centred, corners are not."""
    w, h = image.size
    corners = [image.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    return tuple(sorted(channel)[1] for channel in zip(*corners))  # type: ignore[return-value]


def content_box(image: Image.Image, background: tuple[int, int, int]) -> tuple[int, int, int, int]:
    plain = Image.new("RGB", image.size, background)
    diff = ImageChops.difference(image, plain).convert("L")
    mask = diff.point(lambda value: 255 if value > THRESHOLD else 0)
    return mask.getbbox() or (0, 0, *image.size)


def make_tile(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    background = background_of(image)
    logo = image.crop(content_box(image, background))

    inner = round(SIZE * (1 - 2 * MARGIN))
    logo.thumbnail((inner * 4, inner * 4))  # keep detail for the final downscale
    side = max(logo.size)
    square = Image.new("RGB", (side, side), background)
    square.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2))

    padded_side = round(side / (1 - 2 * MARGIN))
    padded = Image.new("RGB", (padded_side, padded_side), background)
    offset = (padded_side - side) // 2
    padded.paste(square, (offset, offset))
    tile = padded.resize((SIZE, SIZE), Image.LANCZOS).convert("RGBA")

    corners = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(corners).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), CORNER_RADIUS, fill=255)
    tile.putalpha(corners)
    return tile


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources = sorted(p for p in SOURCE.iterdir() if p.suffix.lower() in EXTENSIONS)
    if not sources:
        raise SystemExit(f"no images in {SOURCE}")
    for path in sources:
        target = OUTPUT / f"{path.stem.lower()}.png"
        make_tile(path).save(target, optimize=True)
        print(f"{path.name:22} -> {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
