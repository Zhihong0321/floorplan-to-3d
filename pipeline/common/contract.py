"""The lane 1 -> lane 2 contract, in one place. `check_house` is used by validate.py (lane 1 gate) AND by
build_model.py (lane 2 refuses to build on a FAIL), so the two can never disagree about what a good house.json is.
"""
import math

LEVEL_KEYS = ("name", "elevation", "height", "walls", "openings", "rooms")
ROOF_TYPES = ("none", "gable", "shed", "flat")


def _area(poly):
    n = len(poly)
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))


def _is_xy(p):
    return isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p)


def check_house(h, source=None, tol=0.03):
    """Return {"FAIL": [...], "WARN": [...], "OK": [...]} for a parsed house.json (+ optional source.json)."""
    out = {"FAIL": [], "WARN": [], "OK": []}
    add = lambda lvl, msg: out[lvl].append(msg)

    if not isinstance(h, dict):
        add("FAIL", "house.json must be a JSON object")
        return out
    levels = h.get("levels")
    if not isinstance(levels, list) or not levels:
        add("FAIL", "no levels[]")
        return out
    elev = [l.get("elevation", 0) for l in levels if isinstance(l, dict)]
    if elev != sorted(elev):
        add("FAIL", "levels must be listed from lowest to highest elevation")

    pts = []
    for li, l in enumerate(levels):
        if not isinstance(l, dict):
            add("FAIL", "levels[%d] is not an object" % li)
            continue
        nm = l.get("name", "level %d" % li)
        if not (isinstance(l.get("height", 2.8), (int, float)) and 2.0 <= l.get("height", 2.8) <= 6.0):
            add("WARN", "level %s: height %s m looks unusual (expected 2-6 m)" % (nm, l.get("height")))
        walls = l.get("walls") or []
        if not walls:
            add("FAIL", "level %s has no walls" % nm)
        byid = {}
        for w in walls:
            wid = w.get("id")
            if not wid:
                add("FAIL", "level %s: a wall has no id" % nm)
                continue
            if wid in byid:
                add("FAIL", "level %s: duplicate wall id %s" % (nm, wid))
            if not (_is_xy(w.get("p1")) and _is_xy(w.get("p2"))):
                add("FAIL", "wall %s needs numeric p1 and p2 as [x, y]" % wid)
                continue
            byid[wid] = w
            if math.hypot(w["p2"][0] - w["p1"][0], w["p2"][1] - w["p1"][1]) < 0.05:
                add("FAIL", "wall %s is shorter than 5 cm" % wid)
            if "h" in w and not (0.2 <= w["h"] <= 8):
                add("WARN", "wall %s height override %s m looks unusual" % (wid, w["h"]))
            pts += [w["p1"], w["p2"]]
        spans = {}
        for o in l.get("openings") or []:
            w = byid.get(o.get("wall"))
            if not w:
                add("FAIL", "level %s: opening refers to unknown wall %r" % (nm, o.get("wall")))
                continue
            if "at" not in o:
                add("FAIL", "level %s: opening on %s has no 'at'" % (nm, w["id"]))
                continue
            L = math.hypot(w["p2"][0] - w["p1"][0], w["p2"][1] - w["p1"][1])
            kind = o.get("type", "window")
            if kind not in ("door", "window", "opening"):
                add("FAIL", "level %s: opening type %r must be door|window|opening" % (nm, kind))
            ow = o.get("w", 0.9 if kind == "door" else 1.2)
            a, b = o["at"] - ow / 2, o["at"] + ow / 2
            if a < -0.01 or b > L + 0.01:
                add("FAIL", "level %s: %s on %s (at %.2f, w %.2f) sticks out of the wall (length %.2f)" % (nm, kind, w["id"], o["at"], ow, L))
            for (a2, b2) in spans.get(w["id"], []):
                if a < b2 - 0.01 and b > a2 + 0.01:
                    add("FAIL", "level %s: two openings overlap on wall %s" % (nm, w["id"]))
            spans.setdefault(w["id"], []).append((a, b))
        for r in l.get("rooms") or []:
            poly = r.get("poly") or []
            if len(poly) < 3 or not all(_is_xy(p) for p in poly) or abs(_area(poly)) < 0.5:
                add("FAIL", "level %s: room %r has a degenerate polygon" % (nm, r.get("name")))
        if not l.get("rooms"):
            add("WARN", "level %s has no rooms (no floors/labels will show)" % nm)

    add("OK", "%d level(s), %d wall(s), %d opening(s), %d room(s)" % (
        len(levels), sum(len(l.get("walls") or []) for l in levels if isinstance(l, dict)),
        sum(len(l.get("openings") or []) for l in levels if isinstance(l, dict)),
        sum(len(l.get("rooms") or []) for l in levels if isinstance(l, dict))))

    if pts:
        w_m = max(x for x, _ in pts) - min(x for x, _ in pts)
        d_m = max(y for _, y in pts) - min(y for _, y in pts)
        add("OK", "footprint from walls: %.3f x %.3f m" % (w_m, d_m))
        dd = (source or {}).get("declared_dims") or {}
        for key, val in (("width_m", w_m), ("depth_m", d_m)):
            decl = dd.get(key)
            if not decl:
                continue
            err = abs(val - decl) / decl
            if err > tol:
                add("FAIL", "%s: house.json says %.3f but the plan says %.3f (%.0f%% off) - check the scale" % (key, val, decl, err * 100))
            else:
                add("OK", "%s matches the plan's printed dimension (%.3f vs %.3f, %.1f%% off)" % (key, val, decl, err * 100))
        if not any(dd.get(k) for k in ("width_m", "depth_m")):
            add("WARN", "no declared_dims in source.json - the scale is unverified. Add the dimensions printed on the plan.")

    roof = h.get("roof")
    if not roof or roof.get("type") == "none":
        add("OK", "roof: none - building only; the roof profile comes from the external roof app")
    else:
        if roof.get("type") not in ROOF_TYPES:
            add("FAIL", "roof.type must be none|gable|shed|flat")
        if roof.get("type") == "gable" and roof.get("ridge_axis") not in ("x", "y"):
            add("FAIL", "gable roof needs ridge_axis x|y")
        if roof.get("type") == "shed" and roof.get("falls_to") not in ("N", "S", "E", "W"):
            add("FAIL", "shed roof needs falls_to N|S|E|W")
        if roof.get("type") in ("gable", "shed") and not (3 <= roof.get("pitch_deg", 0) <= 50):
            add("WARN", "roof pitch %s deg looks unusual" % roof.get("pitch_deg"))
    if "north_deg" not in h:
        add("WARN", "north_deg not set (assumed 0: plan-up is north). Confirm orientation.")
    if h.get("_assumptions"):
        add("OK", "%d assumption(s) recorded in _assumptions" % len(h["_assumptions"]))
    else:
        add("WARN", "no _assumptions recorded - write down what you guessed (heights, wall thickness, orientation)")
    return out


def format_findings(out):
    lines = []
    for lvl in ("FAIL", "WARN", "OK"):
        lines += ["%-4s %s" % (lvl, m) for m in out[lvl]]
    lines.append("")
    lines.append("result: " + ("FAIL" if out["FAIL"] else ("PASS with warnings" if out["WARN"] else "PASS")))
    return "\n".join(lines)
