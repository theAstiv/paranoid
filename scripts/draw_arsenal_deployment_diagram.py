"""Draws examples/arsenal-deps/diagrams/deployment.png: a brand-neutral
deployment diagram of the MediaDrop fixture's deployable units (no
cloud-provider logos/icons, no third-party branding).

Deliberately includes one unit — the secrets manager — that isn't named in
description.md or architecture.mmd, so a live run's threats that mention it
are evidence the pipeline actually used this diagram (not just the text
description or the other diagram). See examples/arsenal-deps/README.md.

Run from the repo root: python scripts/draw_arsenal_deployment_diagram.py
Requires Pillow (already a Paranoid dependency).

Uses the Windows-bundled Segoe UI fonts when available and falls back to
Pillow's built-in bitmap font otherwise (e.g. on Linux/macOS CI) — on a
non-Windows machine the regenerated image looks visibly different (no
anti-aliasing, fixed small size), though it still passes the diagram
validator. Regenerate on Windows to match the committed PNG exactly.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


W, H = 1200, 620
BG = (255, 255, 255)
BOX_FILL = (235, 242, 250)
BOX_BORDER = (70, 110, 160)
EXT_FILL = (255, 255, 255)
EXT_BORDER = (150, 150, 150)
TEXT = (30, 40, 55)
ARROW = (90, 100, 115)
SUBTEXT = (90, 100, 115)

img = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

try:
    font_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 20)
    font_small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 13)
except OSError:
    font_title = ImageFont.load_default()
    font_small = ImageFont.load_default()


def box(x, y, w, h, title, subtitle=None, dashed=False):
    """``subtitle`` is a string (one line) or a list of strings (one per
    line) — pass a list whenever the text is long enough to risk running
    past the box's edges at the box's own width."""
    outline = EXT_BORDER if dashed else BOX_BORDER
    fill = EXT_FILL if dashed else BOX_FILL
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=fill, outline=outline, width=2)
    tw = draw.textlength(title, font=font_title)
    draw.text((x + (w - tw) / 2, y + 16), title, fill=TEXT, font=font_title)
    lines = [subtitle] if isinstance(subtitle, str) else (subtitle or [])
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font_small)
        draw.text((x + (w - lw) / 2, y + 44 + i * 18), line, fill=SUBTEXT, font=font_small)
    return (x, y, x + w, y + h)


def label_at(mx, my, text):
    lw = draw.textlength(text, font=font_small)
    draw.rectangle([mx - lw / 2 - 4, my - 9, mx + lw / 2 + 4, my + 9], fill=BG)
    draw.text((mx - lw / 2, my - 7), text, fill=SUBTEXT, font=font_small)


def arrow(p1, p2, label=None, dashed=False, label_frac=0.5):
    x1, y1 = p1
    x2, y2 = p2
    if dashed:
        dist = math.hypot(x2 - x1, y2 - y1)
        steps = max(int(dist // 10), 1)
        for i in range(steps):
            if i % 2 == 0:
                a = i / steps
                b = min((i + 1) / steps, 1.0)
                draw.line(
                    [
                        (x1 + (x2 - x1) * a, y1 + (y2 - y1) * a),
                        (x1 + (x2 - x1) * b, y1 + (y2 - y1) * b),
                    ],
                    fill=ARROW,
                    width=2,
                )
    else:
        draw.line([p1, p2], fill=ARROW, width=2)
    angle = math.atan2(y2 - y1, x2 - x1)
    ah = 9
    for da in (0.5, -0.5):
        ang = angle + math.pi - da
        draw.line(
            [(x2, y2), (x2 + ah * math.cos(ang), y2 + ah * math.sin(ang))],
            fill=ARROW,
            width=2,
        )
    if label:
        mx = x1 + (x2 - x1) * label_frac
        my = y1 + (y2 - y1) * label_frac
        label_at(mx, my, label)


draw.text((40, 22), "MediaDrop — deployment units", fill=TEXT, font=font_title)
draw.text(
    (40, 50),
    "Two containers from one TypeScript source tree, behind a shared Redis, object store, and secrets manager",
    fill=SUBTEXT,
    font=font_small,
)

# Boxes — API/Store on the upper row, Worker/Redis/Secrets on the lower row,
# the external partner application on its own row at the bottom.
lb = box(60, 190, 170, 80, "Load balancer", "TLS termination")
api = box(310, 90, 220, 90, "API container", "Express 5 (esbuild bundle)")
worker = box(310, 320, 220, 90, "Worker container", "sharp resize (esbuild bundle)")
redis = box(630, 320, 180, 80, "Redis", "job queue")
store = box(930, 90, 220, 90, "Object store", "S3-compatible, private")
secrets = box(60, 320, 220, 90, "Secrets manager", ["JWT signing key,", "webhook HMAC key"])
partner = box(310, 490, 260, 70, "Partner application", "external", dashed=True)

# Arrows (only the load balancer sits in the request path — the worker is
# only ever reached via the queue, never directly over HTTP)
arrow((lb[2], 215), (api[0], 135), "HTTP")
arrow((api[2], 150), (store[0], 120), "put original", label_frac=0.42)
arrow((api[0] + 60, api[3]), (redis[0] + 20, redis[1]), "enqueue", label_frac=0.55)
arrow((redis[0], redis[1] + 20), (worker[2], worker[1] + 25), "dequeue", label_frac=0.45)
arrow((worker[2], worker[1] + 55), (store[0], store[3] - 10), "put variants", label_frac=0.58)
arrow(
    (secrets[2], secrets[1] + 20),
    (api[0] + 20, api[3]),
    "JWT signing key",
    dashed=True,
    label_frac=0.45,
)
# Mid-height, right-edge-to-left-edge so it reads as a clear, distinct link
# from the "JWT signing key" arrow above rather than two overlapping diagonals.
arrow(
    (secrets[2], secrets[1] + 55),
    (worker[0], worker[1] + 55),
    "HMAC key",
    dashed=True,
    label_frac=0.5,
)
arrow(
    (worker[0] + 60, worker[3]),
    (partner[0] + 60, partner[1]),
    "axios webhook (HMAC-signed)",
    dashed=True,
    label_frac=0.5,
)

out_path = Path(__file__).resolve().parent.parent / "examples/arsenal-deps/diagrams/deployment.png"
img.save(out_path, format="PNG")
print("saved", out_path, img.size)
