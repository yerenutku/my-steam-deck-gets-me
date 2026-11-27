#!/usr/bin/env python3
"""Draws the WowVoice wheel artwork (concept B "Recessed Stone Wedge", design/handoff/radial-handoff) as
separate transparent layers, and a preview composite to compare with the reference.

Layers (512x512 unless noted, centre (256,256), radii from the handoff: outer 238, ring inner 210, hub 48):
  wheel_base     segmented leather disk + gold dividers + moss rune ring + 4 diamond ornaments
  wedge_stone    the recessed grey stone wedge, drawn pointing NORTH (the addon rotates it to NW)
  wedge_select   amber selected wedge with bright edge, pointing NORTH (rotated to the selection)
  line           directional line from the hub with a bright tip, pointing NORTH (rotated)
  hub            dark joystick hub with bronze rim
  icon_<name>    128x128 icons
  hintbar        512x64 plate for the hint text
WoW loads 32-bit TGA with power-of-two sizes. Text is NOT baked: the addon writes it with WoW's font.

Run: envs/nemo/bin/python design/build_wheel.py [--out DIR] [--preview FILE] [--select N] [--sub]
"""

import argparse
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 4                                   # supersampling for smooth edges
SIZE = 512
C = SIZE / 2
R_OUT, R_RING, R_HUB = 238, 210, 48
R_SEG_IN = 58                            # segments start just outside the hub rim
COL = dict(bg=(0x21, 0x1B, 0x18), seg=(0x35, 0x29, 0x1F), border=(0x9D, 0x72, 0x2B), ring=(0x4B, 0x50, 0x1E),
           rune=(0xD2, 0xB7, 0x3E), stone=(0x77, 0x78, 0x73), sel=(0xE6, 0xA9, 0x1B), edge=(0xFF, 0xD7, 0x65),
           text=(0xF8, 0xEF, 0xD6))
HERE = Path(__file__).resolve().parent
def _find_wow():
    """WoW Forever's folder inside any Proton prefix (the compatdata id differs per install)."""
    hits = sorted((Path.home() / ".local/share/Steam/steamapps/compatdata").glob(
        "*/pfx/drive_c/Program Files (x86)/World of Warcraft/_forever_"))
    return hits[0] if hits else Path.home() / "World of Warcraft/_forever_"


ADDON = HERE.parent / "addon/MySteamDeckGetsMe/Media"   # the repo's addon (the source)


def canvas(w=SIZE, h=SIZE):
    return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))


def done(img, w=SIZE, h=SIZE):
    return img.resize((w, h), Image.LANCZOS)


def pt(r, deg, c=C):
    """polar -> canvas (supersampled); 0 deg = north, clockwise."""
    a = math.radians(deg)
    return ((c + r * math.sin(a)) * SS, (c - r * math.cos(a)) * SS)


def wedge_poly(r0, r1, a0, a1, steps=48, c=C):
    pts = [pt(r1, a0 + (a1 - a0) * i / steps, c) for i in range(steps + 1)]
    pts += [pt(r0, a1 - (a1 - a0) * i / steps, c) for i in range(steps + 1)]
    return pts


def noise(size, scale, seed):
    rng = np.random.default_rng(seed)
    n = rng.random((size // scale + 2, size // scale + 2))
    img = Image.fromarray((n * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(scale / 3)), dtype=np.float32) / 255


def textured(mask, base, var, seed, grain=6):
    """Fill `mask` (L image) with colour `base` modulated by layered noise (leather/stone look)."""
    w, h = mask.size
    m = max(w, h)                                        # noise is square: make it big enough, then crop
    n = 0.55 * noise(m, 48 * SS // 4, seed) + 0.3 * noise(m, 12 * SS // 4, seed + 1) + 0.15 * noise(m, grain, seed + 2)
    n = n[:h, :w]
    rgb = np.clip(np.array(base, np.float32)[None, None, :] * (1 - var / 2 + var * n[..., None]), 0, 255)
    out = Image.fromarray(rgb.astype(np.uint8), "RGB").convert("RGBA")
    out.putalpha(mask)
    return out


def radial_shade(img, inner=0.85, outer=1.0, r0=0, r1=R_RING):
    """Darken towards the outside of the disk (a bit of depth)."""
    w, h = img.size
    y, x = np.mgrid[0:h, 0:w]
    r = np.hypot(x - w / 2, y - h / 2) / SS
    f = np.clip((r - r0) / max(1, r1 - r0), 0, 1)
    k = inner + (outer - inner) * (1 - f) ** 0.7
    a = np.asarray(img, np.float32)
    a[..., :3] *= k[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


# ----------------------------------------------------------------- layers
def wheel_base(n_sectors=8, seed=7):
    img = canvas()
    d0 = ImageDraw.Draw(img)                           # solid backing under the hub: no see-through seam
    d0.ellipse(S(C - R_SEG_IN - 6, C - R_SEG_IN - 6, C + R_SEG_IN + 6, C + R_SEG_IN + 6), fill=(*COL["bg"], 255))
    # leather segments
    for i in range(n_sectors):
        a0, a1 = i * 360 / n_sectors - 180 / n_sectors, (i + 1) * 360 / n_sectors - 180 / n_sectors
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).polygon(wedge_poly(R_SEG_IN, R_RING, a0, a1), fill=255)
        tone = tuple(int(c * (1.02 + 0.14 * random.Random(seed + i).random())) for c in COL["seg"])
        img.alpha_composite(textured(m, tone, 0.75, seed + 10 * i, grain=3))
    img = radial_shade(img, 0.62, 1.12, R_SEG_IN, R_RING)
    d = ImageDraw.Draw(img)
    # dividers: thin aged gold, from outside the hub to the ring
    for i in range(n_sectors):
        a = i * 360 / n_sectors - 180 / n_sectors
        d.line([pt(R_SEG_IN + 4, a), pt(R_RING - 2, a)], fill=(*COL["border"], 255), width=int(2.2 * SS))
        d.line([pt(R_SEG_IN + 4, a + 0.35), pt(R_RING - 2, a + 0.35)], fill=(255, 215, 120, 70), width=int(0.8 * SS))
    # moss rune ring
    ring = Image.new("L", img.size, 0)
    rd = ImageDraw.Draw(ring)
    rd.ellipse([(C - R_OUT) * SS, (C - R_OUT) * SS, (C + R_OUT) * SS, (C + R_OUT) * SS], fill=255)
    rd.ellipse([(C - R_RING) * SS, (C - R_RING) * SS, (C + R_RING) * SS, (C + R_RING) * SS], fill=0)
    moss = textured(ring, COL["ring"], 0.6, seed + 99, grain=3)
    img.alpha_composite(moss)
    d = ImageDraw.Draw(img)
    for r, w, col in ((R_OUT, 3.2, COL["border"]), (R_OUT - 2.5, 1.0, (255, 220, 130)), (R_RING + 1, 3.0, COL["border"]),
                      (R_RING - 2, 1.4, (40, 28, 16))):
        d.ellipse([(C - r) * SS, (C - r) * SS, (C + r) * SS, (C + r) * SS], outline=(*col, 255), width=int(w * SS))
    # runes: small angular glyphs, restrained gold
    rr = random.Random(seed)
    for k in range(32):
        a = k * 360 / 32 + 360 / 64
        if min(abs(((a - q) + 180) % 360 - 180) for q in (0, 90, 180, 270)) < 8:
            continue                                   # leave room for the diamonds
        cx, cy = pt((R_RING + R_OUT) / 2, a)
        s = 5.2 * SS
        strokes = rr.sample([((-1, -1), (1, 1)), ((-1, 1), (1, -1)), ((0, -1.2), (0, 1.2)), ((-1, 0), (1, 0)),
                             ((-1, -1), (0, 1)), ((0, 1), (1, -1)), ((-1, 1), (0, -1)), ((0, -1), (1, 1))], 2)
        rot = math.radians(a)
        for (x0, y0), (x1, y1) in strokes:
            p0 = (cx + s * (x0 * math.cos(rot) - y0 * math.sin(rot)), cy + s * (x0 * math.sin(rot) + y0 * math.cos(rot)))
            p1 = (cx + s * (x1 * math.cos(rot) - y1 * math.sin(rot)), cy + s * (x1 * math.sin(rot) + y1 * math.cos(rot)))
            d.line([p0, p1], fill=(*COL["rune"], 235), width=int(1.6 * SS))
    # diamonds N E S W
    for a in (0, 90, 180, 270):
        cx, cy = pt((R_RING + R_OUT) / 2, a)
        for scale, fill in ((17, (60, 42, 18, 255)), (15, (*COL["border"], 255)), (12, (255, 214, 110, 255)),
                            (9, (70, 110, 30, 255)), (6, (150, 200, 60, 255)), (2.5, (230, 255, 170, 255))):
            s = scale * SS
            d.polygon([(cx, cy - s * 1.25), (cx + s, cy), (cx, cy + s * 1.25), (cx - s, cy)], fill=fill)
    return done(img)


def wedge_stone(n=8, seed=3):
    img = canvas()
    half = 180 / n
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).polygon(wedge_poly(R_SEG_IN + 2, R_RING - 3, -half + 1, half - 1), fill=255)
    stone = textured(m, tuple(int(c * 0.82) for c in COL["stone"]), 0.6, seed, grain=3)
    stone = radial_shade(stone, 0.8, 1.0, R_SEG_IN, R_RING)
    img.alpha_composite(stone)
    d = ImageDraw.Draw(img)
    # recessed bevel: dark top-left edge, light bottom-right edge
    d.line(wedge_poly(R_RING - 4, R_RING - 4, -half + 1, half - 1)[:49], fill=(40, 40, 38, 220), width=int(4 * SS))
    d.line([pt(R_SEG_IN + 3, -half + 1.5), pt(R_RING - 4, -half + 1.5)], fill=(45, 45, 42, 220), width=int(4 * SS))
    d.line([pt(R_SEG_IN + 3, half - 1.5), pt(R_RING - 4, half - 1.5)], fill=(190, 190, 182, 200), width=int(3 * SS))
    d.line(wedge_poly(R_SEG_IN + 3, R_SEG_IN + 3, -half + 1, half - 1)[:49], fill=(200, 200, 190, 160), width=int(3 * SS))
    return done(img)


def wedge_select(n=8):
    img = canvas()
    half = 180 / n
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(wedge_poly(R_SEG_IN - 2, R_RING + 2, -half - 1, half + 1), fill=(255, 190, 40, 200))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(7 * SS)))
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).polygon(wedge_poly(R_SEG_IN + 1, R_RING - 2, -half + 0.6, half - 0.6), fill=255)
    fill = textured(m, (236, 150, 22), 0.22, 5, grain=4)
    w_, h_ = fill.size
    yy, xx = np.mgrid[0:h_, 0:w_]
    rr = np.clip((np.hypot(xx - w_ / 2, yy - h_ / 2) / SS - R_SEG_IN) / (R_RING - R_SEG_IN), 0, 1)
    a = np.asarray(fill, np.float32).copy()
    k = 0.55 + 0.6 * rr ** 1.3                                     # dark amber inside, bright at the rim
    a[..., 0] *= k; a[..., 1] *= k * (0.85 + 0.25 * rr); a[..., 2] *= k * 0.8
    a[..., 3] *= 0.9
    a = np.clip(a, 0, 255).astype(np.uint8)
    img.alpha_composite(Image.fromarray(a, "RGBA"))
    d = ImageDraw.Draw(img)
    d.line(wedge_poly(R_SEG_IN + 1, R_RING - 2, -half + 0.6, half - 0.6) + [pt(R_RING - 2, -half + 0.6)],
           fill=(*COL["edge"], 255), width=int(3.2 * SS), joint="curve")
    return done(img)


def wedge_active(n=8):
    """The ACTIVE destination: green wedge with a bright green edge, pointing NORTH (rotated in-game)."""
    img = canvas()
    half = 180 / n
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(wedge_poly(R_SEG_IN - 2, R_RING + 2, -half - 1, half + 1), fill=(70, 230, 90, 150))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6 * SS)))
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).polygon(wedge_poly(R_SEG_IN + 1, R_RING - 2, -half + 0.6, half - 0.6), fill=255)
    fill = textured(m, (34, 120, 46), 0.25, 9, grain=4)
    w_, h_ = fill.size
    yy, xx = np.mgrid[0:h_, 0:w_]
    rr = np.clip((np.hypot(xx - w_ / 2, yy - h_ / 2) / SS - R_SEG_IN) / (R_RING - R_SEG_IN), 0, 1)
    a = np.asarray(fill, np.float32).copy()
    k = 0.6 + 0.55 * rr ** 1.2                             # darker at the hub, brighter at the rim
    a[..., :3] *= k[..., None]
    a[..., 3] *= 0.92
    img.alpha_composite(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA"))
    d = ImageDraw.Draw(img)
    d.line(wedge_poly(R_SEG_IN + 1, R_RING - 2, -half + 0.6, half - 0.6) + [pt(R_RING - 2, -half + 0.6)],
           fill=(120, 255, 130, 255), width=int(3 * SS), joint="curve")
    return done(img)


def active_tag():
    """256x64 tag for the word ACTIVE (text by the addon): dark green, bright green border, angled ends."""
    w, h = 256, 64
    img = canvas(w, h)
    pts = [(10, h / 2), (30, 10), (w - 30, 10), (w - 10, h / 2), (w - 30, h - 10), (30, h - 10)]
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon([(x * SS, y * SS) for x, y in pts], outline=(90, 240, 100, 200), width=6 * SS)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3 * SS)))
    d = ImageDraw.Draw(img)
    d.polygon([(x * SS, y * SS) for x, y in pts], fill=(16, 60, 22, 240))
    d.line([(x * SS, y * SS) for x, y in pts + pts[:1]], fill=(110, 250, 120, 255), width=3 * SS, joint="curve")
    inner = [(18, h / 2), (34, 16), (w - 34, 16), (w - 18, h / 2), (w - 34, h - 16), (34, h - 16)]
    d.line([(x * SS, y * SS) for x, y in inner + inner[:1]], fill=(60, 160, 70, 160), width=1 * SS)
    return done(img, w, h)


def line_layer():
    img = canvas()
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line([pt(R_HUB - 6, 0), pt(148, 0)], fill=(255, 190, 50, 230), width=int(9 * SS))
    gd.ellipse([pt(148, 0)[0] - 13 * SS, pt(148, 0)[1] - 13 * SS, pt(148, 0)[0] + 13 * SS, pt(148, 0)[1] + 13 * SS],
               fill=(255, 200, 60, 230))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5 * SS)))
    d = ImageDraw.Draw(img)
    d.line([pt(R_HUB - 6, 0), pt(148, 0)], fill=(255, 232, 150, 255), width=int(4 * SS))
    x, y = pt(148, 0)
    d.ellipse([x - 7 * SS, y - 7 * SS, x + 7 * SS, y + 7 * SS], fill=(255, 245, 200, 255))
    return done(img)


def hub():
    img = canvas()
    d = ImageDraw.Draw(img)
    c = C * SS
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([c - 62 * SS, c - 58 * SS, c + 62 * SS, c + 66 * SS], fill=(0, 0, 0, 170))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6 * SS)))
    d = ImageDraw.Draw(img)
    for r, col in ((R_HUB + 10, (70, 46, 20)), (R_HUB + 8, (176, 122, 52)), (R_HUB + 5, (120, 80, 34)),
                   (R_HUB + 2, (210, 160, 80)), (R_HUB, (24, 22, 21))):
        d.ellipse([c - r * SS, c - r * SS, c + r * SS, c + r * SS], fill=(*col, 255))
    # glossy dark knob
    y, x = np.mgrid[0:SIZE * SS, 0:SIZE * SS]
    rr = np.hypot(x - c, y - c) / SS
    hl = np.hypot(x - (c - 14 * SS), y - (c - 16 * SS)) / SS
    a = np.asarray(img, np.float32)
    inside = rr < R_HUB - 1
    shade = np.clip(0.55 + 0.45 * (1 - rr / R_HUB), 0, 1)
    gloss = np.clip(1 - hl / 26, 0, 1) ** 2 * 90
    a[..., 0] = np.where(inside, 30 * shade + gloss, a[..., 0])
    a[..., 1] = np.where(inside, 28 * shade + gloss, a[..., 1])
    a[..., 2] = np.where(inside, 27 * shade + gloss, a[..., 2])
    # dithering: the dark gradient has only ~15 levels; without noise it shows as bands/steps on the Deck screen
    rng = np.random.default_rng(3)
    a[..., :3] += np.where(inside[..., None], rng.normal(0, 1.6, a[..., :3].shape), 0)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    d = ImageDraw.Draw(img)
    d.ellipse([c - (R_HUB - 6) * SS, c - (R_HUB - 6) * SS, c + (R_HUB - 6) * SS, c + (R_HUB - 6) * SS],
              outline=(0, 0, 0, 120), width=int(2 * SS))
    full = done(img)
    # only the middle, at a higher resolution (a mostly empty 512 layer scaled down shimmered): 136 units -> 256 px
    half = 68
    return full.crop((C - half, C - half, C + half, C + half)).resize((256, 256), Image.LANCZOS)


# ----------------------------------------------------------------- icons (128x128)
I = 128


def icon_canvas():
    return Image.new("RGBA", (I * SS, I * SS), (0, 0, 0, 0))


def icon_done(img):
    img = img.resize((I, I), Image.LANCZOS)
    a = np.asarray(img)
    shadow = Image.fromarray(np.dstack([np.zeros_like(a[..., :3]), (a[..., 3] * 0.75).astype(np.uint8)]), "RGBA")
    out = Image.new("RGBA", (I, I), (0, 0, 0, 0))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2.5)), (2, 3))
    out.alpha_composite(img)
    return out


def S(*v):
    return [x * SS for x in v]


def shade(col, k):
    return tuple(max(0, min(255, int(c * k))) for c in col[:3]) + (255,)


def bubble(d, box, col, tail="left"):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(S(x0, y0, x1, y1), radius=(y1 - y0) * 0.45 * SS, fill=shade(col, 1), outline=shade(col, 0.55),
                        width=3 * SS)
    tx = x0 + (x1 - x0) * (0.25 if tail == "left" else 0.75)
    tip = (tx - 14, y1 + 16) if tail == "left" else (tx + 14, y1 + 16)
    d.polygon([*S(tx - 9, y1 - 4), *S(tx + 9, y1 - 4), *S(*tip)], fill=shade(col, 1))
    d.line([*S(tx - 9, y1 - 1), *S(*tip), *S(tx + 9, y1 - 1)], fill=shade(col, 0.55), width=3 * SS)


def person(d, cx, cy, s, col):
    d.ellipse(S(cx - 10 * s, cy - 26 * s, cx + 10 * s, cy - 6 * s), fill=shade(col, 1), outline=shade(col, 0.55), width=2 * SS)
    d.pieslice(S(cx - 19 * s, cy - 2 * s, cx + 19 * s, cy + 36 * s), 180, 360, fill=shade(col, 1), outline=shade(col, 0.55),
               width=2 * SS)


def icon(name):
    img = icon_canvas()
    d = ImageDraw.Draw(img)
    if name == "say":
        bubble(d, (18, 26, 110, 86), (241, 227, 192))
        for x in (44, 64, 84):
            d.ellipse(S(x - 6, 50, x + 6, 62), fill=(60, 48, 36, 255))
    elif name == "whisper":
        bubble(d, (40, 18, 116, 66), (150, 100, 210), "right")
        bubble(d, (12, 46, 88, 96), (190, 140, 240))
    elif name in ("party", "friends", "raid"):
        col = {"party": (110, 150, 255), "friends": (245, 168, 60), "raid": (240, 120, 80)}[name]  # party = chat blue
        n = 5 if name == "raid" else 3
        xs = [30, 98, 64] if n == 3 else [20, 108, 40, 88, 64]
        ys = [62, 62, 76] if n == 3 else [56, 56, 66, 66, 80]
        sc = [1.2, 1.2, 1.45] if n == 3 else [0.95, 0.95, 1.1, 1.1, 1.35]
        for x, y, s in zip(xs, ys, sc):
            person(d, x, y, s, col)
    elif name in ("recent", "person"):
        person(d, 54, 70, 1.7, (241, 227, 192))
        if name == "recent":
            d.ellipse(S(80, 14, 122, 56), fill=(70, 150, 80, 255), outline=(230, 245, 210, 255), width=3 * SS)
            d.line(S(101, 23, 101, 47), fill=(240, 255, 230, 255), width=6 * SS)
            d.line(S(89, 35, 113, 35), fill=(240, 255, 230, 255), width=6 * SS)
    elif name == "guild":
        col = (72, 200, 80)                                  # guild chat green
        d.polygon(S(24, 18, 104, 18, 104, 62, 64, 112, 24, 62), fill=shade(col, 1), outline=shade(col, 0.5))
        d.line(S(24, 18, 104, 18, 104, 62, 64, 112, 24, 62, 24, 18), fill=shade(col, 0.5), width=4 * SS)
        d.polygon(S(38, 30, 90, 30, 90, 60, 64, 92, 38, 60), fill=(24, 80, 30, 255))
        d.polygon(S(52, 40, 76, 40, 76, 66, 64, 58, 52, 66), fill=(235, 190, 70, 255))
    elif name == "world":
        col = (93, 168, 232)
        d.ellipse(S(16, 16, 112, 112), fill=shade(col, 1), outline=shade(col, 0.5), width=4 * SS)
        for k in (0.35, 0.7):
            d.ellipse(S(64 - 48 * k, 16, 64 + 48 * k, 112), outline=(235, 245, 255, 220), width=3 * SS)
        for yy, w in ((40, 40), (64, 48), (88, 40)):
            d.line(S(64 - w, yy, 64 + w, yy), fill=(235, 245, 255, 220), width=3 * SS)
        d.line(S(64, 16, 64, 112), fill=(235, 245, 255, 220), width=3 * SS)
    elif name == "options":
        col = (205, 205, 200)
        cx = cy = 64
        teeth = []
        for k in range(16):
            a = math.radians(k * 22.5)
            r = 48 if k % 2 == 0 else 36
            for da in (-7, 7):
                b = a + math.radians(da)
                teeth.append(((cx + r * math.sin(b)) * SS, (cy - r * math.cos(b)) * SS))
        d.polygon(teeth, fill=shade(col, 1), outline=shade(col, 0.45))
        d.ellipse(S(cx - 16, cy - 16, cx + 16, cy + 16), fill=(70, 70, 68, 255), outline=shade(col, 0.45), width=3 * SS)
    elif name == "commands":
        col = (240, 200, 90)
        d.polygon(S(70, 10, 30, 70, 60, 70, 50, 118, 98, 52, 66, 52, 82, 10), fill=shade(col, 1), outline=shade(col, 0.5))
    elif name == "channel":
        col = (241, 227, 192)
        for x in (48, 78):
            d.line(S(x + 6, 22, x - 6, 106), fill=shade(col, 1), width=10 * SS)
        for y in (48, 80):
            d.line(S(24, y, 108, y), fill=shade(col, 1), width=10 * SS)
    elif name == "battleground":
        col = (225, 225, 230)
        for a, b in (((22, 22), (106, 106)), ((106, 22), (22, 106))):
            d.line(S(*a, *b), fill=shade(col, 1), width=10 * SS)
        for x, y in ((30, 86), (98, 86)):
            d.line(S(x - 14, y - 14, x + 14, y + 14) if x < 64 else S(x + 14, y - 14, x - 14, y + 14),
                   fill=(150, 100, 40, 255), width=12 * SS)
    elif name == "back":                                     # "Back" in the sub-rings (stone sector)
        col = (225, 225, 218)
        d.polygon(S(16, 64, 58, 24, 58, 48, 108, 48, 108, 80, 58, 80, 58, 104), fill=shade(col, 1), outline=shade(col, 0.45))
    elif name == "clock":                                    # timing options
        col = (241, 227, 192)
        d.ellipse(S(18, 18, 110, 110), fill=shade(col, 1), outline=shade(col, 0.5), width=4 * SS)
        d.line(S(64, 64, 64, 32), fill=(60, 48, 36, 255), width=6 * SS)
        d.line(S(64, 64, 86, 76), fill=(60, 48, 36, 255), width=6 * SS)
    return icon_done(img)


ICONS = ["say", "party", "raid", "battleground", "guild", "whisper", "friends", "recent", "world", "options",
         "person", "channel", "commands", "clock", "back"]


def hintbar():
    w, h = 512, 64
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(S(6, 8, w - 6, h - 8), radius=22 * SS, fill=(28, 22, 18, 235), outline=(*COL["border"], 255),
                        width=3 * SS)
    d.rounded_rectangle(S(11, 13, w - 11, h - 13), radius=18 * SS, outline=(255, 215, 120, 90), width=1 * SS)
    return done(img, w, h)


# ----------------------------------------------------------------- controller glyphs (from Steam's own set)
GLYPH_COL = {"r4": (240, 170, 40), "rstick": (110, 185, 255)}       # amber R4, blue stick


def tint(img, col):
    a = np.asarray(img.convert("RGBA")).astype(np.float32)
    out = np.zeros_like(a)
    out[..., :3] = np.array(col, np.float32)
    out[..., 3] = a[..., 3] * (a[..., :3].mean(axis=2) / 255)     # keep the knockout letters see-through
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def glyph(name):
    """Our own R4 badge (64x64), drawn here so nothing of Valve's has to be shipped. The right stick comes from
    WoW itself (atlas gamepad-xbox1-stick-r3-normal), so it isn't drawn."""
    w = 256
    img = canvas(w, w)
    d = ImageDraw.Draw(img)
    col = GLYPH_COL["r4"]
    d.rounded_rectangle(S(14, 34, 242, 222), radius=46 * SS, fill=col + (255,), outline=shade(col, 0.55), width=8 * SS)
    d.rounded_rectangle(S(26, 46, 230, 210), radius=36 * SS, outline=(255, 235, 170, 140), width=3 * SS)
    font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 122 * SS)
    tb = d.textbbox((0, 0), "R4", font=font)
    d.text(((w * SS - (tb[2] - tb[0])) / 2 - tb[0], (w * SS - (tb[3] - tb[1])) / 2 - tb[1] + 2 * SS), "R4", font=font,
           fill=(40, 28, 16, 255))
    return done(img, w, w).resize((128, 128), Image.LANCZOS)


def button_glyph(letter, col):
    """Round face button (A green, B red), 128 px: used inline in the box's tooltip pill."""
    w = 256
    img = canvas(w, w)
    d = ImageDraw.Draw(img)
    d.ellipse(S(14, 14, 242, 242), fill=shade(col, 0.35))
    d.ellipse(S(22, 22, 234, 234), fill=col + (255,), outline=shade(col, 0.55), width=6 * SS)
    d.ellipse(S(34, 34, 222, 222), outline=(255, 255, 255, 90), width=3 * SS)
    font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 140 * SS)
    tb = d.textbbox((0, 0), letter, font=font)
    d.text(((w * SS - (tb[2] - tb[0])) / 2 - tb[0], (w * SS - (tb[3] - tb[1])) / 2 - tb[1]), letter, font=font,
           fill=(255, 255, 255, 255), stroke_width=3 * SS, stroke_fill=shade(col, 0.4))
    return done(img, w, w).resize((128, 128), Image.LANCZOS)


def bar_fill():
    """Countdown bar fill, 256x32: white with a soft top highlight and darker bottom (tinted in the addon)."""
    w, h = 256, 32
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        v = 1.0 - 0.45 * t + (0.25 if t < 0.35 else 0) * (1 - t / 0.35)
        c = max(0, min(255, round(200 * v)))
        for x in range(w):
            px[x, y] = (c, c, c, 255)
    return img


def status_plate(col):
    """The listening/transcribing plate: like the hint bar, but a coloured double border and glow."""
    w, h = 512, 64
    img = canvas(w, h)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(S(8, 9, w - 8, h - 9), radius=18 * SS, outline=col + (200,), width=6 * SS)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5 * SS)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(S(8, 9, w - 8, h - 9), radius=18 * SS, fill=(22, 17, 14, 240), outline=col + (255,),
                        width=3 * SS)
    d.rounded_rectangle(S(14, 15, w - 14, h - 15), radius=13 * SS, outline=(*COL["border"], 200), width=1 * SS)
    return done(img, w, h)


STICK = (110, 185, 255)                                     # stick blue


def stick_base():
    """128 px: the thumbstick seen from above (socket ring) with arrows left and right = "move it sideways"."""
    w = 128
    img = Image.new("RGBA", (w * SS, w * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse(S(30, 30, 98, 98), fill=(28, 34, 44, 255), outline=(*STICK, 255), width=4 * SS)   # socket
    d.ellipse(S(38, 38, 90, 90), outline=(60, 80, 105, 255), width=2 * SS)
    for x, sgn in ((14, -1), (114, 1)):                                                          # arrows
        d.polygon(S(x + 10 * sgn, 64, x - 6 * sgn, 50, x - 6 * sgn, 78), fill=(*STICK, 255))  # tip outwards
    return img.resize((w, w), Image.LANCZOS)


def stick_cap():
    """128 px: the stick's cap with R (moved left/right by the addon's animation)."""
    w = 128
    img = Image.new("RGBA", (w * SS, w * SS), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(S(40, 44, 92, 96), fill=(0, 0, 0, 150))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(3 * SS)))
    d = ImageDraw.Draw(img)
    d.ellipse(S(40, 40, 88, 88), fill=(*STICK, 255), outline=shade(STICK, 0.6), width=3 * SS)
    font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 30 * SS)
    tb = d.textbbox((0, 0), "R", font=font)
    d.text((64 * SS - (tb[2] - tb[0]) / 2 - tb[0], 64 * SS - (tb[3] - tb[1]) / 2 - tb[1]), "R", font=font,
           fill=(24, 34, 50, 255))
    return img.resize((w, w), Image.LANCZOS)


def round_icon():
    """The addon icon's round centre (stone ring + microphone) as a round 128 px image with a soft edge, for the
    status card's icon well (WoW's SetMask did not work on this client)."""
    src = HERE / "addon_icon_source.webp"
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    r = int(w * 0.405)                                  # just outside the stone ring
    cx, cy = w // 2, h // 2
    im = im.crop((cx - r, cy - r, cx + r, cy + r)).resize((512, 512), Image.LANCZOS)
    mask = Image.new("L", (512, 512), 0)
    ImageDraw.Draw(mask).ellipse((6, 6, 506, 506), fill=255)
    im.putalpha(mask.filter(ImageFilter.GaussianBlur(3)))
    return im.resize((128, 128), Image.LANCZOS)


def badge_selected():
    """64x64 seal on the icon of the selected destination: green, gold rim, white check mark."""
    w = 128
    img = Image.new("RGBA", (w * SS, w * SS), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(S(10, 14, 120, 124), fill=(0, 0, 0, 170))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5 * SS)))
    d = ImageDraw.Draw(img)
    d.ellipse(S(8, 8, 120, 120), fill=(120, 84, 30, 255))
    d.ellipse(S(14, 14, 114, 114), fill=(230, 180, 70, 255))
    d.ellipse(S(20, 20, 108, 108), fill=(46, 150, 64, 255))
    d.line(S(36, 66, 56, 86, 92, 44), fill=(250, 255, 245, 255), width=13 * SS, joint="curve")
    return img.resize((64, 64), Image.LANCZOS)


def status_card(col):
    """512x128 listening/transcribing card: coloured border + glow, a round bronze-rimmed well on the left that
    holds the icon (so it sits inside the card), room for two lines of text on the right."""
    w, h = 512, 128
    img = canvas(w, h)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(S(10, 10, w - 10, h - 10), radius=30 * SS, outline=col + (190,), width=8 * SS)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6 * SS)))
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle(S(10, 10, w - 10, h - 10), radius=30 * SS, fill=255)
    img.alpha_composite(textured(m, (34, 26, 20), 0.35, 11, grain=3))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(S(10, 10, w - 10, h - 10), radius=30 * SS, outline=col + (255,), width=3 * SS)
    d.rounded_rectangle(S(17, 17, w - 17, h - 17), radius=24 * SS, outline=(*COL["border"], 170), width=1 * SS)
    cx, cy, r = 64, h / 2, 44                                   # the icon well
    for rr, c in ((r + 5, (70, 46, 20)), (r + 3, (176, 122, 52)), (r + 1, (120, 80, 34)), (r - 1, (16, 13, 11))):
        d.ellipse(S(cx - rr, cy - rr, cx + rr, cy + rr), fill=c + (255,))
    d.line(S(124, 26, 124, h - 26), fill=(*COL["border"], 150), width=1 * SS)   # thin divider before the text
    return done(img, w, h)


# ----------------------------------------------------------------- preview
LABELS = ["Say", "Party", "Guild", "Whisper", "Friends", "Recent\nPeople", "World\nChats", "Options"]
LABEL_ICONS = ["say", "party", "guild", "whisper", "friends", "recent", "world", "options"]


def rotate(img, deg):
    return img.rotate(-deg, resample=Image.BICUBIC, center=(SIZE / 2, SIZE / 2))


def preview(layers, select, out):
    bgref = HERE / "handoff/radial-handoff/reference/options-comparison.png"
    view = Image.new("RGBA", (700, 640), (30, 34, 30, 255))
    if bgref.exists():
        ref = Image.open(bgref).convert("RGBA").crop((1060, 80, 1660, 480)).resize((700, 466))
        view.alpha_composite(ref.filter(ImageFilter.GaussianBlur(8)).point(lambda v: v * 0.6), (0, 0))
    wheel = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    wheel.alpha_composite(layers["wheel_base"])
    wheel.alpha_composite(rotate(layers["wedge_active"], 0))      # preview: Say is the active destination
    if select is not None:
        wheel.alpha_composite(rotate(layers["wedge_select"], select * 45))
        wheel.alpha_composite(rotate(layers["line"], select * 45))
    hubimg = layers["hub"].resize((136, 136), Image.LANCZOS)
    wheel.alpha_composite(hubimg, (int(C - 68), int(C - 68)))
    font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSerifCondensed-Bold.ttf", 21) if Path(
        "/usr/share/fonts/TTF/DejaVuSerifCondensed-Bold.ttf").exists() else ImageFont.load_default()
    d = ImageDraw.Draw(wheel)
    for i, (label, ic) in enumerate(zip(LABELS, LABEL_ICONS)):
        a = math.radians(i * 45)
        cx, cy = C + 138 * math.sin(a), C - 138 * math.cos(a)
        icn = layers["icon_" + ic].resize((46, 46), Image.LANCZOS)
        wheel.alpha_composite(icn, (int(cx - 23), int(cy - 40)))
        tb = d.multiline_textbbox((0, 0), label, font=font, align="center")
        tx, ty = cx - (tb[2] - tb[0]) / 2, cy + 8
        d.multiline_text((tx + 1.5, ty + 1.5), label, font=font, fill=(0, 0, 0, 220), align="center")
        d.multiline_text((tx, ty), label, font=font, fill=COL["text"] + (255,) if i != select else (255, 250, 230, 255),
                         align="center")
    view.alpha_composite(wheel, (94, 8))
    hb = layers["hintbar"]
    view.alpha_composite(hb, (94, 548))
    dv = ImageDraw.Draw(view)
    f2 = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSerifCondensed.ttf", 22) if Path(
        "/usr/share/fonts/TTF/DejaVuSerifCondensed.ttf").exists() else font
    msg = "Push stick & let go to choose  •  Release R4 to talk"
    tb = dv.textbbox((0, 0), msg, font=f2)
    dv.text((94 + 256 - (tb[2] - tb[0]) / 2, 548 + 18), msg, font=f2, fill=(236, 214, 160, 255))
    view.convert("RGB").save(out)


def icon_sheet(layers, out):
    """All icons on the wheel's leather, with names: to look at them outside the game."""
    names = ICONS
    cols = 5
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * 150, rows * 150), (*COL["seg"], 255))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSerifCondensed-Bold.ttf", 16) if Path(
        "/usr/share/fonts/TTF/DejaVuSerifCondensed-Bold.ttf").exists() else ImageFont.load_default()
    for i, n in enumerate(names):
        x, y = (i % cols) * 150, (i // cols) * 150
        sheet.alpha_composite(layers["icon_" + n].resize((96, 96), Image.LANCZOS), (x + 27, y + 12))
        tb = d.textbbox((0, 0), n, font=font)
        d.text((x + 75 - (tb[2] - tb[0]) / 2, y + 116), n, font=font, fill=COL["text"] + (255,))
    sheet.convert("RGB").save(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ADDON))
    p.add_argument("--preview", default=str(HERE / "preview.png"))
    p.add_argument("--select", type=int, default=2)
    p.add_argument("--no-install", action="store_true")
    a = p.parse_args()
    random.seed(1)
    layers = {"wheel_base": wheel_base(), "wedge_stone": wedge_stone(), "wedge_select": wedge_select(),
              "line": line_layer(), "hub": hub(), "hintbar": hintbar()}
    for name in ICONS:
        layers["icon_" + name] = icon(name)
    layers["glyph_r4"] = glyph("r4")
    layers["glyph_a"] = button_glyph("A", (70, 170, 60))
    layers["glyph_b"] = button_glyph("B", (200, 55, 45))
    layers["bar_fill"] = bar_fill()
    layers["badge_selected"] = badge_selected()
    layers["wedge_active"] = wedge_active()
    layers["active_tag"] = active_tag()
    layers["icon_round"] = round_icon()
    layers["stick_base"] = stick_base()
    layers["stick_cap"] = stick_cap()
    layers["status_listen"] = status_card((235, 70, 55))
    layers["status_work"] = status_card((240, 170, 40))
    preview(layers, a.select, a.preview)
    icon_sheet(layers, HERE / "icons_preview.png")
    src = HERE / "wheel_src"
    src.mkdir(exist_ok=True)
    for name, img in layers.items():
        img.save(src / f"{name}.png")                    # editable sources
    if not a.no_install:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, img in layers.items():
            img.save(out / f"{name}.tga", compression=None)
    print("preview:", a.preview, "| layers:", len(layers), "| installed:", not a.no_install)


if __name__ == "__main__":
    main()
