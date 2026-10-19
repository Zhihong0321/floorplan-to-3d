"""Shared helpers: tiny vector maths + triangle-soup builder. No lane-specific logic here."""
import math

UP = (0.0, 1.0, 0.0)
DIRS = {"N": (0.0, -1.0), "S": (0.0, 1.0), "E": (1.0, 0.0), "W": (-1.0, 0.0)}  # plan (x, z)
BEARING = {"N": 0, "E": 90, "S": 180, "W": 270}


def vadd(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def vsub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def vmul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def vlen(a): return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
def vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


COLORS = {
    "floor": "#e8e2d4", "wall_ext": "#f2efe8", "wall_int": "#d9d4c8",
    "glass": "#7fb8d8", "door": "#8a5a3c", "roof": "#b4573f", "pv": "#1b2f5b",
}


class Geo:
    """Triangle soup grouped by (name, level); each group carries its viewer layer."""

    def __init__(self):
        self.groups = {}

    def g(self, name, layer, level=None, color=None, opacity=1.0):
        key = (name, level)
        if key not in self.groups:
            self.groups[key] = {"name": name, "layer": layer, "level": level,
                                "color": color or COLORS.get(name, "#cccccc"),
                                "opacity": opacity, "positions": []}
        return self.groups[key]["positions"]

    @staticmethod
    def tri(pos, a, b, c):
        for p in (a, b, c):
            pos.extend([round(p[0], 3), round(p[1], 3), round(p[2], 3)])

    def quad(self, pos, a, b, c, d):
        self.tri(pos, a, b, c)
        self.tri(pos, a, c, d)

    def box(self, pos, p1, e, n, s0, s1, side, y0, y1):
        """Box along a wall direction e (unit, plan) from s0..s1, +-side/2 thick, heights y0..y1."""
        def P(s, k, y):
            return (p1[0] + e[0] * s + n[0] * k, y, p1[1] + e[1] * s + n[1] * k)
        h = side / 2.0
        c = [P(s, k, y) for (s, k, y) in [(s0, -h, y0), (s1, -h, y0), (s1, h, y0), (s0, h, y0),
                                          (s0, -h, y1), (s1, -h, y1), (s1, h, y1), (s0, h, y1)]]
        for f in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.quad(pos, c[f[0]], c[f[1]], c[f[2]], c[f[3]])
