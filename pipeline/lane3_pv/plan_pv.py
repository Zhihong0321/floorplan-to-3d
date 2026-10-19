#!/usr/bin/env python3
"""LANE 3 - PV panels + cable planning on top of a lane-2 scene.

Reads  projects/<p>/2_model/scene.json      (roof faces, eave height, levels)
       projects/<p>/3_pv/pv_plan.json       (panel, arrays, equipment, cables - written by Claude/user)
Writes projects/<p>/3_pv/pv.json            (arrays, capacity per roof face, cable results)
       projects/<p>/3_pv/cable_schedule.csv
       projects/<p>/3_pv/viewer.html        (scene + PV + cables)

Never reads house.json and never changes geometry: if the roof is wrong, fix it in lane 1/2.
Usage: python3 pipeline/lane3_pv/plan_pv.py <project>
"""
import csv
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common.geo import (Geo, UP, DIRS, BEARING, vadd, vsub, vmul, vlen, vcross)  # noqa: E402
from common import project as P  # noqa: E402

RHO = 0.0225  # ohm*mm2/m, copper at ~90C (conservative)
SIZES = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95]
warnings = []


def flat_face(name, fp, eave_h):
    """Horizontal frame for tilted arrays on a flat roof, facing plan direction `name`."""
    x0, y0, x1, y1 = fp
    dx, dz = DIRS[name]
    d3 = (dx, 0.0, dz)
    f = vmul(d3, -1.0)
    u = vcross(f, UP)
    if dz != 0:
        lu, lv = x1 - x0, y1 - y0
        c = ((x0 + x1) / 2.0, eave_h, y1 if dz > 0 else y0)
    else:
        lu, lv = y1 - y0, x1 - x0
        c = (x1 if dx > 0 else x0, eave_h, (y0 + y1) / 2.0)
    O = vsub(c, vmul(u, lu / 2.0))
    return {"name": name, "O": O, "u": u, "v": f, "n": UP, "lu": lu, "lv": lv, "pitch": 0.0,
            "bearing": BEARING[name]}


# ---------- PV ----------
def fit(fc, pw, ph, gap, sb, flat, tilt):
    """Max (rows, cols) of pw x ph panels that fit a roof face with setback sb."""
    cols = int(max(0, math.floor((fc["lu"] - 2 * sb + gap) / (pw + gap))))
    if flat:
        pitch_v = ph * (math.cos(tilt) + math.sin(tilt) / math.tan(math.radians(20)))
        avail = fc["lv"] - 2 * sb - ph * math.cos(tilt)
        rows = int(math.floor(avail / pitch_v)) + 1 if avail >= 0 else 0
    else:
        rows = int(max(0, math.floor((fc["lv"] - 2 * sb + gap) / (ph + gap))))
    return rows, cols


def capacity(pv, faces, fp, eave_h, roof_kind):
    """Max panels per roof face (portrait / landscape) so layouts can be chosen before placing arrays."""
    if roof_kind == "none":
        return []
    panel = pv.get("panel", {})
    w, h, watt = panel.get("w", 1.134), panel.get("h", 2.278), panel.get("watt", 550)
    gap, sb = pv.get("gap", 0.02), pv.get("setback", 0.4)
    names = list(faces) if roof_kind != "flat" else ["N", "S", "E", "W"]
    out = []
    for nm in names:
        fc = faces[nm] if roof_kind != "flat" else flat_face(nm, fp, eave_h)
        res = {"face": nm, "usable_m": [round(fc["lu"] - 2 * sb, 2), round(fc["lv"] - 2 * sb, 2)]}
        for ori, (pw, ph) in (("portrait", (w, h)), ("landscape", (h, w))):
            r, c = fit(fc, pw, ph, gap, sb, roof_kind == "flat", math.radians(10))
            res[ori] = {"rows": r, "cols": c, "panels": r * c, "kwp": round(r * c * watt / 1000.0, 2)}
        out.append(res)
    return out


def build_pv(geo, pv, faces, fp, eave_h, roof_kind, north_deg):
    if not pv:
        return [], {"panels": 0, "kwp": 0.0}
    panel = pv.get("panel", {})
    pw0, ph0 = panel.get("w", 1.134), panel.get("h", 2.278)
    watt = panel.get("watt", 550)
    vmp, imp = panel.get("vmp", 41.7), panel.get("imp", 13.2)
    gap, sb = pv.get("gap", 0.02), pv.get("setback", 0.4)
    pos = geo.g("pv", "pv")
    arrays, total = [], 0
    for a in pv.get("arrays", []):
        if "conn" in a:  # array placed by an external roof/panel app: only its connection point matters here
            n_ext = a.get("panels", 0)
            pps_e = a.get("panels_per_string", n_ext or 1)
            total += n_ext
            arrays.append({"id": a["id"], "face": a.get("face", "external"), "panels": n_ext,
                           "rows": a.get("rows", 0), "cols": a.get("cols", 0),
                           "kwp": round(n_ext * watt / 1000.0, 2), "azimuth_true": a.get("azimuth_true"),
                           "tilt": a.get("tilt"), "panels_per_string": pps_e,
                           "strings": max(1, int(math.ceil(n_ext / float(pps_e)))) if n_ext else 1,
                           "v_string": round(min(pps_e, n_ext or pps_e) * vmp, 1), "i_string": imp,
                           "conn": [round(x, 3) for x in a["conn"]], "external": True})
            continue
        if roof_kind == "none":
            warnings.append("array %s: scene has no roof. Give it an explicit \"conn\": [x, y, height] "
                            "(position from the roof app) or add a roof to lane 1/2" % a["id"])
            continue
        nm = a["face"]
        port = a.get("orientation", "portrait") == "portrait"
        pw, ph = (pw0, ph0) if port else (ph0, pw0)
        tilt = math.radians(a.get("tilt", 10))
        flat = roof_kind == "flat"
        if flat:
            fc = flat_face(nm, fp, eave_h)
        else:
            fc = faces.get(nm)
            if fc is None:
                warnings.append("array %s: roof has no face %r (faces: %s)" % (a["id"], nm, ",".join(faces)))
                continue
        rows, cols = a.get("rows", "max"), a.get("cols", "max")
        if rows == "max" or cols == "max":
            mr, mc = fit(fc, pw, ph, gap, sb, flat, tilt)
            rows = mr if rows == "max" else rows
            cols = mc if cols == "max" else cols
        if rows < 1 or cols < 1:
            warnings.append("array %s: no panel fits face %s" % (a["id"], nm))
            continue
        TU = cols * pw + (cols - 1) * gap
        if flat:
            pitch_v = ph * (math.cos(tilt) + math.sin(tilt) / math.tan(math.radians(20)))
            TV = (rows - 1) * pitch_v + ph * math.cos(tilt)
        else:
            pitch_v = ph + gap
            TV = rows * ph + (rows - 1) * gap
        if TU > fc["lu"] - 2 * sb + 1e-6 or TV > fc["lv"] - 2 * sb + 1e-6:
            warnings.append("array %s (%.1fx%.1f m) does not fit face %s (%.1fx%.1f m usable)" % (
                a["id"], TU, TV, nm, fc["lu"] - 2 * sb, fc["lv"] - 2 * sb))
        al = a.get("align", "center")
        if "u_offset" in a:
            u_start = a["u_offset"]
        elif al == "left":
            u_start = sb
        elif al == "right":
            u_start = fc["lu"] - sb - TU
        else:
            u_start = (fc["lu"] - TU) / 2.0
        v_start = a.get("v_offset", sb)
        O, u, v, n = fc["O"], fc["u"], fc["v"], fc["n"]
        lift = 0.05 if not flat else 0.25
        for r in range(rows):
            for c in range(cols):
                u0 = u_start + c * (pw + gap)
                v0 = v_start + r * pitch_v
                B = vadd(vadd(vadd(O, vmul(u, u0)), vmul(v, v0)), vmul(n, lift))
                if flat:
                    vt = vadd(vmul(v, math.cos(tilt)), (0.0, math.sin(tilt), 0.0))
                else:
                    vt = v
                P1 = B
                P2 = vadd(B, vmul(u, pw))
                P3 = vadd(P2, vmul(vt, ph))
                P4 = vadd(B, vmul(vt, ph))
                geo.quad(pos, P1, P2, P3, P4)
        conn = vadd(vadd(vadd(O, vmul(u, u_start + TU / 2.0)), vmul(v, v_start)), vmul(n, lift))
        npan = rows * cols
        total += npan
        pps = a.get("panels_per_string", npan)
        strings = max(1, int(math.ceil(npan / float(pps))))
        az = (fc["bearing"] - north_deg) % 360
        arrays.append({"id": a["id"], "face": nm, "panels": npan, "rows": rows, "cols": cols,
                       "kwp": round(npan * watt / 1000.0, 2), "azimuth_true": round(az),
                       "tilt": round(a.get("tilt", 10) if flat else fc["pitch"], 1),
                       "panels_per_string": pps, "strings": strings,
                       "v_string": round(min(pps, npan) * vmp, 1), "i_string": imp,
                       "conn": [round(x, 3) for x in conn]})
    return arrays, {"panels": total, "kwp": round(total * watt / 1000.0, 2)}


# ---------- equipment + cables ----------
def level_elev(levels, ref):
    lv = levels
    if isinstance(ref, int):
        return lv[ref].get("elevation", 0.0)
    for l in lv:
        if l.get("name") == ref:
            return l.get("elevation", 0.0)
    warnings.append("unknown level %r" % (ref,))
    return 0.0


def build_equipment(plan, levels):
    out = {}
    for e in plan.get("equipment", []):
        z = level_elev(levels, e.get("level", 0)) + e.get("height", 1.5)
        d = dict(e)
        d["p3"] = (e["pos"][0], z, e["pos"][1])
        out[e["id"]] = d
    return out


def manhattan(p, q, run_h):
    """Points after p that reach q using only vertical moves and X-then-Z horizontal moves."""
    if abs(p[0] - q[0]) < 1e-6 and abs(p[2] - q[2]) < 1e-6:
        return [q]
    if abs(p[1] - run_h) < 1e-6:  # travelling at run height: go sideways first, then change height
        return [(q[0], p[1], p[2]), (q[0], p[1], q[2]), q]
    # otherwise change height first (e.g. leaving a wall point), then go sideways
    return [(p[0], q[1], p[2]), (q[0], q[1], p[2]), q]


def route(start, end, via, run_h):
    """start -> up/down to run height -> via points -> end's plan position -> up/down to end."""
    pts = [start, (start[0], run_h, start[2])]
    for v in via:
        pts.append((v[0], v[2] if len(v) == 3 else run_h, v[1]))
    pts.append((end[0], run_h, end[2]))
    pts.append(end)
    path = [pts[0]]
    for q in pts[1:]:
        for p in manhattan(path[-1], q, run_h):
            if vlen(vsub(p, path[-1])) > 1e-6:
                path.append(p)
    return path


def build_cables(plan, arrays, equip, eave_h, roof_kind):
    arr = {a["id"]: a for a in arrays}
    default_run = eave_h - 0.25 if roof_kind in ("flat", "none") else eave_h + 0.4
    rows, paths = [], []
    for c in plan.get("cables", []):
        def end(ref):
            if ref in arr:
                return tuple(arr[ref]["conn"])
            if ref in equip:
                return equip[ref]["p3"]
            warnings.append("cable %s: unknown endpoint %r" % (c["id"], ref))
            return None
        s, e = end(c["from"]), end(c["to"])
        if s is None or e is None:
            continue
        run_h = c.get("run_height", default_run)
        path = route(s, e, c.get("via", []), run_h)
        route_m = sum(vlen(vsub(path[i + 1], path[i])) for i in range(len(path) - 1))
        slack = c.get("slack_pct", 10.0)
        term = c.get("termination_m", 1.0)
        cut = route_m * (1 + slack / 100.0) + term
        typ = c.get("type", "dc")
        size = c.get("size_mm2")
        cur, volt, phases = c.get("current_a"), c.get("voltage_v"), 1
        src_arr = arr.get(c["from"]) or arr.get(c["to"])
        src_eq = next((equip[x] for x in (c["from"], c["to"]) if x in equip and "kw" in equip[x]), None)
        if typ == "dc" and src_arr:
            cur = cur or src_arr["i_string"] * c.get("strings", 1)
            volt = volt or src_arr["v_string"]
        if typ == "ac" and src_eq:
            phases = src_eq.get("phases", 1)
            volt = volt or src_eq.get("ac_v", 230 if phases == 1 else 400)
            cur = cur or round(src_eq["kw"] * 1000.0 / (volt * (math.sqrt(3) if phases == 3 else 1)), 1)
        limit = c.get("max_drop_pct", 1.5 if typ == "dc" else 3.0)
        vd = pct = sugg = None
        status = "n/a"
        if typ in ("dc", "ac") and cur and volt and size:
            k = math.sqrt(3) if phases == 3 and typ == "ac" else 2.0
            vd = cur * RHO * k * route_m / size
            pct = 100.0 * vd / volt
            status = "OK" if pct <= limit else "DROP>%.1f%%" % limit
            for sz in SIZES:
                if cur * RHO * k * route_m / sz / volt * 100.0 <= limit:
                    sugg = sz
                    break
        nco = c.get("conductors", {"dc": 2, "ac": 5 if phases == 3 else 3}.get(typ, 1))
        rows.append({"id": c["id"], "type": typ, "from": c["from"], "to": c["to"],
                     "route_m": round(route_m, 1), "slack_pct": slack, "termination_m": term,
                     "cut_length_m": round(cut, 1), "conductors": nco,
                     "total_conductor_m": round(cut * nco, 1), "size_mm2": size,
                     "current_a": cur, "voltage_v": volt,
                     "vdrop_v": round(vd, 2) if vd is not None else None,
                     "vdrop_pct": round(pct, 2) if pct is not None else None,
                     "limit_pct": limit, "suggested_mm2": sugg, "status": status})
        paths.append({"id": c["id"], "type": typ,
                      "path": [[round(x, 3) for x in p] for p in path]})
    return rows, paths



# ---------- main ----------
def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    p = P.paths(sys.argv[1], create=True)
    if not os.path.isfile(p["scene"]):
        raise SystemExit("missing %s - run lane 2 first" % p["scene"])
    scene = P.load_json(p["scene"])
    if scene.get("schema") != "scene/1":
        raise SystemExit("scene.json has unknown schema %r" % scene.get("schema"))
    plan = P.load_json(p["pv_plan"]) if os.path.isfile(p["pv_plan"]) else {}
    faces = {f["name"]: f for f in scene["faces"]}
    fp, eave_h = tuple(scene["footprint"]), scene["eave_h"]
    roof_kind, north = scene["roof"]["type"], scene.get("north_deg", 0.0)

    cap = capacity(plan, faces, fp, eave_h, roof_kind) if plan else []
    geo = Geo()
    arrays, pvsum = build_pv(geo, plan, faces, fp, eave_h, roof_kind, north)
    equip = build_equipment(plan, scene["levels"])
    cables, paths = build_cables(plan, arrays, equip, eave_h, roof_kind)

    result = {
        "schema": "pv/1", "arrays": arrays, "pv": pvsum, "capacity": cap, "cables": cables,
        "equipment": [{"id": k, "kind": v.get("kind", "generic"), "p3": list(v["p3"]),
                       "label": v.get("label", k)} for k, v in equip.items()],
        "paths": paths, "warnings": warnings,
    }
    P.save_json(p["pv"], result)
    model = {k: scene[k] for k in ("name", "north_deg", "levels", "eave_h", "footprint")}
    model["groups"] = scene["groups"] + list(geo.groups.values())
    model["faces"] = [{k: f[k] for k in ("name", "azimuth_true", "pitch")} for f in scene["faces"]]
    model.update({k: result[k] for k in ("arrays", "pv", "equipment", "cables", "paths")})
    model["warnings"] = scene.get("warnings", []) + warnings
    P.render_viewer(model, p["viewer"])
    if cables:
        with open(p["csv"], "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(cables[0].keys()))
            w.writeheader()
            w.writerows(cables)

    print("== lane 3: %s ==" % scene["name"])
    for c in cap:
        print("capacity face %s: usable %.1f x %.1f m | portrait %d (%.1f kWp) | landscape %d (%.1f kWp)" % (
            c["face"], c["usable_m"][0], c["usable_m"][1], c["portrait"]["panels"], c["portrait"]["kwp"],
            c["landscape"]["panels"], c["landscape"]["kwp"]))
    for a in arrays:
        az = "?" if a["azimuth_true"] is None else "%d" % a["azimuth_true"]
        print("array %s: %d panels (%dx%d) on %s%s, az %s deg true, tilt %s, %.2f kWp, %d string(s) of %d, %.0f V / %.1f A" % (
            a["id"], a["panels"], a["rows"], a["cols"], a["face"], " [external]" if a.get("external") else "", az,
            "?" if a["tilt"] is None else a["tilt"], a["kwp"], a["strings"], a["panels_per_string"], a["v_string"], a["i_string"]))
    if pvsum["panels"]:
        print("PV total: %d panels, %.2f kWp" % (pvsum["panels"], pvsum["kwp"]))
    if cables:
        print("%-6s %-4s %8s %8s %6s %8s %8s %6s  %s" % ("cable", "type", "route_m", "cut_m", "mm2", "I(A)", "drop%", "sugg", "status"))
        for c in cables:
            print("%-6s %-4s %8s %8s %6s %8s %8s %6s  %s" % (
                c["id"], c["type"], c["route_m"], c["cut_length_m"], c["size_mm2"], c["current_a"],
                c["vdrop_pct"], c["suggested_mm2"], c["status"]))
    for w in warnings:
        print("WARNING:", w)
    print("wrote", p["pv"])
    print("wrote", p["viewer"])


if __name__ == "__main__":
    main()
