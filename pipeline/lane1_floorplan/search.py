#!/usr/bin/env python3
"""LANE 1a - find floorplans for a residential project name with Tavily.

Usage:
  python3 pipeline/lane1_floorplan/search.py "Nada Alam Seri Pajam" [--project nada3a]
         [--country malaysia] [--n 8] [--depth basic|advanced] [--extra "double storey terrace"]

Needs TAVILY_API_KEY (in <repo>/.env or the environment). Runs several query variants, merges and ranks
the hits, and writes projects/<project>/1_floorplan/candidates.json. It only SEARCHES - nothing is
downloaded here (see fetch.py). Claude/the user picks which candidate to fetch.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import project as P  # noqa: E402
from common.net import open_with_retries  # noqa: E402

API = "https://api.tavily.com/search"
PLAN_WORDS = re.compile(r"floor ?plan|layout|unit type|type [a-z0-9]\b|brochure|leaflet|pdf|blueprint|plan", re.I)
STRONG = re.compile(r"floor ?plan|layout plan|unit layout|brochure|leaflet", re.I)


def tavily_search(key, query, n, depth, country):
    body = {"query": query, "search_depth": depth, "max_results": n,
            "include_images": True, "include_image_descriptions": True}
    if country:
        body["country"] = country
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with open_with_retries(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        hint = {401: "invalid TAVILY_API_KEY", 429: "rate limit", 432: "plan/credit limit", 433: "credit limit"}.get(e.code, "")
        raise SystemExit("Tavily HTTP %d %s: %s" % (e.code, hint, detail))


def kind_of(url):
    u = url.lower().split("?")[0]
    host = urlparse(url).netloc.lower()
    if u.endswith(".pdf"):
        return "pdf"
    if "issuu.com" in host and "/docs/" in u:
        return "issuu"
    if re.search(r"\.(jpe?g|png|webp|gif)$", u):
        return "image"
    return "page"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--project", help="project slug (default: slug of the query)")
    ap.add_argument("--country", default="")
    ap.add_argument("--n", type=int, default=8, help="results per query variant")
    ap.add_argument("--depth", default="basic", choices=["basic", "advanced", "fast", "ultra-fast"])
    ap.add_argument("--extra", default="", help="extra words appended to every variant, e.g. 'double storey terrace'")
    a = ap.parse_args()

    key = P.tavily_key()
    slug = a.project or P.slugify(a.query)
    p = P.paths(slug, create=True)
    base = (a.query + " " + a.extra).strip()
    variants = [base + " floor plan", base + " layout plan unit type brochure", base + " brochure pdf"]

    merged, images, credits = {}, {}, 0
    for q in variants:
        res = tavily_search(key, q, a.n, a.depth, a.country)
        credits += (res.get("usage") or {}).get("credits", 0)
        for r in res.get("results", []):
            url = r["url"]
            text = " ".join([r.get("title", ""), r.get("content", ""), url])
            bonus = 0.25 if STRONG.search(text) else (0.1 if PLAN_WORDS.search(text) else 0.0)
            kind = kind_of(url)
            bonus += {"pdf": 0.15, "issuu": 0.15, "image": 0.05}.get(kind, 0.0)
            c = merged.setdefault(url, {"url": url, "title": r.get("title", ""), "kind": kind,
                                        "tavily_score": r.get("score", 0), "rank": 0.0,
                                        "snippet": (r.get("content", "") or "")[:300], "images": [], "queries": []})
            c["tavily_score"] = max(c["tavily_score"], r.get("score", 0))
            c["rank"] = round(c["tavily_score"] + bonus, 3)
            c["queries"].append(q)
            for im in r.get("images", []) or []:
                if isinstance(im, dict):
                    c["images"].append(im)
                elif isinstance(im, str):
                    c["images"].append({"url": im, "description": ""})
        for im in res.get("images", []) or []:
            d = im if isinstance(im, dict) else {"url": im, "description": ""}
            images[d["url"]] = d

    results = sorted(merged.values(), key=lambda c: -c["rank"])
    for i, c in enumerate(results, 1):
        c["id"] = i
    plan_images = [d for d in images.values() if PLAN_WORDS.search((d.get("description") or "") + d["url"])]
    out = {"query": a.query, "variants": variants, "country": a.country, "credits_used": credits,
           "results": results, "images": list(images.values()), "plan_like_images": plan_images}
    P.save_json(p["candidates"], out)

    print("project slug: %s   (credits used: %s)" % (slug, credits))
    print("%-3s %-5s %-6s %-22s %s" % ("id", "rank", "kind", "domain", "title"))
    for c in results[:15]:
        print("%-3d %-5.2f %-6s %-22s %s" % (c["id"], c["rank"], c["kind"], urlparse(c["url"]).netloc[:22], c["title"][:70]))
    if plan_images:
        print("\nplan-like images found:")
        for d in plan_images[:8]:
            print("  -", d["url"], "|", (d.get("description") or "")[:70])
    print("\nwrote", p["candidates"])
    print("next: python3 pipeline/lane1_floorplan/fetch.py %s <url>" % slug)


if __name__ == "__main__":
    main()
