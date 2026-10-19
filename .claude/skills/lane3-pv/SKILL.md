---
name: lane3-pv
description: OPTIONAL lane 3 of the pipeline. Cable planning (lengths, slack, voltage drop, suggested size, CSV) for home solar PV, from array positions supplied by the external roof app (or arrays placed on a legacy lane-2 roof). Only use when the user explicitly asks for cables/panels.
---

# Lane 3 - cables (+ legacy panel placement) - optional
Out of scope by default: panel placement belongs to the external roof app. Details: `AGENTS.md` section 8, formats in `CONTRACTS.md`.
Input `2_model/scene.json` + `3_pv/pv_plan.json`; output `3_pv/pv.json`, `cable_schedule.csv`, `viewer.html`. Never read/edit house.json.

- No roof in the scene: give each array `{"id","conn":[x,y,height],"panels","panels_per_string"}`; cables are routed from there.
- Ask once for panel (W/Vmp/Imp), inverter (kW, 1/3-phase), inverter + DB positions; otherwise use placeholders and list them in `_assumptions`.
- `python3 pipeline/run.py run <slug> --with-pv`, then review `3_pv/viewer.html`.
- Always state: indicative only; ampacity, derating, protection, fire setbacks, shading and local code are NOT checked.
