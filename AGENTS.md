# AGENTS.md - how an AI agent uses this pipeline

> Read this file first. It is written for an AI agent (Claude Code or similar) that has been asked to
> "get the floorplan of <residential project> and make a 3D model of the house".
> Humans: the same content works as a manual. File formats are specified in `CONTRACTS.md`.

## 1. What this pipeline does (and does not)

**Input:** a residential project name (e.g. "Taman Daiman Jaya, Kota Tinggi"), or a floorplan URL / PDF / image.
**Output:** a 3D model of the **building shell** (walls, openings, floors, labelled rooms, level heights) as a
self-contained `model.html` viewer + `scene.json` (+ GLB export button in the viewer).

**The roof is deliberately NOT modelled.** The owner has a separate app (Google Open Buildings + Google Solar API) that
produces building height and the roof profile for panel placement; the two are combined later. So:
- Do not read, guess or draw roofs. Leave `roof` out of `house.json`.
- Do not place solar panels. Lane 3 (panels + cables) exists but is **optional** and out of scope unless asked.

Purpose behind it: home solar PV cable planning. Cable lengths need correct room layout, wall positions and storey heights.

## 2. Architecture: three lanes, file contracts, strict ownership

```
 project name / URL / image
        |
 LANE 1  floorplan   search -> fetch -> READ (you, with vision) -> validate -> plan_check
        |            writes projects/<slug>/1_floorplan/  house.json  source.json  plan_check_*.png
 LANE 2  model       house.json -> 3D building            writes projects/<slug>/2_model/  scene.json  model.html
        |
 LANE 3  pv + cables (OPTIONAL) scene.json + pv_plan.json -> panels/cables   writes projects/<slug>/3_pv/
```

Rules that keep it durable:
1. **A lane only reads the previous lane's files and only writes its own folder.** Never patch `house.json` from lane 2 or
   later; report the problem back to lane 1 and fix it there.
2. **Lane 2 refuses to build when `house.json` fails the contract check** (`pipeline/common/contract.py`, same code as
   `validate.py`). Fix lane 1; `--force` exists but is for debugging only.
3. Everything is deterministic and re-runnable. `run.py status` tells you what is stale.
4. Python 3.8+ standard library + Pillow (+ PyMuPDF only for PDFs). No other dependencies. The viewer works offline.

## 3. Cheat sheet (all commands run from the repo root)

```bash
python3 pipeline/run.py doctor                    # environment check -> READY / NOT READY
python3 pipeline/run.py new "<project name>"      # creates projects/<slug>/
python3 pipeline/run.py list                      # all projects + state
python3 pipeline/run.py status <slug>             # which files exist / are STALE
python3 pipeline/run.py run <slug>                # lane 1 gate (validate + plan_check) -> lane 2. Exit code != 0 on failure
python3 pipeline/run.py run <slug> --with-pv      # ...and lane 3 if 3_pv/pv_plan.json exists (optional)
python3 pipeline/tests/run_tests.py               # 28 offline regression tests; run after ANY code change

# lane 1 tools
python3 pipeline/lane1_floorplan/search.py "<project>" --project <slug> [--country malaysia] [--extra "double storey terrace"]
python3 pipeline/lane1_floorplan/fetch.py <slug> <url> [--pages 4,5] [--declare width=7.315,depth=21.336] [--note "..."]
python3 pipeline/lane1_floorplan/validate.py <slug>
python3 pipeline/lane1_floorplan/plan_check.py <slug>
python3 pipeline/lane2_model/build_model.py <slug>
```

Slash skills (if available): `/floorplan-to-3d` (whole flow), `/lane1-floorplan`, `/lane2-model`, `/lane3-pv`.

## 4. Decision tree: what to do with the request

| The user gives you | Do |
|---|---|
| A project name only | Lane 1 step A (search), then B, C, then lane 2 |
| A URL (page, PDF, Issuu, image) | `fetch.py` directly, then read |
| A file / pasted image | If it only exists in the chat, you can still read it, but ask for the file or URL so provenance is stored; note this in `source.json` |
| An existing project slug | `status`, rebuild only what is stale |
| "Place panels / plan cables" | Out of scope by default. Confirm, then use lane 3 (section 8) |

Always run `doctor` first in a new session if anything misbehaves.

## 5. LANE 1 - find and read the floorplan (the part that needs judgement)

### 5A. Find
1. `search.py "<project>" --project <slug> --country malaysia`. Needs `TAVILY_API_KEY` in `<repo>/.env`.
   Never print, log or commit the key. HTTP 401 = bad key; **HTTP 432/433 = the key's plan/usage limit is exhausted
   (not a bug)** -> tell the user, then use the browser pane (search engine) or ask for a URL.
2. Read `candidates.json`. Prefer, in order: developer's official brochure PDF > Issuu/e-brochure > developer project page >
   property portals (iProperty, PropertyGuru, NuProp, EdgeProp, JohorProjects). Marketing "site plans" are NOT unit plans:
   look for ground + first floor drawings with dimensions. Matterport/3D tours are not plans.
3. **Ambiguity -> ask the user** before reading: several unit types (A/B/C/D), phases, a similar-sounding project
   (e.g. "Damai" vs "Daiman"), intermediate vs end/corner unit. Show 1-3 candidates with links.

### 5B. Fetch
`fetch.py <slug> <url>`: handles Issuu documents (page images), direct images, PDFs (rendered with PyMuPDF/pdftoppm) and web
pages (lists plan-like links; `--plan-images` downloads them). Each download is logged to `source.json`.
Download only what the user asked for. Check the printed resolution; `LOW-RES` means dimensions may be unreadable.
Brochures are marketing material: private prototyping use, keep the source URL.

### 5C. Read -> `house.json`
Procedure that works (it produced 0.0 % dimension error on the test plans):
1. **View** every image with the Read tool. Identify: target unit (leaflets often show a **mirrored pair** - pick one and say
   which), levels, overall printed dimensions (mm or ft), north arrow (usually absent), section/elevation (for storey heights).
2. **Enlarge with a pixel ruler.** Crop each floor, upscale 4x with Pillow, draw tick lines every 20 source pixels labelled with
   source-pixel coordinates, then read wall positions off the ruler. Do not eyeball from the full image.
3. **Calibrate scale from printed dimensions**: `px_per_m = (pixel distance between two dimension ticks) / (printed length in m)`.
   Cross-check with a second, perpendicular dimension (agree within ~1-2 %). Typical leaflet: ~20-25 px/m (~5 cm/pixel).
   Convert feet: 1 ft = 0.3048 m (22' = 6.706 m, 24' = 7.315 m, 70' = 21.336 m).
4. **Coordinates:** x to the right, y DOWN (as drawn), metres, origin = a corner of the unit/plot. `x_m = (px - x0)/s`, `y_m = (py - y0)/s`.
   All levels share the same origin so floors line up.
5. **Walls are centre lines** `{id, p1, p2}`; thickness `t` default 0.15 ext / 0.10 int. Exterior is auto-detected when both ends
   lie on the outer bounding box; set `"ext": true` on perimeter walls that do not. `"h"` overrides height (fences, parapets).
6. **Openings** sit on a wall: `{wall, type: door|window|opening, at, w, sill, h}` where `at` = distance from `p1` to the opening
   **centre**. `opening` = doorless gap. Stay inside the wall (validator fails otherwise).
7. **Rooms** are polygons (>= 3 points, non-degenerate) with the label from the plan. They become floors + labels.
8. **Levels** lowest first: `elevation`, `height` (floor to floor). Take heights from a section if present, else assume
   (ground ~3.3 m, upper ~3.0 m) and record it.
9. **Make the printed overall size reproducible:** put it in `source.json -> declared_dims {width_m, depth_m}`. If the plan's
   total depth includes things outside the building (rear garden, drive), model them as low `h`-override boundary walls so the
   wall bounding box equals the printed size (that is how the validator proves your scale).
10. **Record every guess** in `house.json -> "_assumptions"` (north direction, heights, wall thickness, which unit). Keys that
    start with `_` are ignored by code and are your notebook. `north_deg` = clockwise angle of the north arrow from plan-up
    (0 = plan-up is north; flag it as unconfirmed when there is no arrow).
11. **Leave `roof` out.**

Minimal valid `house.json`:
```json
{"schema":"house/1","name":"Test","north_deg":0,
 "_assumptions":["north assumed up","storey height 3.0 m assumed"],
 "levels":[{"name":"Ground","elevation":0,"height":3.0,
   "walls":[{"id":"w1","p1":[0,0],"p2":[6,0]},{"id":"w2","p1":[6,0],"p2":[6,4]},
            {"id":"w3","p1":[6,4],"p2":[0,4]},{"id":"w4","p1":[0,4],"p2":[0,0]}],
   "openings":[{"wall":"w1","type":"door","at":1.5,"w":0.9},{"wall":"w3","type":"window","at":3,"w":1.5}],
   "rooms":[{"name":"Living","poly":[[0,0],[6,0],[6,4],[0,4]]}]}]}
```

### 5D. Gate (mandatory)
1. `validate.py <slug>` -> must say PASS (warnings are allowed but read them). It checks structure, ids, openings inside walls and
   non-overlapping, room polygons, **footprint vs printed dimensions (>3 % off = FAIL: wrong scale)**.
2. `plan_check.py <slug>` -> look at `plan_check_<level>.png` **next to the source drawing**: room positions, door/window gaps,
   stairs, voids, projections. Fix `house.json` and repeat until they agree. Validation alone does not catch a wrongly placed room.

## 6. LANE 2 - 3D building

`python3 pipeline/run.py run <slug>` (or `build_model.py <slug>`). Outputs `2_model/scene.json` and `2_model/model.html`.
- Review: start the preview server (`preview_start` with name `projects`, port 8765 from `.claude/launch.json`) and open
  `http://localhost:8765/<slug>/2_model/model.html`. **`file://` URLs do not open in the browser pane.**
  Take an iso and a top screenshot; compare with the plan_check images. Use the level/layer toggles and wall-opacity slider.
- Problems found here are lane 1 problems -> go back, fix `house.json`, rebuild. Do not edit `scene.json`.
- Stairs, furniture, curved walls and roofs are not modelled. Walls are boxes along centre lines.

### Hand-off to the roof app (the "combine later" contract)
`scene.json` contains a `building` block:
```json
"building": {"footprint": [x0, y0, x1, y1], "top_h": 6.3, "levels": 2, "north_deg": 0, "note": "walls only; ..."}
```
- Frame: **local metres, no lat/lng**. Plan x = 3D X (east if `north_deg` = 0 and plan-up is north), plan y = 3D Z (down the page),
  3D Y = height above the ground-floor slab. `footprint` is the **bounding box** of the full-height walls (fences/parapets with an
  `h` override are excluded); for the exact outline use the wall list in `house.json`.
- `top_h` = top of the highest wall (a storey-height assumption unless a section gave it). When Open Buildings/Solar heights
  disagree, **theirs win**; replace the level heights in `house.json` and rebuild.
- `north_deg` tells the roof app how the plan is rotated relative to true north; it is only as good as the assumption recorded in
  `_assumptions`. `groups[]` in `scene.json` are triangle soups (`positions` = x,y,z triples) tagged with `layer` and `level`.

## 7. Final report to the user (keep it short)
Source (link) and which unit; scale/dimension check result; the plan_check vs source comparison outcome; the assumptions list
(especially north, heights, which unit); link to `2_model/model.html`; anything that needs the user's confirmation.
If the pipeline could not find a usable plan, say so and ask for a PDF/URL. **Never invent a layout.**

## 8. Lane 3 (optional): panels and cables
Only when asked. Input `3_pv/pv_plan.json` (see `CONTRACTS.md`). Two modes:
- **With a roof** in `house.json` (gable/shed/flat): arrays are placed on roof faces (`"face":"S"`, `"rows":"max"` allowed).
- **Building only (default)**: give each array an explicit position from the roof app: `{"id":"A1","conn":[x,y,height],"panels":12,
  "panels_per_string":6}`; lane 3 then only plans cables (routes, lengths with slack, voltage drop, suggested size, CSV).
Indicative only: ampacity, derating, protection, fire setbacks, shading and local code are NOT checked; a licensed installer verifies.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Tavily HTTP 432 ... usage limit` | The key's credits/limit are exhausted. Not a code bug. Tell the user; fall back to browser search or a given URL |
| `TAVILY_API_KEY not set` | Create `<repo>/.env` from `.env.example` (never print the key) |
| `PDF saved but cannot be rendered` | `pip install --user pymupdf` (or `brew install poppler`), re-run `fetch.py` |
| `validate: width_m ... 12% off` | Scale wrong. Recalibrate from two printed dimensions; check feet vs mm; check you picked the right unit |
| `opening ... sticks out of the wall` | `at` is the centre, measured from `p1`; wall too short or `at`/`w` wrong |
| `lane 2 refuses to build` | Contract FAIL in `house.json`; fix in lane 1 |
| Viewer blank / `file://` fails in the pane | Use the preview server URL, not `file://` |
| `STALE` in `status` | Upstream file is newer; re-run `run.py run <slug>` |
| Image text unreadable | Source too small. Look for the brochure PDF; never guess dimensions |
| Mirrored plan pair, unsure which unit | Say which one you modelled; the other is a mirror, possibly an end lot with side land |

## 10. Changing the pipeline itself
- Run `python3 pipeline/tests/run_tests.py` before and after. Add a fixture under `pipeline/tests/fixtures/` and a test for every bug fixed.
- A contract change (`house.json`, `scene.json`, `pv_plan.json`) requires updating `CONTRACTS.md`, `common/contract.py` and the tests together.
- `pipeline/common/vendor/` is three.js r147 with checksums (`SHA256SUMS`); `doctor` verifies them. Do not upgrade casually (later
  releases dropped the classic scripts that make the viewer work offline).
- Keep secrets out of the repo: `.env` is gitignored; `FLOORPLAN_ROOT` relocates projects/`.env` (used by tests).

## 11. Repository map
```
AGENTS.md  CONTRACTS.md  CLAUDE.md  .env.example  .claude/launch.json  .claude/skills/<floorplan-to-3d|lane1-floorplan|lane2-model|lane3-pv>
pipeline/run.py                         orchestrator + doctor
pipeline/common/{project,contract,geo,net}.py  viewer_template.html  vendor/
pipeline/lane1_floorplan/{search,fetch,validate,plan_check}.py
pipeline/lane2_model/build_model.py
pipeline/lane3_pv/plan_pv.py            optional
pipeline/tests/                         run_tests.py, test_pipeline.py, fixtures/
projects/<slug>/{1_floorplan,2_model,3_pv}/
```
Downloaded sources (`projects/*/1_floorplan/source/`) and regenerable outputs are git-ignored; a fresh clone has `house.json` + `source.json`
(with the URLs) and rebuilds with `python3 pipeline/run.py run <slug>`. Re-download sources with `fetch.py` if you need to re-read a plan.

Worked examples already in `projects/`: `lumina-type-a` (building only, real brochure, the reference for the workflow),
`nada3a` (leaflet with section, legacy roof + PV), `demo` (synthetic), `nilam3-type-b` (sources fetched, not yet read).
