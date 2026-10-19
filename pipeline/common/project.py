"""Project folder layout, .env loading and the shared viewer renderer.

projects/<slug>/
  1_floorplan/  source/ source.json candidates.json house.json plan_check_*.png     (lane 1 writes)
  2_model/      scene.json model.html                                               (lane 2 writes)
  3_pv/         pv_plan.json pv.json cable_schedule.csv viewer.html                 (lane 3 writes; pv_plan.json is its input)
"""
import json
import os
import re

# FLOORPLAN_ROOT lets tests (or you) keep projects/.env somewhere else than next to the code
ROOT = os.environ.get("FLOORPLAN_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMMON = os.path.dirname(os.path.abspath(__file__))


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "project"


def paths(slug, create=False):
    base = os.path.join(ROOT, "projects", slug)
    p = {
        "base": base,
        "l1": os.path.join(base, "1_floorplan"),
        "source": os.path.join(base, "1_floorplan", "source"),
        "l2": os.path.join(base, "2_model"),
        "l3": os.path.join(base, "3_pv"),
    }
    p.update({
        "source_json": os.path.join(p["l1"], "source.json"),
        "candidates": os.path.join(p["l1"], "candidates.json"),
        "house": os.path.join(p["l1"], "house.json"),
        "scene": os.path.join(p["l2"], "scene.json"),
        "model_html": os.path.join(p["l2"], "model.html"),
        "pv_plan": os.path.join(p["l3"], "pv_plan.json"),
        "pv": os.path.join(p["l3"], "pv.json"),
        "csv": os.path.join(p["l3"], "cable_schedule.csv"),
        "viewer": os.path.join(p["l3"], "viewer.html"),
    })
    if create:
        for k in ("source", "l2", "l3"):
            os.makedirs(p[k], exist_ok=True)
    return p


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj, indent=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)


def load_env():
    """Read KEY=VALUE lines from <root>/.env into os.environ (real env vars win). No dependencies."""
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def tavily_key():
    load_env()
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        raise SystemExit("TAVILY_API_KEY not set. Put it in %s/.env as TAVILY_API_KEY=tvly-... "
                         "(see .env.example) or export it in the shell." % ROOT)
    return key


def render_viewer(model, out_path):
    """Write one self-contained HTML viewer (three.js inlined) for a scene [+ PV] model dict."""
    rd = lambda *a: open(os.path.join(COMMON, *a), encoding="utf-8").read()
    html = (rd("viewer_template.html")
            .replace("/*__THREE__*/", rd("vendor", "three.min.js"))
            .replace("/*__ORBIT__*/", rd("vendor", "OrbitControls.js"))
            .replace("/*__GLTF__*/", rd("vendor", "GLTFExporter.js"))
            .replace("/*__MODEL__*/", json.dumps(model).replace("</", "<\\/")))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


def empty_pv_fields():
    return {"arrays": [], "pv": {"panels": 0, "kwp": 0.0}, "equipment": [], "cables": [], "paths": []}
