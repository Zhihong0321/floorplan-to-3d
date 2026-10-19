---
name: lane1-floorplan
description: Lane 1 of the floorplan->3D pipeline. Find a residential project's floorplan (Tavily search or a given URL/file), download it, READ it into projects/<slug>/1_floorplan/house.json (no roof), and verify the reading. Use for "find the floorplan of <project>", "read this floorplan", or when house.json is missing/wrong.
---

# Lane 1 - find + read the floorplan
Full procedure: `AGENTS.md` section 5. Contract: `CONTRACTS.md` ("Lane 1 -> Lane 2"). Output = `house.json` + `source.json`. Do not touch 2_model/ or 3_pv/.

- Find: `search.py "<project>" --project <slug>` (HTTP 432 = Tavily limit exhausted, not a bug -> browser search or ask for a URL).
- Fetch: `fetch.py <slug> <url> [--pages ..] [--declare width=..,depth=..]`.
- Read: view images; crop + enlarge with a pixel ruler; calibrate px/m from two printed dimensions; walls = centre lines; openings by `at` (centre);
  rooms as polygons; heights from a section or assumed; log EVERY guess in `_assumptions`; **leave `roof` out**.
- Gate: `validate.py <slug>` must PASS (footprint must match the printed size within 3 %), then compare `plan_check_*.png` with the source drawing.
