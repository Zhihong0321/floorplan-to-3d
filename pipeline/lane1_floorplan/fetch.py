#!/usr/bin/env python3
"""LANE 1b - download a chosen floorplan source into projects/<p>/1_floorplan/source/.

Usage:
  python3 pipeline/lane1_floorplan/fetch.py <project> <url> [--pages 4,5] [--max-pages 12]
         [--declare width=6.706,depth=21.336] [--note "text"] [--plan-images]

Handles: Issuu document URLs (page images), direct image URLs, PDFs (rendered to PNG with pdftoppm or
PyMuPDF), and ordinary web pages (lists PDF/plan-image links; --plan-images downloads the plan-like ones).
Every download is recorded in source.json (url, files, time) so the provenance is never lost.
Stdlib + Pillow only.
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import project as P  # noqa: E402
from common.net import open_with_retries  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"}
MAX_BYTES = 40 * 1024 * 1024
PLAN_RE = re.compile(r"floor ?plan|layout|unit|type|plan|blueprint|brochure", re.I)


def http_get(url, binary=True):
    req = urllib.request.Request(url, headers=UA)
    with open_with_retries(req, timeout=40) as r:
        data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise SystemExit("download larger than %d MB, aborting: %s" % (MAX_BYTES // 2 ** 20, url))
        return (data if binary else data.decode("utf-8", "replace")), r.headers.get("Content-Type", "")


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:80]


def describe_image(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        note = "" if w >= 1000 else "  (LOW-RES: <1000 px wide - dimensions may be hard to read)"
        return "%dx%d%s" % (w, h, note)
    except Exception:
        return "?"


def save(dirpath, name, data):
    path = os.path.join(dirpath, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def fetch_issuu(url, out, pages, max_pages):
    html, _ = http_get(url, binary=False)
    m = re.search(r"image\.isu\.pub/([0-9]{6,}-[0-9a-f]{32})/", html)
    if not m:
        raise SystemExit("could not find the Issuu document id on that page")
    doc = m.group(1)
    slug = safe_name(urlparse(url).path.strip("/").split("/")[-1])
    files, n = [], 1
    wanted = pages or list(range(1, max_pages + 1))
    for n in wanted:
        try:
            data, _ = http_get("https://image.isu.pub/%s/jpg/page_%d.jpg" % (doc, n))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                if not pages:
                    break
                print("  page %d not available" % n)
                continue
            raise
        files.append(save(out, "issuu_%s_p%d.jpg" % (slug, n), data))
    return files, "issuu-document"


def render_pdf(pdf_path, out, pages, max_pages):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    if shutil.which("pdftoppm"):
        first, last = (min(pages), max(pages)) if pages else (1, max_pages)
        subprocess.run(["pdftoppm", "-r", "150", "-f", str(first), "-l", str(last), "-png", pdf_path,
                        os.path.join(out, stem)], check=True)
        files = sorted(os.path.join(out, f) for f in os.listdir(out) if f.startswith(stem + "-") and f.endswith(".png"))
        return files
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("  PDF saved but cannot be rendered: install ONE of:  brew install poppler   |   pip install pymupdf")
        return []
    doc = fitz.open(pdf_path)
    files = []
    for i in (pages or range(1, min(len(doc), max_pages) + 1)):
        if 1 <= i <= len(doc):
            pix = doc[i - 1].get_pixmap(dpi=150)
            f = os.path.join(out, "%s-%d.png" % (stem, i))
            pix.save(f)
            files.append(f)
    return files


def fetch_page(url, out, grab):
    html, _ = http_get(url, binary=False)
    found = []
    for m in re.finditer(r"""(?:href|src|data-src)\s*=\s*["']([^"'#]+?\.(?:pdf|jpe?g|png|webp))(?:\?[^"']*)?["']""", html, re.I):
        found.append(urljoin(url, m.group(1)))
    found = list(dict.fromkeys(found))
    plan_like = [u for u in found if PLAN_RE.search(u)]
    print("  %d pdf/image links on the page, %d look plan-related:" % (len(found), len(plan_like)))
    for u in (plan_like or found)[:25]:
        print("   ", u)
    files = []
    if grab:
        for u in plan_like[:12]:
            try:
                data, _ = http_get(u)
            except Exception as e:  # noqa: BLE001
                print("  skip", u, e)
                continue
            files.append(save(out, safe_name(os.path.basename(urlparse(u).path)), data))
    return files, "web-page"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("url")
    ap.add_argument("--pages", help="comma list, e.g. 4,5")
    ap.add_argument("--max-pages", type=int, default=12)
    ap.add_argument("--declare", help="declared plan size in metres, e.g. width=6.706,depth=21.336")
    ap.add_argument("--note", default="")
    ap.add_argument("--plan-images", action="store_true", help="web pages: download plan-like images/PDFs found")
    a = ap.parse_args()

    p = P.paths(a.project, create=True)
    pages = [int(x) for x in a.pages.split(",")] if a.pages else None
    host = urlparse(a.url).netloc.lower()
    raw_path = urlparse(a.url).path          # original case: used for file names
    path = raw_path.lower()                  # lowercase: used for matching only
    files, kind = [], "unknown"

    if not re.match(r"^https?://", a.url):
        raise SystemExit("only http(s) URLs are supported")
    if "issuu.com" in host and "/docs/" in path:
        files, kind = fetch_issuu(a.url, p["source"], pages, a.max_pages)
    elif re.search(r"\.(jpe?g|png|webp|gif)$", path):
        data, _ = http_get(a.url)
        files, kind = [save(p["source"], safe_name(os.path.basename(raw_path)), data)], "image"
    elif path.endswith(".pdf"):
        data, _ = http_get(a.url)
        pdf = save(p["source"], safe_name(os.path.basename(raw_path)), data)
        files, kind = [pdf] + render_pdf(pdf, p["source"], pages, a.max_pages), "pdf"
    else:
        data, ctype = http_get(a.url)
        if "pdf" in ctype.lower():
            pdf = save(p["source"], safe_name(raw_path.strip("/").split("/")[-1] or "doc") + ".pdf", data)
            files, kind = [pdf] + render_pdf(pdf, p["source"], pages, a.max_pages), "pdf"
        elif ctype.lower().startswith("image/"):
            files, kind = [save(p["source"], safe_name(raw_path.strip("/").split("/")[-1] or "img") + ".img", data)], "image"
        else:
            files, kind = fetch_page(a.url, p["source"], a.plan_images)

    rel = [os.path.relpath(f, p["l1"]) for f in files]
    src = P.load_json(p["source_json"]) if os.path.isfile(p["source_json"]) else {"schema": "source/1", "sources": []}
    if a.declare:
        d = dict(kv.split("=") for kv in a.declare.split(","))
        src["declared_dims"] = {"width_m": float(d.get("width", 0)) or None, "depth_m": float(d.get("depth", 0)) or None}
    if files:
        src["sources"].append({"url": a.url, "kind": kind, "files": rel, "note": a.note,
                               "fetched_at": datetime.datetime.now().isoformat(timespec="seconds")})
    P.save_json(p["source_json"], src)

    print("kind: %s | files: %d" % (kind, len(files)))
    for f in files:
        print("  ", os.path.relpath(f, P.ROOT), describe_image(f) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else "")
    print("wrote", p["source_json"])
    print("next: LOOK at the images, then write", os.path.relpath(p["house"], P.ROOT))


if __name__ == "__main__":
    main()
