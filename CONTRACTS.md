# Pipeline contracts

Three lanes (lane 3 is optional). Each reads files from the previous lane and writes its own folder. **The roof is out of scope:
the building is modelled walls-only; the roof profile and panel placement come from an external app (Google Open Buildings / Solar API) and are combined later.** **No lane imports another lane's code,
and no lane edits another lane's files.** If lane 2 finds a bad house.json, it reports back to lane 1 (and vice versa).

```
project name / URL / image
        |
   LANE 1  floorplan      search -> fetch -> read (Claude vision) -> validate -> plan_check
        |  1_floorplan/house.json  (+ source.json provenance)
   LANE 2  model          house.json -> 3D scene
        |  2_model/scene.json  (+ model.html)
   LANE 3  pv + cables    (OPTIONAL) scene.json + pv_plan.json -> cable schedule, final viewer
           3_pv/pv.json, cable_schedule.csv, viewer.html
```

```
projects/<slug>/
  1_floorplan/  source/  source.json  candidates.json  house.json  plan_check_<level>.png
  2_model/      scene.json  model.html
  3_pv/         pv_plan.json  pv.json  cable_schedule.csv  viewer.html
```
Code: `pipeline/common` (shared maths + viewer), `pipeline/lane1_floorplan`, `pipeline/lane2_model`, `pipeline/lane3_pv`,
`pipeline/run.py` (chains them). Skills: `.claude/skills/{solar-from-project,lane1-floorplan,lane2-model,lane3-pv}`.

---------------------------------------------------------------------------------------------------

## Lane 1 -> Lane 2 : `1_floorplan/house.json`  (schema `house/1`)
Geometry only. Metres. Plan axes **x right, y down** (as drawn). Keys starting with `_` are notes and ignored.

```jsonc
{
  "schema": "house/1",
  "name": "My house",
  "_source": "which file/page, what scale", "_assumptions": ["north assumed up", "wall thickness 150 mm"],
  "north_deg": 0,             // clockwise angle of the north arrow from plan-up (0 = plan-up is north)
  "levels": [                 // lowest first
    { "name": "Ground", "elevation": 0.0, "height": 3.0,     // height = floor to floor
      "walls": [ {"id": "g1", "p1": [0,0], "p2": [6.7,0],
                  "t": 0.15,        // thickness (default .15 ext / .10 int)
                  "ext": true,      // default: auto (both ends on the outer bounding box)
                  "h": 1.1} ],      // optional height override (parapet / low wall)
      "openings": [ {"wall": "g1", "type": "door|window|opening", "at": 1.3,   // at = distance p1 -> opening CENTRE
                     "w": 1.0, "sill": 0.9, "h": 1.2} ],   // defaults: door .9/0/2.1, window 1.2/.9/1.2, opening = gap
      "rooms": [ {"name": "Living", "poly": [[0,0],[5,0],[5,4],[0,4]]} ] } ],
  "roof": { "type": "none|gable|shed|flat",   // OPTIONAL and normally ABSENT (= none). Only legacy projects use gable/shed/flat
             "ridge_axis": "x|y", "falls_to": "N|S|E|W", "pitch_deg": 25,
            "overhang": 0.6, "overhang_gable": 0.0, "footprint": [x0,y0,x1,y1] }   // footprint optional
}
```
`1_floorplan/source.json`: `{"declared_dims": {"width_m":..,"depth_m":..}, "sources":[{url, kind, files, note, fetched_at}]}`.
`declared_dims` = the overall size PRINTED on the plan; `validate.py` fails the lane if the walls disagree by >3 %.

**Lane 1 gate (must PASS before lane 2):** `validate.py` (structure, openings inside walls, dims vs plan) and a visual
comparison of `plan_check_*.png` against the source drawing.

## Lane 2 -> Lane 3 : `2_model/scene.json`  (schema `scene/1`)
Meshes (`groups`: triangle soup with layer/level/colour) for the viewer, plus what lane 3 needs: `levels`
(name, elevation, height), `eave_h`, `footprint`, `roof` {type, pitch_deg} (`type: none` and `faces: []` when the roof is left out), and `faces[]` = roof planes
`{name N|S|E|W, O, u, v, n, lu, lv, pitch, bearing, azimuth_true}` (origin + unit axes in 3D, size in metres).
3D axes: X = plan x, Y = height, Z = plan y. Lane 2 knows nothing about PV.

`building` (the hand-off block for the external roof app):
`{"footprint": [x0,y0,x1,y1], "top_h": 6.3, "levels": 2, "north_deg": 0}` - local metres, no lat/lng; `footprint` is the bounding box of the
full-height walls (walls with an `h` override are fences/parapets and excluded); `top_h` = top of the highest wall.
Empty mesh groups are never emitted.

## Lane 3 input : `3_pv/pv_plan.json`  (schema `pv_plan/1`)
```jsonc
{ "schema": "pv_plan/1",
  "panel": {"w": 1.134, "h": 2.278, "watt": 550, "vmp": 41.7, "imp": 13.2}, "gap": 0.02, "setback": 0.4,
  "arrays": [ {"id": "A1", "conn": [3.6, 9.0, 6.4], "panels": 12, "panels_per_string": 6},   // array placed by the roof app: only its connection point [x,y,height] is needed
               {"id": "A2", "face": "S", "rows": 3, "cols": 4,     // legacy: placed on a lane-2 roof face; "max" fills the face
               "orientation": "portrait|landscape", "panels_per_string": 6,
               "align": "center|left|right", "u_offset": null, "v_offset": null, "tilt": 10} ],   // tilt: flat roofs only
  "equipment": [ {"id": "inverter", "kind": "inverter|db|meter|battery|generic", "label": "Inverter 5 kW",
                  "pos": [6.5, 16], "level": 0, "height": 1.5, "kw": 5, "phases": 1, "ac_v": 230} ],
  "cables": [ {"id": "DC1", "type": "dc|ac|earth|comms", "from": "A1", "to": "inverter", "size_mm2": 4,
               "strings": 1, "conductors": 4, "via": [[6.5, 13.9]], "run_height": 7.9,
               "slack_pct": 10, "termination_m": 1.0, "max_drop_pct": 1.5} ] }
```
`face` = roof side by PLAN direction (N = plan-up). `via`: `[x,y]` waypoint at run height, `[x,y,height]` exact point.
Default run height = eave + 0.4 m (pitched) / eave - 0.25 m (flat); use ~equipment height for short local runs.

## Lane 3 output
`pv.json` (arrays, **capacity** = max panels per roof face portrait/landscape, cables, warnings), `cable_schedule.csv`,
`viewer.html` (scene + panels + cables; layers, X-ray, GLB export).

Cable maths: path = start -> up/down to run height -> via points -> end -> up/down (axis-aligned);
`cut = route x (1 + slack%) + termination`; `total conductor m = cut x conductors`;
DC I = Imp x strings, V = panels/string x Vmp; AC I = kW / (V x sqrt3 if 3-phase);
drop = I x 0.0225 x (2 | sqrt3) x L / A (90 C copper); limits 1.5 % DC / 3 % AC; `suggested_mm2` = smallest size meeting it.
**Not checked:** ampacity, derating, protection, fire setbacks, shading, local code. A licensed installer verifies on site.

## Secrets
`TAVILY_API_KEY` lives in `<repo>/.env` (gitignored; see `.env.example`) or the shell environment. Only
`lane1_floorplan/search.py` reads it. It is never printed, logged or written to a project folder.
