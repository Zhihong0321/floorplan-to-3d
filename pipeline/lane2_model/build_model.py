#!/usr/bin/env python3
"""LANE 2 - floorplan geometry -> 3D scene.

Reads  projects/<p>/1_floorplan/house.json      (contract: CONTRACTS.md, "house.json")
Writes projects/<p>/2_model/scene.json          (walls/floors/roof meshes + roof faces for lane 3)
       projects/<p>/2_model/model.html          (self-contained 3D viewer, no PV)

Knows nothing about panels, inverters or cables, and never edits house.json.
Usage: python3 pipeline/lane2_model/build_model.py <project>
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common.geo import (Geo, UP, DIRS, BEARING, vadd, vsub, vmul, vlen, vcross)  # noqa: E402
from common import project as P  # noqa: E402
from common.contract import check_house, format_findings  # noqa: E402

warnings = []


# ---------- walls ----------
def build_walls(geo, house):
    levels = house["levels"]
    allpts = [p for lv in levels for w in lv["walls"] for p in (w["p1"], w["p2"])]
    bx0, bx1 = min(p[0] for p in allpts), max(p[0] for p in allpts)
    by0, by1 = min(p[1] for p in allpts), max(p[1] for p in allpts)
    tol = 0.06

    def is_ext(w):
        if "ext" in w:
            return bool(w["ext"])
        a, b = w["p1"], w["p2"]
        return any(abs(a[i] - v) < tol and abs(b[i] - v) < tol
                   for i, v in ((0, bx0), (0, bx1), (1, by0), (1, by1)))

    walls_by_id = {}
    for li, lv in enumerate(levels):
        elev, height = lv.get("elevation", 0.0), lv.get("height", 2.8)
        for w in lv["walls"]:
            walls_by_id[w["id"]] = (li, w)
            ext = is_ext(w)
            w["_ext"] = ext
            t = w.get("t", 0.15 if ext else 0.1)
            height = w.get("h", lv.get("height", 2.8))  # per-wall height override (parapets etc.)
            p1, p2 = w["p1"], w["p2"]
            L = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if L < 1e-6:
                warnings.append("wall %s has zero length" % w["id"])
                continue
            e = ((p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L)
            n = (-e[1], e[0])
            ops = []
            for o in lv.get("openings", []):
                if o["wall"] != w["id"]:
                    continue
                kind = o.get("type", "window")
                ow = o.get("w", 0.9 if kind == "door" else 1.2)
                sill = o.get("sill", 0.0 if kind == "door" else 0.9)
                oh = o.get("h", 2.1 if kind == "door" else 1.2)
                c = o["at"]
                if c - ow / 2 < -1e-6 or c + ow / 2 > L + 1e-6:
                    warnings.append("opening on %s at %.2f is outside the wall (L=%.2f)" % (w["id"], c, L))
                ops.append((c - ow / 2, c + ow / 2, sill, min(sill + oh, height), kind))
            ops.sort()
            solid = geo.g("wall_ext" if ext else "wall_int", "walls", li)
            glass = geo.g("glass", "walls", li, opacity=0.45)
            door = geo.g("door", "walls", li)
            cur = -t / 2.0
            for (sa, sb, sill, head, kind) in ops:
                if sa > cur:
                    geo.box(solid, p1, e, n, cur, sa, t, elev, elev + height)
                if sill > 0:
                    geo.box(solid, p1, e, n, sa, sb, t, elev, elev + sill)
                if head < height:
                    geo.box(solid, p1, e, n, sa, sb, t, elev + head, elev + height)
                if kind != "opening":  # "opening" = doorless gap
                    tgt = glass if kind == "window" else door
                    A = (p1[0] + e[0] * sa, elev + sill, p1[1] + e[1] * sa)
                    B = (p1[0] + e[0] * sb, elev + sill, p1[1] + e[1] * sb)
                    C = (B[0], elev + head, B[2])
                    D = (A[0], elev + head, A[2])
                    geo.quad(tgt, A, B, C, D)
                cur = sb
            geo.box(solid, p1, e, n, cur, L + t / 2.0, t, elev, elev + height)
    return (bx0, by0, bx1, by1), walls_by_id


# ---------- roof ----------
def make_face(name, d3, c_e, lu, run, pitch_rad, az_bearing):
    f = vmul(d3, -1.0)
    u = vcross(f, UP)
    cp, sp = math.cos(pitch_rad), math.sin(pitch_rad)
    v = vadd(vmul(f, cp), (0.0, sp, 0.0))
    lv = run / cp
    O = vsub(c_e, vmul(u, lu / 2.0))
    return {"name": name, "O": O, "u": u, "v": v, "n": vcross(u, v), "lu": lu, "lv": lv,
            "pitch": math.degrees(pitch_rad), "bearing": az_bearing}


def build_roof(geo, house, fp, eave_h, top_li):
    roof = house.get("roof") or {"type": "none"}
    kind = roof.get("type", "none")
    ov = roof.get("overhang", 0.4)
    ovg = roof.get("overhang_gable", ov)  # overhang past the gable ends (0 for terraces)
    pitch = math.radians(roof.get("pitch_deg", 20))
    tp = math.tan(pitch)
    x0, y0, x1, y1 = fp
    W, D = x1 - x0, y1 - y0
    xc, yc = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    faces = {}
    if kind == "none":  # roof intentionally left out: supplied later by the roof app
        return roof, faces
    pos = geo.g("roof", "roof", opacity=0.55)
    fill = geo.g("wall_ext", "walls", None)

    def add_face(fc):
        O, u, v = fc["O"], fc["u"], fc["v"]
        A = O
        B = vadd(O, vmul(u, fc["lu"]))
        C = vadd(B, vmul(v, fc["lv"]))
        Dd = vadd(O, vmul(v, fc["lv"]))
        geo.quad(pos, A, B, C, Dd)
        faces[fc["name"]] = fc

    if kind == "gable":
        axis = roof.get("ridge_axis", "x")
        if axis == "x":
            rise = (D / 2.0) * tp
            for nm, dz, ce_z in (("N", -1.0, y0 - ov), ("S", 1.0, y1 + ov)):
                add_face(make_face(nm, (0.0, 0.0, dz), (xc, eave_h - ov * tp, ce_z), W + 2 * ovg,
                                   D / 2.0 + ov, pitch, BEARING[nm]))
            for x in (x0, x1):
                geo.tri(fill, (x, eave_h, y0), (x, eave_h, y1), (x, eave_h + rise, yc))
        else:
            rise = (W / 2.0) * tp
            for nm, dx, ce_x in (("W", -1.0, x0 - ov), ("E", 1.0, x1 + ov)):
                add_face(make_face(nm, (dx, 0.0, 0.0), (ce_x, eave_h - ov * tp, yc), D + 2 * ovg,
                                   W / 2.0 + ov, pitch, BEARING[nm]))
            for y in (y0, y1):
                geo.tri(fill, (x0, eave_h, y), (x1, eave_h, y), (xc, eave_h + rise, y))
    elif kind == "shed":
        fall = roof.get("falls_to", "S")
        dx, dz = DIRS[fall]
        d3 = (dx, 0.0, dz)
        depth = D if dz != 0 else W
        across = W if dz != 0 else D
        if fall == "S": ce = (xc, eave_h - ov * tp, y1 + ov)
        elif fall == "N": ce = (xc, eave_h - ov * tp, y0 - ov)
        elif fall == "E": ce = (x1 + ov, eave_h - ov * tp, yc)
        else: ce = (x0 - ov, eave_h - ov * tp, yc)
        add_face(make_face(fall, d3, ce, across + 2 * ov, depth + 2 * ov, pitch, BEARING[fall]))

        def hgt(px, pz):  # roof height above wall line at plan point
            dist = {"S": y1 - pz, "N": pz - y0, "E": x1 - px, "W": px - x0}[fall]
            return eave_h + dist * tp
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            ha, hb = hgt(*a), hgt(*b)
            if ha - eave_h < 1e-6 and hb - eave_h < 1e-6:
                continue
            geo.quad(fill, (a[0], eave_h, a[1]), (b[0], eave_h, b[1]), (b[0], hb, b[1]), (a[0], ha, a[1]))
    elif kind == "flat":
        z = eave_h
        geo.quad(pos, (x0 - ov, z, y0 - ov), (x1 + ov, z, y0 - ov), (x1 + ov, z, y1 + ov), (x0 - ov, z, y1 + ov))
    else:
        raise SystemExit("roof.type must be none | gable | shed | flat (got %r). Use gable for hip roofs." % kind)
    return roof, faces


# ---------- main ----------
def building_bbox(levels):
    """Bounding box of the full-height walls on all levels (walls with an 'h' override are fences/parapets)."""
    pts = [q for l in levels for w in l["walls"] if "h" not in w for q in (w["p1"], w["p2"])]
    if not pts:
        pts = [q for l in levels for w in l["walls"] for q in (w["p1"], w["p2"])]
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def build(house):
    levels = house.get("levels") or []
    if not levels or not all(l.get("walls") for l in levels):
        raise SystemExit("house.json needs levels[] and every level needs walls[] (lane 1 output is incomplete)")
    geo = Geo()
    fp_walls, _ = build_walls(geo, house)
    top = max(levels, key=lambda l: l.get("elevation", 0.0))
    eave_h = top.get("elevation", 0.0) + top.get("height", 2.8)
    bfp = building_bbox(levels)  # outline of the full-height walls = the building, fences/parapets excluded
    fp = tuple((house.get("roof") or {}).get("footprint", bfp))
    roof, faces = build_roof(geo, house, fp, eave_h, 0)
    north = house.get("north_deg", 0.0)
    return {
        "schema": "scene/1",
        "name": house.get("name", "house"),
        "north_deg": north,
        "levels": [{"name": l.get("name", "L%d" % i), "elevation": l.get("elevation", 0.0),
                    "height": l.get("height", 2.8), "rooms": l.get("rooms", [])}
                   for i, l in enumerate(levels)],
        "groups": [g for g in geo.groups.values() if g["positions"]],
        "building": {"footprint": list(bfp), "top_h": eave_h, "levels": len(levels),
                     "north_deg": north,
                     "note": "walls only; roof is supplied by an external roof/panel app"},
        "roof": {"type": roof.get("type", "none"), "pitch_deg": roof.get("pitch_deg", 0),
                 "overhang": roof.get("overhang", 0.4)},
        "faces": [{"name": k, "O": list(f["O"]), "u": list(f["u"]), "v": list(f["v"]), "n": list(f["n"]),
                   "lu": f["lu"], "lv": f["lv"], "pitch": f["pitch"], "bearing": f["bearing"],
                   "azimuth_true": round((f["bearing"] - north) % 360)} for k, f in faces.items()],
        "eave_h": eave_h,
        "footprint": list(fp),
        "warnings": warnings,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    p = P.paths(sys.argv[1], create=True)
    if not os.path.isfile(p["house"]):
        raise SystemExit("missing %s - run lane 1 first" % p["house"])
    try:
        house = P.load_json(p["house"])
    except ValueError as e:
        raise SystemExit("house.json is not valid JSON: %s" % e)
    source = P.load_json(p["source_json"]) if os.path.isfile(p["source_json"]) else {}
    findings = check_house(house, source)
    if findings["FAIL"] and "--force" not in sys.argv:
        print(format_findings(findings))
        raise SystemExit("lane 2 refuses to build: fix house.json in lane 1 (or pass --force to build anyway)")
    scene = build(house)
    P.save_json(p["scene"], scene, indent=None)
    viewer_model = dict(scene)
    viewer_model.update(P.empty_pv_fields())
    P.render_viewer(viewer_model, p["model_html"])
    wall_tris = sum(len(g["positions"]) // 9 for g in scene["groups"] if g["layer"] == "walls")
    print("== lane 2: %s ==" % scene["name"])
    b = scene["building"]
    print("levels: %d | building top %.2f m | footprint %.2f x %.2f m | roof: %s" % (
        len(scene["levels"]), b["top_h"], b["footprint"][2] - b["footprint"][0], b["footprint"][3] - b["footprint"][1],
        "none (external)" if scene["roof"]["type"] == "none" else "%s %s deg, faces %s" % (
            scene["roof"]["type"], scene["roof"]["pitch_deg"],
            ", ".join("%s (az %d)" % (f["name"], f["azimuth_true"]) for f in scene["faces"]))))
    print("wall triangles: %d" % wall_tris)
    for w in warnings:
        print("WARNING:", w)
    print("wrote", p["scene"])
    print("wrote", p["model_html"])


if __name__ == "__main__":
    main()
