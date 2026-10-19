---
name: floorplan-to-3d
description: Project name (or floorplan URL/file) -> find + read the floorplan -> 3D building model (walls, openings, rooms, levels; NO roof). Use for "get the floorplan of <residential project>", "make a 3D model of this house", or to resume a project in projects/.
---

# Project name -> floorplan -> 3D building

**Read `AGENTS.md` at the repo root first**: it is the full operating manual (commands, how to measure a plan, gate, troubleshooting).
Scope: building shell only. The roof/panels come from an external app and are combined later. Lane 3 (panels/cables) is optional.

1. `python3 pipeline/run.py doctor`, then `new "<project>"` (or `status <slug>` to resume).
2. **Lane 1** (`/lane1-floorplan`): search (Tavily) -> choose -> fetch -> read -> `validate` -> `plan_check`.
   **Checkpoint:** if several unit types/phases/lookalike project names exist, ask the user which before reading.
3. **Lane 2** (`/lane2-model`): `python3 pipeline/run.py run <slug>`; review `model.html` in the browser pane; send problems back to lane 1.
4. Report: source link, unit, dimension check, assumptions (north, heights), link to `projects/<slug>/2_model/model.html`.

Never invent a layout; if no usable plan is found, say so and ask for a PDF/URL. Never print the Tavily key.
