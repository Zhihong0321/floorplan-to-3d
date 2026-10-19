#!/usr/bin/env python3
"""LANE 1c - gate for house.json. Run before lane 2 (lane 2 also runs the same check and refuses on FAIL).

Usage: python3 pipeline/lane1_floorplan/validate.py <project>
Exit code 1 if any FAIL. Checks: structure, ids, openings inside walls / not overlapping, room polygons,
footprint vs the dimensions printed on the plan (source.json -> declared_dims), roof fields (roof is optional).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import project as P  # noqa: E402
from common.contract import check_house, format_findings  # noqa: E402


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    p = P.paths(sys.argv[1])
    if not os.path.isfile(p["house"]):
        raise SystemExit("FAIL missing %s" % p["house"])
    try:
        house = P.load_json(p["house"])
    except ValueError as e:
        raise SystemExit("FAIL house.json is not valid JSON: %s" % e)
    source = P.load_json(p["source_json"]) if os.path.isfile(p["source_json"]) else {}
    out = check_house(house, source)
    print(format_findings(out))
    sys.exit(1 if out["FAIL"] else 0)


if __name__ == "__main__":
    main()
