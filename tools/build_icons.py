"""Regenerate the bundled application icons from the master artwork.

Run from the repository root::

    python tools/build_icons.py

The script reads ``app/assets/icon_source.png`` (the master artwork) and writes:

* ``app/assets/icon.png`` - runtime PNG with a squircle alpha mask.
* ``app/assets/icon.ico`` - real Windows icon (BMP entries for the small sizes,
  PNG entries for the large ones) so the taskbar and the PyInstaller executable
  pick a crisp bitmap instead of scaling one oversized image.

The master artwork is deliberately kept out of the PyInstaller bundle; only the
two generated files are shipped.
"""

from __future__ import annotations

import math
import struct
import sys
from io import BytesIO
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "app" / "assets"
SOURCE = ASSETS / "icon_source.png"
PNG_OUT = ASSETS / "icon.png"
ICO_OUT = ASSETS / "icon.ico"

PNG_SIZE = 256
ICO_SIZES: Tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)
BMP_SIZES: Tuple[int, ...] = (16, 24, 32, 48, 64)
SQUIRCLE_EXPONENT = 4.0
SUPERSAMPLE = 4


def squircle_mask(size: int) -> Image.Image:
    """
    Build an antialiased squircle (superellipse) alpha mask.

    Args:
        size: Width and height of the returned mask.

    Returns:
        Image: ``L`` mode mask, white inside the shape and black outside.
    """
    big = size * SUPERSAMPLE
    points: List[Tuple[float, float]] = []
    steps = 720
    power = 2.0 / SQUIRCLE_EXPONENT
    for index in range(steps):
        angle = 2.0 * math.pi * index / steps
        cos_t, sin_t = math.cos(angle), math.sin(angle)
        x = math.copysign(abs(cos_t) ** power, cos_t)
        y = math.copysign(abs(sin_t) ** power, sin_t)
        points.append((big / 2.0 + x * big / 2.0, big / 2.0 + y * big / 2.0))

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def build_artwork(source: Path) -> Image.Image:
    """
    Load the master artwork and apply the squircle alpha mask.

    Args:
        source: Path of the master PNG.

    Returns:
        Image: Square ``RGBA`` artwork masked with the squircle shape.
    """
    with Image.open(source) as raw:
        artwork = raw.convert("RGBA")

    side = max(artwork.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(artwork, ((side - artwork.width) // 2, (side - artwork.height) // 2))
    square.putalpha(squircle_mask(side))
    return square


def write_png(artwork: Image.Image, target: Path) -> None:
    """
    Write the runtime PNG used by the UI and by non-Windows window managers.

    Args:
        artwork: Masked ``RGBA`` artwork.
        target: Destination file path.
    """
    png = artwork.resize((PNG_SIZE, PNG_SIZE), Image.Resampling.LANCZOS)
    png.save(target, format="PNG", optimize=True)


def _bmp_entry(image: Image.Image) -> bytes:
    """
    Encode an image as a 32-bit ``BITMAPINFOHEADER`` icon entry.

    Args:
        image: ``RGBA`` image to encode.

    Returns:
        bytes: DIB payload including the AND mask.
    """
    width, height = image.size
    flipped = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    pixels = flipped.tobytes("raw", "BGRA")

    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height * 2,
        1,
        32,
        0,
        len(pixels),
        0,
        0,
        0,
        0,
    )

    stride = ((width + 31) // 32) * 4
    alpha = image.getchannel("A").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    alpha_pixels = alpha.load()
    mask = bytearray(stride * height)
    if alpha_pixels is None:
        return header + pixels + bytes(mask)
    for y in range(height):
        row = bytearray(stride)
        for x in range(width):
            pixel = alpha_pixels[x, y]
            if pixel is None:
                continue
            if pixel == 0:
                row[x // 8] |= 0x80 >> (x % 8)
        mask[y * stride:(y + 1) * stride] = row

    return header + pixels + bytes(mask)


def _png_entry(image: Image.Image) -> bytes:
    """
    Encode an image as a PNG-compressed icon entry.

    Args:
        image: ``RGBA`` image to encode.

    Returns:
        bytes: PNG payload.
    """
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def write_ico(artwork: Image.Image, target: Path) -> None:
    """
    Write a multi-resolution Windows icon.

    Small sizes use 32-bit BMP entries for maximum shell compatibility, large
    sizes use PNG entries to keep the file small.

    Args:
        artwork: Masked ``RGBA`` artwork.
        target: Destination file path.
    """
    frames: List[Tuple[int, bytes, bool]] = []
    for size in ICO_SIZES:
        resized = artwork.resize((size, size), Image.Resampling.LANCZOS)
        if size in BMP_SIZES:
            frames.append((size, _bmp_entry(resized), False))
        else:
            frames.append((size, _png_entry(resized), True))

    count = len(frames)
    directory = BytesIO()
    directory.write(struct.pack("<HHH", 0, 1, count))
    offset = 6 + count * 16
    payloads = BytesIO()
    for size, payload, is_png in frames:
        directory.write(
            struct.pack(
                "<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        offset += len(payload)
        payloads.write(payload)

    target.write_bytes(directory.getvalue() + payloads.getvalue())


def main() -> int:
    """
    Rebuild the PNG and ICO assets from the master artwork.

    Returns:
        int: Process exit code.
    """
    if not SOURCE.is_file():
        print(f"error: master artwork not found at {SOURCE}", file=sys.stderr)
        return 1

    artwork = build_artwork(SOURCE)
    write_png(artwork, PNG_OUT)
    write_ico(artwork, ICO_OUT)

    print(f"wrote {PNG_OUT.relative_to(ROOT)} ({PNG_OUT.stat().st_size} bytes)")
    print(f"wrote {ICO_OUT.relative_to(ROOT)} ({ICO_OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
