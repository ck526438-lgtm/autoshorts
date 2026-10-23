"""Generated abstract backdrops.

Two jobs: make `autoshorts demo` produce a watchable video with zero accounts
and zero downloads, and give every run an offline floor so b-roll APIs cannot
block a render.
"""

from __future__ import annotations

import colorsys
import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

_VARIANTS = ("mesh", "streaks", "orbs", "grain")


def _seed(*parts: str) -> int:
    return int(hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:8], 16)


def _hue(seed: int, offset: float = 0.0) -> tuple[int, int, int]:
    h = ((seed % 360) / 360.0 + offset) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.42)
    return int(r * 255), int(g * 255), int(b * 255)


def generate(query: str, out: Path, width: int, height: int, variant: int = 0) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    seed = _seed(query, str(variant))
    rng = random.Random(seed)
    style = _VARIANTS[variant % len(_VARIANTS)]

    base = _hue(seed)
    accent = _hue(seed, 0.18)
    image = Image.new("RGB", (width, height), base)
    top = _hue(seed, 0.55)
    # Vertical gradient, drawn row by row (cheap, and no numpy dependency).
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        colour = tuple(int(top[i] * (1 - t) + base[i] * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=colour)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    if style == "orbs":
        for _ in range(7):
            radius = rng.randint(width // 8, width // 2)
            cx, cy = rng.randint(0, width), rng.randint(0, height)
            tint = accent if rng.random() < 0.5 else top
            od.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                       fill=(*tint, rng.randint(40, 110)))
    elif style == "streaks":
        for _ in range(16):
            y0 = rng.randint(-height // 3, height)
            thick = rng.randint(2, max(3, height // 40))
            tint = accent if rng.random() < 0.4 else base
            od.line([(0, y0), (width, y0 + rng.randint(height // 6, height // 2))],
                    fill=(*tint, rng.randint(28, 80)), width=thick)
    elif style == "mesh":
        step = max(60, width // 8)
        for x in range(0, width + step, step):
            tint = accent if (x // step) % 2 else top
            od.line([(x, 0), (x + rng.randint(-step, step), height)],
                    fill=(*tint, 42), width=2)
        for y in range(0, height + step, step):
            od.line([(0, y), (width, y + rng.randint(-step, step))], fill=(*base, 36), width=2)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=width // 14))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    # Film grain from an upsampled low-res noise field, drawn from our own RNG
    # (PIL's effect_noise ignores it, which would break reproducible renders).
    gw, gh = max(64, width // 8), max(64, height // 8)
    grain = Image.new("L", (gw, gh))
    grain.putdata([rng.randint(200, 255) if i % 97 else rng.randint(0, 60)
                   for i in range(gw * gh)])
    grain = grain.resize((width, height), Image.BILINEAR).convert("RGB")
    image = Image.blend(image, ImageChops.multiply(image, grain), 0.18)

    # Vignette keeps captions readable at the edges.
    mask = Image.new("L", (width, height), 0)
    md = ImageDraw.Draw(mask)
    cx, cy = width / 2, height / 2
    for radius in range(int(math.hypot(cx, cy)), 0, -12):
        alpha = int(255 * (radius / math.hypot(cx, cy)) ** 2 * 0.55)
        md.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                   fill=min(255, alpha))
    dark = Image.new("RGB", (width, height), (0, 0, 0))
    image = Image.composite(image, dark, ImageChops.invert(mask))
    image = Image.blend(image, ImageChops.multiply(image, Image.new("RGB", (width, height), (220, 220, 220))), 0.35)

    image.save(out, "PNG", optimize=True)
    return out
