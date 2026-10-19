#!/usr/bin/env python3
"""Orchestrator. Lanes stay independent; this only chains them through their files.

  python3 pipeline/run.py doctor                check Python, Pillow, PyMuPDF, vendor checksums, Tavily key, projects dir
  python3 pipeline/run.py new <name>            create projects/<slug>/ folders
  python3 pipeline/run.py status <name>         which lane outputs exist / are stale
  python3 pipeline/run.py list                  all projects with a one-line state
  python3 pipeline/run.py run <name> [--with-pv]
        lane 1 gate (validate + plan_check) -> lane 2 (3D building).  --with-pv also runs lane 3 (needs 3_pv/pv_plan.json).

Lane 1's reading step (image -> house.json) is done by Claude; run.py never invents it.
Exit code is non-zero on any failure, so it is safe to use in scripts.
"""
import hashlib
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import project as P  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def sh(script, slug):
    r = subprocess.run([PY, os.path.join(HERE, script), slug])
    if r.returncode:
        raise SystemExit("stopped: %s failed (exit %d)" % (script, r.returncode))


def mt(path):
    return os.path.getmtime(path) if os.path.isfile(path) else None


def state(slug):
    p = P.paths(slug)
    if not os.path.isfile(p["house"]):
        n = len(os.listdir(p["source"])) if os.path.isdir(p["source"]) else 0
        return "lane 1 in progress (%d source file(s), no house.json)" % n
    if not os.path.isfile(p["scene"]):
        return "house.json ready, lane 2 not built"
    if mt(p["house"]) > mt(p["scene"]) + 1:
        return "3D model STALE (house.json is newer)"
    return "3D building built" + (" + PV" if os.path.isfile(p["pv"]) else "")


def status(slug):
    p = P.paths(slug)
    rows = [("lane 1  source files", p["source"], None), ("lane 1  house.json", p["house"], None),
            ("lane 2  scene.json", p["scene"], p["house"]), ("lane 2  model.html", p["model_html"], p["house"]),
            ("lane 3  pv_plan.json (input)", p["pv_plan"], None), ("lane 3  pv.json", p["pv"], p["scene"]),
            ("lane 3  viewer.html", p["viewer"], p["scene"])]
    print("project:", slug, "-", state(slug))
    for label, path, dep in rows:
        if os.path.isdir(path):
            n = len([f for f in os.listdir(path) if not f.startswith(".")])
            print("  %-30s %s" % (label, "%d file(s)" % n if n else "EMPTY"))
            continue
        t = mt(path)
        if t is None:
            print("  %-30s %s" % (label, "missing" if not label.startswith("lane 3") else "- (optional lane)"))
            continue
        stale = dep and mt(dep) and mt(dep) > t + 1
        if label.startswith("lane 3  pv") and mt(p["pv_plan"]) and mt(p["pv_plan"]) > t + 1:
            stale = True
        print("  %-30s %s%s" % (label, time.strftime("%Y-%m-%d %H:%M", time.localtime(t)), "   STALE - rebuild" if stale else ""))


def doctor():
    ok = True

    def line(flag, msg):
        nonlocal ok
        if flag == "FAIL":
            ok = False
        print("%-5s %s" % (flag, msg))

    v = sys.version_info
    line("OK" if v >= (3, 8) else "FAIL", "Python %d.%d.%d" % v[:3] + ("" if v >= (3, 8) else " (need 3.8+)"))
    try:
        import PIL
        line("OK", "Pillow %s (plan_check, image sizes)" % PIL.__version__)
    except ImportError:
        line("FAIL", "Pillow missing: pip install --user pillow")
    try:
        import fitz
        line("OK", "PyMuPDF %s (PDF brochures)" % fitz.__doc__.split()[1].rstrip(":"))
    except ImportError:
        line("WARN", "PyMuPDF missing - PDF sources can't be rendered: pip install --user pymupdf  (or brew install poppler)")
    vend = os.path.join(P.COMMON, "vendor")
    sums = os.path.join(vend, "SHA256SUMS")
    if os.path.isfile(sums):
        bad = []
        for ln in open(sums):
            digest, name = ln.split()
            f = os.path.join(vend, name)
            if not os.path.isfile(f) or hashlib.sha256(open(f, "rb").read()).hexdigest() != digest:
                bad.append(name)
        line("FAIL" if bad else "OK", "viewer libraries (three.js r147)" + (": CHANGED/MISSING " + ", ".join(bad) if bad else " match SHA256SUMS"))
    else:
        line("WARN", "vendor/SHA256SUMS missing")
    P.load_env()
    line("OK" if os.environ.get("TAVILY_API_KEY") else "WARN",
         "TAVILY_API_KEY " + ("is set" if os.environ.get("TAVILY_API_KEY") else "not set: search disabled (give a URL/file instead, or create .env from .env.example)"))
    line("OK", "projects dir: %s (%d project(s))" % (os.path.join(P.ROOT, "projects"), len(projects())))
    print("\nresult:", "READY" if ok else "NOT READY")
    return 0 if ok else 1


def projects():
    d = os.path.join(P.ROOT, "projects")
    return sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x)) and not x.startswith(("_", "."))) if os.path.isdir(d) else []


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "doctor":
        raise SystemExit(doctor())
    if cmd == "list":
        for s in projects():
            print("%-28s %s" % (s, state(s)))
        return
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    slug = P.slugify(sys.argv[2])
    p = P.paths(slug)
    if cmd == "new":
        P.paths(slug, create=True)
        print("created", p["base"])
    elif cmd == "status":
        status(slug)
    elif cmd == "run":
        if not os.path.isdir(p["base"]):
            raise SystemExit("no such project %r (run: new %s)" % (slug, slug))
        sh("lane1_floorplan/validate.py", slug)
        sh("lane1_floorplan/plan_check.py", slug)
        sh("lane2_model/build_model.py", slug)
        if "--with-pv" in sys.argv:
            if os.path.isfile(p["pv_plan"]):
                sh("lane3_pv/plan_pv.py", slug)
            else:
                print("lane 3 skipped: no %s" % p["pv_plan"])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
