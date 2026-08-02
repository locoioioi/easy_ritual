from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageOps


def normalize_icon(input_path: Path, output_path: Path, canvas_size: int = 64) -> tuple[int, int, str]:
    image = Image.open(input_path).convert("RGBA")
    bbox = _content_bbox(image)
    if bbox is not None:
        image = image.crop(bbox)
    image.thumbnail((canvas_size, canvas_size), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    x = (canvas_size - image.width) // 2
    y = (canvas_size - image.height) // 2
    canvas.alpha_composite(image, (x, y))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return image.width, image.height, average_hash(canvas)


def average_hash(image: Image.Image, hash_size: int = 8) -> str:
    gray = ImageOps.grayscale(image.convert("RGB")).resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    pixels = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= avg else "0" for pixel in pixels)
    return f"{int(bits, 2):0{hash_size * hash_size // 4}x}"


def _content_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    alpha_bbox = alpha.getbbox()
    if alpha_bbox is not None:
        return alpha_bbox

    background = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    diff = ImageChops.difference(image, background)
    return diff.getbbox()
