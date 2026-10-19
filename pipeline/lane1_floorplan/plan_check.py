#!/usr/bin/env python3
"""LANE 1d - redraw house.json as a 2D plan so it can be compared with the source drawing.

Usage: python3 pipeline/lane1_floorplan/plan_check.py <project> [--px-per-m 40]
Writes projects/<p>/1_floorplan/plan_check_<level>.png (walls, doors, windows, rooms, 1 m grid, dimensions).
Pillow only. No 3D involved: this is lane 1 verifying its own reading before anything is built on it.
"""
import argparse
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import project as P  # noqa: E402

PAL = [(236, 229, 211), (227, 235, 221), (223, 231, 238), (240, 225, 220), (232, 224, 238), (238, 233, 208)]


def render(level, all_pts, s, out):
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    for r in level.get("rooms", []):
        xs += [q[0] for q in r["poly"]]
        ys += [q[1] for q in r["poly"]]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    m = 60
    W, H = int((x1 - x0) * s) + 2 * m, int((y1 - y0) * s) + 2 * m + 30
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = ImageFont.load_default(size=12)
    fb = ImageFont.load_default(size=14)
    T = lambda x, y: (m + (x - x0) * s, m + (y - y0) * s)

    # 1 m grid + axis labels every 5 m
    for gx in range(int(math.floor(x0)), int(math.ceil(x1)) + 1):
        a, b = T(gx, y0 - 0.3), T(gx, y1 + 0.3)
        d.line([a, b], fill=(235, 235, 235))
        if gx % 5 == 0:
            d.text((a[0] - 6, a[1] - 16), "%d" % gx, fill=(150, 150, 150), font=f)
    for gy in range(int(math.floor(y0)), int(math.ceil(y1)) + 1):
        a, b = T(x0 - 0.3, gy), T(x1 + 0.3, gy)
        d.line([a, b], fill=(235, 235, 235))
        if gy % 5 == 0:
            d.text((a[0] - 28, a[1] - 6), "%d" % gy, fill=(150, 150, 150), font=f)

    for i, r in enumerate(level.get("rooms", [])):
        d.polygon([T(*q) for q in r["poly"]], fill=PAL[i % len(PAL)])
    for r in level.get("rooms", []):
        cx = sum(q[0] for q in r["poly"]) / len(r["poly"])
        cy = sum(q[1] for q in r["poly"]) / len(r["poly"])
        tx, ty = T(cx, cy)
        w = d.textlength(r["name"], font=f)
        d.text((tx - w / 2, ty - 6), r["name"], fill=(40, 40, 40), font=f)

    walls = {w["id"]: w for w in level["walls"]}
    for w in level["walls"]:
        (ax, ay), (bx, by) = w["p1"], w["p2"]
        L = math.hypot(bx - ax, by - ay)
        if L < 1e-6:
            continue
        ex, ey = (bx - ax) / L, (by - ay) / L
        nx, ny = -ey, ex
        t = w.get("t", 0.15)
        h = t / 2
        quad = [T(ax - ex * h + nx * h, ay - ey * h + ny * h), T(bx + ex * h + nx * h, by + ey * h + ny * h),
                T(bx + ex * h - nx * h, by + ey * h - ny * h), T(ax - ex * h - nx * h, ay - ey * h - ny * h)]
        d.polygon(quad, fill=(55, 55, 60))
        d.text(T((ax + bx) / 2 + nx * 0.25, (ay + by) / 2 + ny * 0.25), w["id"], fill=(170, 60, 60), font=ImageFont.load_default(size=9))
    for o in level.get("openings", []):
        w = walls.get(o["wall"])
        if not w:
            continue
        (ax, ay), (bx, by) = w["p1"], w["p2"]
        L = math.hypot(bx - ax, by - ay)
        ex, ey = (bx - ax) / L, (by - ay) / L
        nx, ny = -ey, ex
        kind = o.get("type", "window")
        ow = o.get("w", 0.9 if kind == "door" else 1.2)
        t = w.get("t", 0.15) / 2 + 0.01
        pa = (ax + ex * (o["at"] - ow / 2), ay + ey * (o["at"] - ow / 2))
        pb = (ax + ex * (o["at"] + ow / 2), ay + ey * (o["at"] + ow / 2))
        gap = [T(pa[0] + nx * t, pa[1] + ny * t), T(pb[0] + nx * t, pb[1] + ny * t),
               T(pb[0] - nx * t, pb[1] - ny * t), T(pa[0] - nx * t, pa[1] - ny * t)]
        d.polygon(gap, fill=(255, 255, 255))
        col = {"door": (150, 90, 50), "window": (60, 130, 200)}.get(kind)
        if col:
            d.line([T(*pa), T(*pb)], fill=col, width=3)

    # overall dimensions + scale bar
    d.text((m, 10), "%s   |   %.2f x %.2f m" % (level.get("name", "?"), x1 - x0, y1 - y0), fill=(20, 20, 20), font=fb)
    sx, sy = T(x0, y1 + 0.9)
    d.line([(sx, sy), (sx + 5 * s, sy)], fill=(20, 20, 20), width=2)
    d.text((sx + 5 * s + 6, sy - 7), "5 m", fill=(20, 20, 20), font=f)
    d.text((m, H - 22), "doors brown | windows blue | wall ids red", fill=(110, 110, 110), font=f)
    im.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--px-per-m", type=float, default=40)
    a = ap.parse_args()
    p = P.paths(a.project)
    house = P.load_json(p["house"])
    pts = [q for l in house["levels"] for w in l["walls"] for q in (w["p1"], w["p2"])]
    for i, l in enumerate(house["levels"]):
        out = os.path.join(p["l1"], "plan_check_%s.png" % P.slugify(l.get("name", str(i))))
        render(l, pts, a.px_per_m, out)
        print("wrote", os.path.relpath(out, P.ROOT))


if __name__ == "__main__":
    main()
