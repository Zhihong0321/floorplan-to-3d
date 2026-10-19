"""Regression tests for the pipeline. Stdlib unittest, no network (Tavily and downloads are mocked).

Run:  python3 pipeline/tests/run_tests.py
"""
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
sys.path.insert(0, PIPE)

from common import project as P  # noqa: E402
from common.contract import check_house  # noqa: E402
from lane1_floorplan import fetch, search  # noqa: E402
from lane2_model import build_model as bm  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def one_wall_house(openings=None, **extra):
    h = {"levels": [{"name": "G", "elevation": 0, "height": 3.0,
                     "walls": [{"id": "w", "p1": [0, 0], "p2": [4, 0]}],
                     "openings": openings or [],
                     "rooms": [{"name": "R", "poly": [[0, 0], [4, 0], [4, 3], [0, 3]]}]}],
         "_assumptions": ["test"], "north_deg": 0}
    h.update(extra)
    return h


class ContractTests(unittest.TestCase):
    def fails(self, h, source=None):
        return check_house(h, source)["FAIL"]

    def test_real_plan_passes(self):
        out = check_house(fx("lumina_house.json"), fx("lumina_source.json"))
        self.assertEqual(out["FAIL"], [])
        self.assertTrue(any("width_m matches" in m for m in out["OK"]))

    def test_roof_is_optional(self):
        out = check_house(fx("lumina_house.json"), fx("lumina_source.json"))
        self.assertTrue(any("roof: none" in m for m in out["OK"]))

    def test_no_levels(self):
        self.assertTrue(self.fails({}))
        self.assertTrue(self.fails({"levels": []}))
        self.assertTrue(self.fails([]))

    def test_opening_outside_wall(self):
        self.assertTrue(self.fails(one_wall_house([{"wall": "w", "type": "door", "at": 3.9, "w": 1.0}])))

    def test_opening_unknown_wall_and_bad_type(self):
        self.assertTrue(self.fails(one_wall_house([{"wall": "nope", "type": "door", "at": 1}])))
        self.assertTrue(self.fails(one_wall_house([{"wall": "w", "type": "gate", "at": 2}])))

    def test_overlapping_openings(self):
        ops = [{"wall": "w", "type": "window", "at": 1.5, "w": 1.2}, {"wall": "w", "type": "window", "at": 2.0, "w": 1.2}]
        self.assertTrue(any("overlap" in m for m in self.fails(one_wall_house(ops))))

    def test_duplicate_wall_id_and_bad_points(self):
        h = one_wall_house()
        h["levels"][0]["walls"].append({"id": "w", "p1": [0, 1], "p2": [4, 1]})
        self.assertTrue(any("duplicate" in m for m in self.fails(h)))
        h = one_wall_house()
        h["levels"][0]["walls"][0]["p1"] = ["a", "b"]
        self.assertTrue(self.fails(h))

    def test_degenerate_room(self):
        h = one_wall_house()
        h["levels"][0]["rooms"] = [{"name": "line", "poly": [[0, 0], [1, 0], [2, 0]]}]
        self.assertTrue(self.fails(h))

    def test_declared_dims_mismatch_fails(self):
        src = {"declared_dims": {"width_m": 6.0, "depth_m": 1.0}}
        self.assertTrue(any("width_m" in m for m in self.fails(one_wall_house(), src)))

    def test_roof_field_rules(self):
        self.assertTrue(self.fails(one_wall_house(roof={"type": "gable", "pitch_deg": 20})))      # no ridge_axis
        self.assertTrue(self.fails(one_wall_house(roof={"type": "shed", "pitch_deg": 10})))       # no falls_to
        self.assertTrue(self.fails(one_wall_house(roof={"type": "dome"})))
        self.assertEqual(self.fails(one_wall_house(roof={"type": "none"})), [])


class Lane2Tests(unittest.TestCase):
    def setUp(self):
        bm.warnings.clear()

    def test_building_only_has_no_roof(self):
        s = bm.build(fx("lumina_house.json"))
        self.assertEqual(s["schema"], "scene/1")
        self.assertEqual(s["roof"]["type"], "none")
        self.assertEqual(s["faces"], [])
        self.assertNotIn("roof", [g["name"] for g in s["groups"]])
        self.assertAlmostEqual(s["building"]["top_h"], 6.3, places=2)
        x0, y0, x1, y1 = s["building"]["footprint"]
        self.assertAlmostEqual(x1 - x0, 7.315, places=2)   # fences (h override) are not part of the building
        self.assertAlmostEqual(y0, 3.34, places=2)
        self.assertGreater(sum(len(g["positions"]) for g in s["groups"] if g["layer"] == "walls"), 5000)

    def test_openings_cut_the_wall(self):
        # one 4 m wall, a 1 m door in the middle: solid left + solid right + header above the door = 3 boxes = 36 triangles
        s = bm.build(one_wall_house([{"wall": "w", "type": "door", "at": 2.0, "w": 1.0}]))
        solid = [g for g in s["groups"] if g["name"].startswith("wall_")]
        self.assertEqual(sum(len(g["positions"]) for g in solid), 36 * 9)
        self.assertTrue(any(g["name"] == "door" and len(g["positions"]) == 2 * 9 for g in s["groups"]))
        # a doorless 'opening' leaves a gap but draws no leaf
        s2 = bm.build(one_wall_house([{"wall": "w", "type": "opening", "at": 2.0, "w": 1.0}]))
        self.assertFalse(any(g["name"] == "door" for g in s2["groups"]))

    def test_deterministic(self):
        a = bm.build(fx("lumina_house.json"))
        bm.warnings.clear()
        b = bm.build(fx("lumina_house.json"))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_optional_roofs_still_work(self):
        s = bm.build(fx("demo_house_with_roof.json"))
        self.assertEqual({f["name"] for f in s["faces"]}, {"N", "S"})
        self.assertIn("roof", [g["name"] for g in s["groups"]])
        base = fx("demo_house_with_roof.json")
        for roof in ({"type": "flat", "overhang": 0.3}, {"type": "shed", "falls_to": "S", "pitch_deg": 12, "overhang": 0.4}):
            h = copy.deepcopy(base)
            h["roof"] = roof
            bm.warnings.clear()
            self.assertEqual(bm.build(h)["roof"]["type"], roof["type"])

    def test_viewer_renders_without_leftover_placeholders(self):
        s = bm.build(fx("lumina_house.json"))
        s.update(P.empty_pv_fields())
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "v.html")
            P.render_viewer(s, out)
            html = open(out, encoding="utf-8").read()
        self.assertIn("Precinct Lumina", html)
        for token in ("/*__THREE__*/", "/*__ORBIT__*/", "/*__GLTF__*/", "/*__MODEL__*/"):
            self.assertNotIn(token, html)
        self.assertGreater(len(html), 500000)  # three.js is inlined: the file works offline


class SearchTests(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual(search.kind_of("https://x.com/a/b.PDF?x=1"), "pdf")
        self.assertEqual(search.kind_of("https://issuu.com/pub/docs/name"), "issuu")
        self.assertEqual(search.kind_of("https://x.com/plan.jpg"), "image")
        self.assertEqual(search.kind_of("https://x.com/page"), "page")

    def test_ranking_and_candidates_file(self):
        canned = {"results": [
            {"url": "https://a.com/listing", "title": "Houses for sale", "content": "nice houses", "score": 0.6},
            {"url": "https://b.com/brochure.pdf", "title": "Project E-Brochure floor plan", "content": "floor plan type A", "score": 0.5,
             "images": [{"url": "https://b.com/i.jpg", "description": "floor plan"}]}],
            "images": [{"url": "https://c.com/layout.png", "description": "unit layout plan"}], "usage": {"credits": 1}}
        with tempfile.TemporaryDirectory() as root:
            old_root, old_argv = P.ROOT, sys.argv
            old_ts, old_key = search.tavily_search, search.P.tavily_key
            try:
                P.ROOT = root
                search.tavily_search = lambda *a, **k: copy.deepcopy(canned)
                search.P.tavily_key = lambda: "tvly-test"
                sys.argv = ["search.py", "Some Project", "--project", "t1"]
                with contextlib_redirect():
                    search.main()
                cands = json.load(open(P.paths("t1")["candidates"]))
            finally:
                P.ROOT, sys.argv = old_root, old_argv
                search.tavily_search, search.P.tavily_key = old_ts, old_key
        self.assertEqual(cands["results"][0]["url"], "https://b.com/brochure.pdf")   # pdf + plan words outrank a plain listing
        self.assertEqual(cands["results"][0]["kind"], "pdf")
        self.assertTrue(cands["plan_like_images"])
        self.assertEqual(cands["credits_used"], 3)  # three query variants
        self.assertNotIn("tvly", json.dumps(cands))  # the key is never written to disk


class contextlib_redirect:
    def __enter__(self):
        self._old = sys.stdout
        sys.stdout = io.StringIO()

    def __exit__(self, *a):
        sys.stdout = self._old


def png_bytes():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (1200, 800), (240, 240, 240)).save(b, "PNG")
    return b.getvalue()


class FetchTests(unittest.TestCase):
    def run_fetch(self, url, http, *extra):
        with tempfile.TemporaryDirectory() as root:
            old_root, old_argv, old_get = P.ROOT, sys.argv, fetch.http_get
            try:
                P.ROOT = root
                fetch.http_get = http
                sys.argv = ["fetch.py", "t1", url] + list(extra)
                with contextlib_redirect():
                    fetch.main()
                p = P.paths("t1")
                files = sorted(os.listdir(p["source"]))
                src = json.load(open(p["source_json"]))
            finally:
                P.ROOT, sys.argv, fetch.http_get = old_root, old_argv, old_get
        return files, src

    def test_direct_image_records_provenance(self):
        files, src = self.run_fetch("https://x.com/plans/Type-A.jpg", lambda u, binary=True: (png_bytes(), "image/jpeg"),
                                    "--declare", "width=7.3,depth=21.3")
        self.assertEqual(files, ["Type-A.jpg"])
        self.assertEqual(src["sources"][0]["url"], "https://x.com/plans/Type-A.jpg")
        self.assertEqual(src["declared_dims"]["width_m"], 7.3)

    def test_issuu_pages_stop_at_first_404(self):
        doc = "210522050056-bea4740fe2eb6f8f016b5b918d5142ae"

        def http(url, binary=True):
            if "issuu.com/" in url and binary is False:
                return ('<meta property="og:image" content="https://image.isu.pub/%s/jpg/page_1_social_preview.jpg">' % doc), "text/html"
            n = int(url.rsplit("page_", 1)[1].split(".")[0])
            if n > 2:
                raise urllib.error.HTTPError(url, 404, "nf", {}, None)
            return png_bytes(), "image/jpeg"
        files, src = self.run_fetch("https://issuu.com/pub/docs/my_leaflet", http)
        self.assertEqual(files, ["issuu_my_leaflet_p1.jpg", "issuu_my_leaflet_p2.jpg"])
        self.assertEqual(src["sources"][0]["kind"], "issuu-document")

    def test_issuu_without_doc_id_is_a_clear_error(self):
        with self.assertRaises(SystemExit):
            self.run_fetch("https://issuu.com/pub/docs/x", lambda u, binary=True: ("<html></html>", "text/html"))

    def test_pdf_is_rendered_to_png(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        d = fitz.open()
        for i in range(3):
            d.new_page(width=300, height=200).insert_text((20, 50), "page %d" % (i + 1))
        pdf = d.tobytes()
        files, src = self.run_fetch("https://x.com/b/brochure.pdf", lambda u, binary=True: (pdf, "application/pdf"), "--pages", "2,3")
        self.assertIn("brochure.pdf", files)
        self.assertEqual(len([f for f in files if f.endswith(".png")]), 2)

    def test_non_http_scheme_rejected(self):
        with self.assertRaises(SystemExit):
            self.run_fetch("file:///etc/passwd", lambda u, binary=True: (b"", ""))


class CliIntegrationTests(unittest.TestCase):
    """Whole CLI in a throwaway FLOORPLAN_ROOT: lane 1 gate -> plan_check -> lane 2 (and lane 3 when asked)."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.env = dict(os.environ, FLOORPLAN_ROOT=self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def project(self, slug, house, source=None, pv_plan=None):
        base = os.path.join(self.root, "projects", slug)
        os.makedirs(os.path.join(base, "1_floorplan"))
        json.dump(house, open(os.path.join(base, "1_floorplan", "house.json"), "w"))
        if source:
            json.dump(source, open(os.path.join(base, "1_floorplan", "source.json"), "w"))
        if pv_plan:
            os.makedirs(os.path.join(base, "3_pv"))
            json.dump(pv_plan, open(os.path.join(base, "3_pv", "pv_plan.json"), "w"))
        return base

    def cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(PIPE, "run.py")] + list(args), env=self.env,
                              capture_output=True, text=True)

    def test_full_run_building_only(self):
        base = self.project("t1", fx("lumina_house.json"), fx("lumina_source.json"))
        r = self.cli("run", "t1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in ("1_floorplan/plan_check_ground.png", "1_floorplan/plan_check_first.png", "2_model/scene.json", "2_model/model.html"):
            self.assertTrue(os.path.getsize(os.path.join(base, rel)) > 1000, rel)
        self.assertIn("3D building built", self.cli("list").stdout)
        self.assertFalse(os.path.exists(os.path.join(base, "3_pv", "pv.json")))   # lane 3 is opt-in

    def test_gate_blocks_bad_house(self):
        bad = one_wall_house([{"wall": "w", "type": "door", "at": 3.9, "w": 1.0}])
        base = self.project("t2", bad)
        r = self.cli("run", "t2")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(base, "2_model", "scene.json")))
        # lane 2 on its own refuses too, unless forced
        r2 = subprocess.run([sys.executable, os.path.join(PIPE, "lane2_model", "build_model.py"), "t2"], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn("refuses", r2.stdout + r2.stderr)

    def test_invalid_json_is_a_clean_error(self):
        base = self.project("t3", one_wall_house())
        open(os.path.join(base, "1_floorplan", "house.json"), "w").write("{not json")
        r = self.cli("run", "t3")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_optional_lane3_with_roof(self):
        self.project("t4", fx("nada_house_with_roof.json"), pv_plan=fx("nada_pv_plan.json"))
        r = self.cli("run", "t4", "--with-pv")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pv = json.load(open(os.path.join(self.root, "projects", "t4", "3_pv", "pv.json")))
        self.assertEqual(pv["pv"]["panels"], 12)
        self.assertEqual([c["status"] for c in pv["cables"]], ["OK", "OK"])

    def test_lane3_without_roof_uses_external_array_position(self):
        plan = {"schema": "pv_plan/1", "panel": {"w": 1.134, "h": 2.278, "watt": 550, "vmp": 41.7, "imp": 13.2},
                "arrays": [{"id": "A1", "conn": [3.6, 9.0, 6.4], "panels": 12, "panels_per_string": 6}],
                "equipment": [{"id": "inverter", "kind": "inverter", "pos": [7.0, 12.0], "level": 0, "height": 1.5, "kw": 5, "phases": 1}],
                "cables": [{"id": "DC1", "type": "dc", "from": "A1", "to": "inverter", "size_mm2": 4}]}
        self.project("t5", fx("lumina_house.json"), fx("lumina_source.json"), pv_plan=plan)
        r = self.cli("run", "t5", "--with-pv")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pv = json.load(open(os.path.join(self.root, "projects", "t5", "3_pv", "pv.json")))
        self.assertEqual(pv["warnings"], [])
        self.assertGreater(pv["cables"][0]["route_m"], 5)
        self.assertEqual(pv["capacity"], [])

    def test_doctor_runs(self):
        r = self.cli("doctor")
        self.assertIn("viewer libraries", r.stdout)


if __name__ == "__main__":
    unittest.main()
