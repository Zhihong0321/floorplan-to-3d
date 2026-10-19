---
name: lane2-model
description: Lane 2 of the floorplan->3D pipeline. Convert projects/<slug>/1_floorplan/house.json into a 3D building (walls, floors, openings; no roof) and review it in the browser pane. Use for "build the 3D model", "regenerate the model", or after house.json changes.
---

# Lane 2 - floorplan -> 3D building
Full details: `AGENTS.md` section 6. Input `1_floorplan/house.json`; output `2_model/scene.json` + `model.html`. Never edit house.json here.

1. `python3 pipeline/run.py run <slug>` (gate + lane 2). Lane 2 refuses to build when house.json fails the contract.
2. Review: `preview_start` name `projects` (port 8765) -> `http://localhost:8765/<slug>/2_model/model.html` (`file://` does not open in the pane). Iso + Top screenshots vs `plan_check_*.png`.
3. Problems are lane 1 problems: report as "house.json: <what> because <evidence>", fix there, rebuild.
4. `scene.json.building` {footprint bbox, top_h, north_deg} is the hand-off to the external roof app (local metres, no lat/lng).
