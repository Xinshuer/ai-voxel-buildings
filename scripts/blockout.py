"""Isometric voxel blockouts (0.25 m per voxel) for image-edit models.

The blockout locks every building's position, size, bay count and door openings.
An image-edit model (Qwen-Image-Edit-2511) then only swaps in materials and detail.

Usage
-----
  # a whole compound (all parts, walls, gates, yards) from a plan file
  python blockout.py plan --plan examples/plan.json --type hall_court --tier standard --out work/court.png

  # one building of that compound, rotated so its door faces the camera
  python blockout.py plan --plan examples/plan.json --type hall_court --tier standard --part hall --out work/hall.png

  # a built-in structure that has no plan entry (city wall, gate, pavilion, archway, bridges, pagoda)
  python blockout.py shape pagoda --out work/pagoda.png

Camera: isometric, from the front-left and above. The y=0 face (front) and x=0 face (left) are visible.
Plan format: see docs/plan-format.md.

Blockout colour legend (also used in the redraw prompt):
  red = doors and columns, brown = windows, light wood = plain timber, grey-blue = brick / stone,
  dark blue-grey = roof tiles, white = plastered wall, near-black = open doorway / dark interior.
"""
import argparse, json, math
import numpy as np
from PIL import Image, ImageDraw

S = 0.25            # voxel edge (m)
EAVE = 3.0          # default eave height (m)
RIDGE = 2.6         # default ridge rise above the eave (m)
BASE = 0.25         # default plinth height (m)
OVER = 0.5          # default eave overhang (m)
BACKGROUND = (238, 230, 214)

COL = {  # colour id: RGB
    1: (198, 205, 214),   # paved yard, wall-top walkway
    2: (236, 233, 226),   # white plastered wall
    3: (112, 128, 150),   # grey-blue brick (wall skirt, city brick, chimney)
    4: (90, 108, 132),    # roof tiles
    5: (176, 52, 40),     # red doors / door leaves
    6: (130, 145, 165),   # stone (plinth, steps, ashlar)
    7: (120, 86, 56),     # wooden lattice windows, transoms
    8: (210, 200, 175),   # garden ground
    9: (60, 72, 96),      # scale figure: clothes (test only, never in final images)
    10: (232, 196, 160),  # scale figure: face (test only)
    11: (150, 158, 168),  # well curb, stele, stone plaque, rockery, stone balustrade
    12: (176, 52, 40),    # red columns
    13: (52, 44, 40),     # open doorway / dark interior
    14: (156, 118, 78),   # natural wood (plank doors, railings, posts, plank walls, bridge deck)
    15: (120, 165, 180),  # pond
    16: (190, 160, 118),  # rammed earth
    17: (176, 140, 72),   # bronze (pagoda finial)
}


# ---------------- voxel grid ----------------
class Grid:
    """A voxel volume. Coordinates in metres: x to the right (frontage), y backwards (depth), z up."""

    def __init__(self, xmin, ymin, xmax, ymax, zmax):
        self.x0, self.y0 = xmin, ymin
        self.g = np.zeros((int(round((xmax - xmin) / S)), int(round((ymax - ymin) / S)), int(round(zmax / S)) + 1), np.uint8)

    def idx(self, x, y, z):
        return int(round((x - self.x0) / S)), int(round((y - self.y0) / S)), int(round(z / S))

    def box(self, x0, y0, z0, x1, y1, z1, c):
        """Fill an axis-aligned box with colour c (0 = carve out)."""
        i0, j0, k0 = self.idx(min(x0, x1), min(y0, y1), min(z0, z1))
        i1, j1, k1 = self.idx(max(x0, x1), max(y0, y1), max(z0, z1))
        n = self.g.shape
        i0, j0, k0 = max(i0, 0), max(j0, 0), max(k0, 0)
        i1, j1, k1 = min(i1, n[0]), min(j1, n[1]), min(k1, n[2])
        if i1 > i0 and j1 > j0 and k1 > k0:
            self.g[i0:i1, j0:j1, k0:k1] = c

    def each(self, x0, y0, x1, y1):
        """Yield the (x, y) centre of every voxel column in the rectangle."""
        for x in np.arange(x0 + S / 2, x1, S):
            for y in np.arange(y0 + S / 2, y1, S):
                yield float(x), float(y)


def draw(G, out, max_side=1500):
    """Isometric projection from the front-left and above.
    u = (x - y) * cos30, v = (x + y) * sin30 + z. Only exposed faces are drawn, far to near (sort by i + j - k).
    Each voxel paints top / front / left faces with brightness 1.0 / 0.86 / 0.72."""
    g = G.g
    filled = g > 0
    top = filled.copy(); top[:, :, :-1] &= ~filled[:, :, 1:]
    front = filled.copy(); front[:, 1:, :] &= ~filled[:, :-1, :]
    left = filled.copy(); left[1:, :, :] &= ~filled[:-1, :, :]
    cells = np.argwhere(top | front | left)
    if not len(cells):
        raise SystemExit("blockout is empty")
    c30, s30 = 0.866, 0.5
    u = (cells[:, 0] - cells[:, 1]) * c30 * S
    v = (cells[:, 0] + cells[:, 1]) * s30 * S + cells[:, 2] * S
    umin, umax = u.min() - 1.0, u.max() + 1.0
    vmin, vmax = v.min() - 1.0, v.max() + 1.0 + S
    k_px = min(max_side / (umax - umin + 3), max_side / (vmax - vmin + 4))
    Wpx, Hpx = int((umax - umin + 3) * k_px), int((vmax - vmin + 4) * k_px)
    img = Image.new("RGB", (Wpx, Hpx), BACKGROUND)
    dr = ImageDraw.Draw(img)

    def P(x, y, z):
        return ((x - y) * c30 - umin + 1.5) * k_px, Hpx - ((x + y) * s30 + z - vmin + 2) * k_px

    def shade(c, f):
        return tuple(int(t * f) for t in c)

    order = np.argsort(-(cells[:, 0] + cells[:, 1] - cells[:, 2]), kind="stable")
    for n in order:
        i, j, k = cells[n]
        c = COL[int(g[i, j, k])]
        x0, y0, z0, x1, y1, z1 = i * S, j * S, k * S, (i + 1) * S, (j + 1) * S, (k + 1) * S
        if top[i, j, k]:
            dr.polygon([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], fill=c, outline=shade(c, 0.92))
        if front[i, j, k]:
            dr.polygon([P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1)], fill=shade(c, 0.86), outline=shade(c, 0.8))
        if left[i, j, k]:
            dr.polygon([P(x0, y0, z0), P(x0, y1, z0), P(x0, y1, z1), P(x0, y0, z1)], fill=shade(c, 0.72), outline=shade(c, 0.66))
    img.save(out)
    print(out, img.size, int(filled.sum()), "voxels")
    return img.size


# ---------------- roofs ----------------
def gable_roof(G, x0, y0, x1, y1, z, rise, along_x=True, over=OVER, c=4):
    """Overhanging gable roof (xuanshan): steps in one voxel at a time, gable ends overhang."""
    span = (y1 - y0) if along_x else (x1 - x0)
    n = max(1, int(round(rise / S)))
    for k in range(n + 1):
        inset = (span / 2 + over) * k / n
        if along_x:
            G.box(x0 - over, y0 - over + inset, z + k * S, x1 + over, y1 + over - inset, z + (k + 1) * S, c)
        else:
            G.box(x0 - over + inset, y0 - over, z + k * S, x1 + over - inset, y1 + over, z + (k + 1) * S, c)


def hip_roof(G, x0, y0, x1, y1, z, rise, over=OVER, gable_cap=None, c=4):
    """Roof that steps in on all four sides. With gable_cap it becomes a hip-and-gable (xieshan) roof:
    the long side only steps in this far, then continues as two slopes. A square plan gives a pyramid roof."""
    w, d = x1 - x0 + 2 * over, y1 - y0 + 2 * over
    short = min(w, d) / 2
    n = max(1, int(round(rise / S)))
    for k in range(n + 1):
        ins = short * k / n
        ins_long = ins if gable_cap is None else min(ins, gable_cap)
        if w >= d:
            G.box(x0 - over + ins_long, y0 - over + ins, z + k * S, x1 + over - ins_long, y1 + over - ins, z + (k + 1) * S, c)
        else:
            G.box(x0 - over + ins, y0 - over + ins_long, z + k * S, x1 + over - ins, y1 + over - ins_long, z + (k + 1) * S, c)


def lean_roof(G, x0, y0, x1, y1, z_hi, z_lo, high="front", over=OVER, slab=0.5, solid_from=None, c=4):
    """Single-slope roof; the high side is `high` (front = y0, back = y1). slab = roof thickness.
    solid_from: fill walls from this height up to the roof underside (lean-to with walls)."""
    for x, y in G.each(x0 - over, y0 - over, x1 + over, y1 + over):
        t = (y - (y0 - over)) / ((y1 - y0) + 2 * over)
        if high == "back":
            t = 1 - t
        zt = round((z_hi + (z_lo - z_hi) * t) / S) * S
        G.box(x - S / 2, y - S / 2, zt - slab, x + S / 2, y + S / 2, zt, c)
        if solid_from is not None and x0 <= x <= x1 and y0 <= y <= y1:
            G.box(x - S / 2, y - S / 2, solid_from, x + S / 2, y + S / 2, zt - slab, 2)


# ---------------- one building ----------------
HOUSE = dict(base=0.25, skirt=0.75, eave=3.0, rise=2.6, over=OVER, storeys=1, eave1=3.25, bays=0, porch=0.0,
             facade=None, upper="windows", terrace=0.0, terrace_h=None, terrace_w=None, terrace_sides=False,
             roof="gable", lean_high="front", lean_low=None, chimney=(), vents=False, ridge_orn=False,
             front_steps=True, auto_windows=True, porch_col=12)
# facade: one letter per bay, left to right:
#   G red lattice doors + transom      O lattice doors, centre open (dark)   B plank doors closed   b plank doors removed (dark)
#   K whole bay open (dark)            W brick sill wall + lattice window     D the plan's door (centre door if none), small windows beside it
#   w one small window in the centre   - blank wall


def bay_lines(x0, x1, bays):
    if isinstance(bays, (list, tuple)) and bays:
        xs = [x0]
        for b in bays:
            xs.append(xs[-1] + b)
        if abs(xs[-1] - x1) > 0.01:
            raise ValueError(f"bays add up to {xs[-1] - x0}, frontage is {x1 - x0}")
        return xs
    n = bays or 3
    return [x0 + (x1 - x0) * b / n for b in range(n + 1)]


def house(G, x0, y0, x1, y1, o=None, doors=(), windows=()):
    """One building. doors: [{"edge": front/back/left/right, "at": [x, y], "width": w, "height": h}] in the same coordinates."""
    o = dict(HOUSE, **(o or {}))
    base, skirt, eave, rise, over = o["base"], o["skirt"], o["eave"], o["rise"], o["over"]
    two = o["storeys"] >= 2
    low_top = o["eave1"] if two else eave            # height available to the ground-floor facade
    edge = next((d["edge"] for d in doors if d["edge"] in ("front", "back")), None) or \
        next((d["edge"] for d in doors), "front")
    along_x = edge in ("front", "back") or o["facade"] is not None
    pad = 0.25
    G.box(x0 - pad, y0 - pad, 0, x1 + pad, y1 + pad, base, 6)                     # plinth

    G.box(x0, y0, base, x1, y1, base + skirt, 3)                                  # brick wall skirt
    if o["roof"] == "lean":
        z_lo = o["lean_low"] if o["lean_low"] else eave - 0.75
        lean_roof(G, x0, y0, x1, y1, eave, z_lo, high=o["lean_high"], over=over, solid_from=base + skirt)
    else:
        G.box(x0, y0, base + skirt, x1, y1, eave, 2)                              # plastered wall
        if o["roof"] == "xieshan":
            hip_roof(G, x0, y0, x1, y1, eave, rise, over=over, gable_cap=min(x1 - x0, y1 - y0) * 0.3)
        else:
            gable_roof(G, x0, y0, x1, y1, eave, rise, along_x=along_x, over=over)

    xs = bay_lines(x0, x1, o["bays"])
    porch = o["porch"]
    fy = y0 + porch                                                               # front wall plane
    if porch:  # front porch: front wall steps back, one column per bay line
        G.box(x0, y0, base, x1, fy, low_top, 0)
        for cx in xs:
            a = min(max(cx - 0.25, x0), x1 - 0.5)
            G.box(a, y0, base, a + 0.5, y0 + 0.5, low_top, o["porch_col"])
    if two:  # pent eave between the storeys: a short tiled eave, no projecting balcony
        z = o["eave1"]
        G.box(x0 - 0.5, y0 - 0.75, z, x1 + 0.5, y0, z + S, 4)
        G.box(x0 - 0.5, y0 - 0.5, z + S, x1 + 0.5, y0, z + 2 * S, 4)
        G.box(x0 - 0.5, y1, z, x1 + 0.5, y1 + 0.75, z + S, 4)
        G.box(x0 - 0.5, y1, z + S, x1 + 0.5, y1 + 0.5, z + 2 * S, 4)
        uy = y0
        if o["upper"] == "gallery":  # upper floor set back 1 m behind a railing (inside the footprint)
            G.box(x0, y0, z + 2 * S, x1, y0 + 1.0, eave, 0)
            G.box(x0, y0, z + 2 * S, x1, y0 + S, z + 2 * S + 1.0, 14)
            for cx in xs:
                a = min(max(cx - 0.25, x0), x1 - 0.5)
                G.box(a, y0, z + 2 * S, a + 0.5, y0 + 0.5, eave, 12)
            uy = y0 + 1.0
        for a, b in zip(xs, xs[1:]):  # a row of lattice windows per upper bay
            if b - a >= 2.0:
                G.box(a + 0.5, uy - S, z + 0.75, b - 0.5, uy + S, min(z + 2.0, eave - 0.5), 7)

    fd = [d for d in doors if d["edge"] == "front"]

    def fl(a, b, z0, z1, c):
        G.box(a, fy - S, z0, b, fy + S, z1, c)

    top = low_top - 0.25
    if o["facade"]:
        if len(o["facade"]) != len(xs) - 1:
            raise ValueError(f"facade {o['facade']} does not match {len(xs) - 1} bays")
        for code, a, b in zip(o["facade"], xs, xs[1:]):
            ia, ib = a + 0.25, b - 0.25
            hdoor = min(base + 2.75, top)
            if code in "GO":
                fl(ia, ib, base, hdoor, 5)
                if top - hdoor >= 0.5:
                    fl(ia, ib, hdoor, min(hdoor + 0.5, top), 7)
                if code == "O":
                    m = (ib - ia) / 4
                    fl(ia + m, ib - m, base, hdoor, 13)
            elif code in "Bb":
                fl(ia, ib, base, hdoor, 14)
                if code == "b":
                    fl(ia + 0.5, ib - 0.5, base, hdoor - 0.25, 13)
            elif code == "K":
                fl(ia, ib, base, hdoor, 13)
            elif code == "W":
                fl(ia, ib, base, base + 1.0, 3)
                fl(ia + 0.25, ib - 0.25, base + 1.0, min(base + 2.5, top), 7)
            elif code in "Dw":
                inbay = [d for d in fd if a - 0.01 <= d["at"][0] <= b + 0.01] if code == "D" else []
                if code == "D" and not inbay:
                    inbay = [{"at": [(a + b) / 2, y0], "width": 1.0, "height": 2.2}]
                for d in inbay:
                    fl(d["at"][0] - d["width"] / 2, d["at"][0] + d["width"] / 2, base, base + d.get("height", 2.2), 5)
                if inbay:
                    d0 = inbay[0]
                    free = [(a, d0["at"][0] - d0["width"] / 2), (d0["at"][0] + d0["width"] / 2, b)]
                else:
                    free = [(a, b)]
                if code == "D" and not o["auto_windows"]:
                    free = []
                for p, q in free:
                    if q - p >= 1.75:
                        cx = (p + q) / 2
                        fl(cx - 0.5, cx + 0.5, base + 1.0, base + 2.0, 7)
        doors = [d for d in doors if d["edge"] != "front"]
    # doors (painted on the wall plane) and, without a facade, a window on each side of the front door
    for d in doors:
        e, (ax, ay), dw, dh = d["edge"], d["at"], d["width"], d.get("height", 2.2)
        if e == "front":
            fl(ax - dw / 2, ax + dw / 2, base, base + dh, 5)
            if o["auto_windows"]:
                for wx in (x0 + (ax - x0) / 2, ax + (x1 - ax) / 2):
                    if abs(wx - ax) > dw / 2 + 1.2:
                        fl(wx - 0.75, wx + 0.75, base + 1.0, base + 2.0, 7)
        elif e == "back":
            G.box(ax - dw / 2, y1 - S, base, ax + dw / 2, y1 + S, base + dh, 5)
        elif e == "left":
            G.box(x0 - S, ay - dw / 2, base, x0 + S, ay + dw / 2, base + dh, 5)
            if o["auto_windows"]:
                for wy in (y0 + (ay - y0) / 2, ay + (y1 - ay) / 2):
                    if abs(wy - ay) > dw / 2 + 1.2:
                        G.box(x0 - S, wy - 0.75, base + 1.0, x0 + S, wy + 0.75, base + 2.0, 7)
        elif e == "right":
            G.box(x1 - S, ay - dw / 2, base, x1 + S, ay + dw / 2, base + dh, 5)
    for w in windows:
        e, (ax, ay), ww = w["edge"], w["at"], w["width"]
        z0 = base + w.get("sill", 0.9); z1 = z0 + w.get("height", 1.0)
        if e == "front":
            fl(ax - ww / 2, ax + ww / 2, z0, z1, 7)
        elif e == "left":
            G.box(x0 - S, ay - ww / 2, z0, x0 + S, ay + ww / 2, z1, 7)

    if o["terrace"]:  # raised terrace (yuetai) in front, with central steps
        t, th = o["terrace"], o["terrace_h"] or base
        tw = o["terrace_w"] or round((x1 - x0) * 0.4)
        cx = (x0 + x1) / 2
        G.box(cx - tw / 2, y0 - t, 0, cx + tw / 2, y0, th, 6)
        n = max(1, int(round(th / S)))
        for k in range(n - 1):
            G.box(cx - 1.5, y0 - t - (k + 1) * 0.5, 0, cx + 1.5, y0 - t - k * 0.5, th - (k + 1) * S, 6)
        if o["terrace_sides"]:
            for k in range(n - 1):
                G.box(cx - tw / 2 - (k + 1) * 0.5, y0 - t / 2 - 1.5, 0, cx - tw / 2 - k * 0.5, y0 - t / 2 + 1.5, th - (k + 1) * S, 6)
                G.box(cx + tw / 2 + k * 0.5, y0 - t / 2 - 1.5, 0, cx + tw / 2 + (k + 1) * 0.5, y0 - t / 2 + 1.5, th - (k + 1) * S, 6)
    elif o["front_steps"] and base >= 0.5:  # tall plinth: steps in front of the door
        n = int(round(base / S)) - 1
        cx = fd[0]["at"][0] if fd else (x0 + x1) / 2
        w = max(3.0, (fd[0]["width"] + 1.0) if fd else 3.0)
        for k in range(n):
            G.box(cx - w / 2, y0 - pad - (k + 1) * 0.5, 0, cx + w / 2, y0 - pad - k * 0.5, base - (k + 1) * S, 6)
    for (cx, cy) in o["chimney"]:  # brick chimney from the wall up past the ridge
        G.box(cx, cy, base, cx + 1.0, cy + 1.0, (eave if o["roof"] == "lean" else eave + rise) + 1.0, 3)
    if o["vents"]:  # small high vents in the gable walls
        cy = (y0 + y1) / 2
        G.box(x0 - S, cy - 0.75, eave - 1.5, x0 + S, cy + 0.75, eave - 0.75, 7)
        G.box(x1 - S, cy - 0.75, eave - 1.5, x1 + S, cy + 0.75, eave - 0.75, 7)
    if o["ridge_orn"]:  # ornament in the middle of the ridge
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        G.box(cx - 0.5, cy - 0.5, eave + rise, cx + 0.5, cy + 0.5, eave + rise + 1.0, 4)


def lean_shed(G, x0, y0, x1, y1, z_hi, z_lo, post_step=4.0, back_wall=None, rows=2, post_c=14, xs=None):
    """Open single-slope shed: high at the front, timber posts, a thin tiled roof slab.
    back_wall=(height or "roof", colour) closes the back row of posts."""
    lean_roof(G, x0, y0, x1, y1, z_hi, z_lo, high="front")
    if xs is None:
        n = max(1, int(math.ceil((x1 - x0) / post_step - 0.01)))
        xs = [x0 + (x1 - x0) * b / n for b in range(n + 1)]
    ys = [y0, y1 - 0.5] if rows == 2 else [y0, (y0 + y1) / 2 - 0.25, y1 - 0.5]
    for yy in ys:
        t = (yy + 0.25 - (y0 - OVER)) / ((y1 - y0) + 2 * OVER)
        zt = round((z_hi + (z_lo - z_hi) * t) / S) * S - 0.5
        for cx in xs:
            a = min(max(cx - 0.25, x0), x1 - 0.5)
            G.box(a, yy, 0, a + 0.5, yy + 0.5, zt, post_c)
    if back_wall:
        h, c = back_wall
        if h == "roof":  # close all the way up to the eave
            for x, y in G.each(x0, y1 - 0.5, x1, y1):
                t = (y - (y0 - OVER)) / ((y1 - y0) + 2 * OVER)
                zt = round((z_hi + (z_lo - z_hi) * t) / S) * S - 0.5
                G.box(x - S / 2, y - S / 2, 0, x + S / 2, y + S / 2, zt, c)
        else:
            G.box(x0, y1 - 0.5, 0, x1, y1, h, c)
    return xs


def pavilion_shed(G, x0, y0, x1, y1):
    """Small garden pavilion inside a compound: four red posts and a pyramid roof."""
    for cx, cy in ((x0 + .25, y0 + .25), (x1 - .5, y0 + .25), (x0 + .25, y1 - .5), (x1 - .5, y1 - .5)):
        G.box(cx, cy, BASE, cx + 0.25, cy + 0.25, 2.5, 12)
    G.box(x0 - .25, y0 - .25, 0, x1 + .25, y1 + .25, BASE, 6)
    hip_roof(G, x0, y0, x1, y1, 2.5, 1.75, over=0.5)


def scale_figure(G, px, py):
    """1.75 m figure for checking scale only. Never leave it in a blockout that goes to the edit model."""
    G.box(px, py, S, px + 0.5, py + 0.5, 1.5, 9)
    G.box(px + 0.25, py + 0.25, 1.5, px + 0.5, py + 0.5, 1.75, 10)


# ---------------- whole compound from a plan ----------------
def load(plan_path, type_id, tier_id):
    with open(plan_path, encoding="utf-8") as f:
        b = json.load(f)
    t = next((x for x in b["types"] if x["id"] == type_id), None)
    if t is None:
        raise SystemExit(f"type {type_id!r} not in {plan_path}")
    tier = next((x for x in t["tiers"] if x["tier"] == tier_id), None)
    if tier is None:
        raise SystemExit(f"tier {tier_id!r} not in type {type_id!r}")
    return tier


def wall_rects(w):
    """A plan wall: use `cells` (whole-metre cells, gaps already removed) when present, else thicken `path`."""
    if w.get("cells"):
        return [tuple(c) for c in w["cells"]]
    out, th = [], w["thickness"]
    pts = w["path"] + ([w["path"][0]] if w.get("closed") else [])
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        out.append((min(ax, bx) - th / 2, min(ay, by) - th / 2, max(ax, bx) + th / 2, max(ay, by) + th / 2))
    return out


def gap_rect(w, gap):
    """The box a wall gap cuts out: from..to along the wall line, full wall thickness across it."""
    (fx, fy), (tx, ty) = gap["from"], gap["to"]
    th = w["thickness"]
    if abs(fy - ty) < 0.01:
        return min(fx, tx), fy - th / 2, max(fx, tx), fy + th / 2
    return fx - th / 2, min(fy, ty), fx + th / 2, max(fy, ty)


def part_options(p, eave, rise, base):
    o = dict(eave=eave, rise=rise, base=base)
    if p.get("roof") == "lean_to":
        o.update(roof="lean", lean_high="back", lean_low=eave - 0.75)
    if p.get("storeys", 1) >= 2:
        o.update(storeys=2, eave1=3.25, eave=max(o["eave"], 6.0))
    o.update(p.get("blockout", {}))  # per-part overrides written in the plan
    return o


def render_tier(tier, out=None, people=(), part_opts=None, eave=EAVE, rise=RIDGE, base=BASE, ground=True):
    """A whole compound: ground, walls, wall gates, buildings, sheds, platforms, wells, ponds, rocks.
    part_opts={part id: house() options} overrides the plan."""
    W, D = tier["footprint"]["width"], tier["footprint"]["depth"]
    G = Grid(-6, -6, W + 6, D + 6, 22)
    part_opts = part_opts or {}
    if ground:
        G.box(0, 0, 0, W, D, S, 1)
    for p in tier["parts"]:
        if p["kind"] == "yard" and p.get("surface") == "garden":
            for r in p["rects"]:
                G.box(r[0], r[1], 0, r[2], r[3], S, 8)
    for b in tier.get("blockers", []):
        r = b.get("rect")
        if not r:
            continue
        if b["kind"] == "pond":
            G.box(r[0], r[1], 0, r[2], r[3], S, 15)
        elif b["kind"] == "rock":
            G.box(r[0] + .5, r[1] + .5, S, r[2] - .5, r[3] - .5, 1.5, 11)
    wall_by_id = {w["id"]: w for w in tier.get("walls", [])}
    for w in tier.get("walls", []):
        h = w["height"]
        for (a, b_, c, d) in wall_rects(w):
            G.box(a, b_, S, c, d, min(0.75, h - S), 3)
            G.box(a, b_, 0.75, c, d, h - S, 2)
            G.box(a, b_, h - S, c, d, h, 4)
        for gp in w.get("gaps", []):  # every gap stays open; gates are drawn back in below
            a, b_, c, d = gap_rect(w, gp)
            G.box(a, b_, S, c, d, h + 2 * S, 0)
    for d in tier.get("doors", []):  # wall gate: two leaves in the opening, wall above, a small tiled cap
        wid = d.get("on", {}).get("wall")
        if not wid or d.get("kind") != "gate":
            continue
        w = wall_by_id[wid]
        gap = next((gp for gp in w.get("gaps", []) if gp.get("ref") == d["id"]), None)
        if not gap:
            continue
        h, dh = w["height"], d.get("height", 2.6)
        a, b_, c, e = gap_rect(w, gap)
        if abs(gap["from"][1] - gap["to"][1]) < 0.01:
            G.box(a, (b_ + e) / 2 - S, 0, c, (b_ + e) / 2 + S, dh, 5)
        else:
            G.box((a + c) / 2 - S, b_, 0, (a + c) / 2 + S, e, dh, 5)
        G.box(a, b_, dh, c, e, h, 2)
        G.box(a - S, b_ - S, h, c + S, e + S, h + 2 * S, 4)
    doors = tier.get("doors", [])
    for p in tier["parts"]:
        kind = p["kind"]
        if kind == "building":
            x0, y0, x1, y1 = p["rect"]
            pd = [dict(edge=d["on"]["edge"], at=d["at"], width=d["width"], height=d.get("height", 2.2))
                  for d in doors if d.get("on", {}).get("part") == p["id"]]
            o = part_options(p, eave, rise, base)
            units = (tier.get("units") or {}).get(p["id"])
            if units and units.get("bays") and abs(sum(units["bays"]) - (x1 - x0)) < 0.01 and "bays" not in p.get("blockout", {}):
                o["bays"] = units["bays"]
            o.update(part_opts.get(p["id"], {}))
            wins = [w for w in tier.get("windows", []) if w.get("partId") == p["id"]]
            house(G, x0, y0, x1, y1, o, pd, wins)
        elif kind == "shed":
            x0, y0, x1, y1 = p["rect"]
            if p.get("style") == "pavilion":
                pavilion_shed(G, x0, y0, x1, y1)
            else:
                po = dict(z_hi=2.75, z_lo=2.25, post_step=4.0)
                po.update(p.get("blockout", {}))
                po.update(part_opts.get(p["id"], {}))
                lean_shed(G, x0, y0, x1, y1, **po)
        elif kind == "platform":  # open stone platform: steps in the middle of each side, low balustrade
            x0, y0, x1, y1 = p["rect"]
            h = dict(p.get("blockout", {}), **part_opts.get(p["id"], {})).get("height", 0.75)
            G.box(x0, y0, 0, x1, y1, h, 6)
            G.box(x0, y0, h, x1, y0 + S, h + 0.5, 11); G.box(x0, y1 - S, h, x1, y1, h + 0.5, 11)
            G.box(x0, y0, h, x0 + S, y1, h + 0.5, 11); G.box(x1 - S, y0, h, x1, y1, h + 0.5, 11)
            cx, cy, n = (x0 + x1) / 2, (y0 + y1) / 2, int(round(h / S))
            G.box(cx - 1.5, y0, h, cx + 1.5, y0 + S, h + 0.5, 0); G.box(cx - 1.5, y1 - S, h, cx + 1.5, y1, h + 0.5, 0)
            G.box(x0, cy - 1.5, h, x0 + S, cy + 1.5, h + 0.5, 0); G.box(x1 - S, cy - 1.5, h, x1, cy + 1.5, h + 0.5, 0)
            for k in range(n):
                z = h - (k + 1) * S
                G.box(cx - 1.5, y0 - (k + 1) * 0.5, 0, cx + 1.5, y0 - k * 0.5, z, 6)
                G.box(cx - 1.5, y1 + k * 0.5, 0, cx + 1.5, y1 + (k + 1) * 0.5, z, 6)
                G.box(x0 - (k + 1) * 0.5, cy - 1.5, 0, x0 - k * 0.5, cy + 1.5, z, 6)
                G.box(x1 + k * 0.5, cy - 1.5, 0, x1 + (k + 1) * 0.5, cy + 1.5, z, 6)
    for fx in tier.get("fixtures", []):
        if fx.get("kind") == "well":
            r = fx["rect"]
            G.box(r[0] + .25, r[1] + .25, S, r[2] - .25, r[3] - .25, 0.75, 11)
            G.box(r[0] + .75, r[1] + .75, 0.5, r[2] - .75, r[3] - .75, 0.75, 9)
    for (px, py) in people:
        scale_figure(G, px, py)
    if out:
        draw(G, out)
    return G


def single(tier, part_id, face=None):
    """Keep one building: move it to the origin and rotate so `face` (default: the door edge) faces the camera.
    Returns (width, depth, doors, windows, part, turns). Each turn brings the right edge to the front: x' = y, y' = W - x."""
    p = next((x for x in tier["parts"] if x["id"] == part_id), None)
    if p is None:
        raise SystemExit(f"part {part_id!r} not in this tier")
    x0, y0, x1, y1 = p["rect"]
    W, D = x1 - x0, y1 - y0
    doors = [dict(edge=d["on"]["edge"], at=[d["at"][0] - x0, d["at"][1] - y0], width=d["width"], height=d.get("height", 2.2))
             for d in tier.get("doors", []) if d.get("on", {}).get("part") == part_id]
    wins = [dict(edge=w["edge"], at=[w["at"][0] - x0, w["at"][1] - y0], width=w["width"], sill=w.get("sill", 0.9), height=w.get("height", 1.0))
            for w in tier.get("windows", []) if w.get("partId") == part_id]
    if face is None:
        face = "front" if (not doors or any(d["edge"] == "front" for d in doors)) else doors[0]["edge"]
    turns = {"front": 0, "right": 1, "back": 2, "left": 3}[face]
    rot = {"right": "front", "back": "right", "left": "back", "front": "left"}
    for _ in range(turns):
        for d in doors + wins:
            x, y = d["at"]
            d["at"] = [y, W - x]
            d["edge"] = rot[d["edge"]]
        W, D = D, W
    return W, D, doors, wins, p, turns


def render_single(tier, part_id, out=None, o=None, people=(), face=None):
    W, D, doors, wins, p, _ = single(tier, part_id, face)
    G = Grid(-6, -8, W + 6, D + 6, 30)
    oo = dict(o or {})
    if p.get("roof") == "lean_to" and "roof" not in oo:
        oo["roof"] = "lean"
    if p.get("storeys", 1) >= 2 and "storeys" not in oo:
        oo["storeys"] = 2
    house(G, 0, 0, W, D, oo, doors, wins)
    for (px, py) in people:
        scale_figure(G, px, py)
    if out:
        draw(G, out)
    return G, (W, D)


# ---------------- built-in structures without a plan entry ----------------
# All sizes are whole metres; adjust the numbers to your own setting.
def crenel_parapet(G, x0, x1, y0, y1, z, solid=1.0, merlon=0.75, period=2.0, tooth=1.5, c=3):
    """Crenellated parapet: a solid lower band, then merlons every 2 m (1.5 m merlon, 0.5 m crenel)."""
    G.box(x0, y0, z, x1, y1, z + solid, c)
    a = x0
    while a < x1 - 0.01:
        G.box(a, y0, z + solid, min(a + tooth, x1), y1, z + solid + merlon, c)
        a += period


def wall_segment(G, x0, x1, y0=0.0, thick=4.0, h=8.0, outer="front", inner_wall=True):
    """City wall segment: ashlar footing (0.75), brick body, walkway on top, outer parapet, inner waist-high wall (1 m)."""
    G.box(x0, y0, 0, x1, y0 + thick, 0.75, 6)
    G.box(x0, y0, 0.75, x1, y0 + thick, h, 3)
    G.box(x0, y0, h - S, x1, y0 + thick, h, 1)
    oy = (y0, y0 + 0.5) if outer == "front" else (y0 + thick - 0.5, y0 + thick)
    iy = (y0 + thick - 0.5, y0 + thick) if outer == "front" else (y0, y0 + 0.5)
    crenel_parapet(G, x0, x1, oy[0], oy[1], h)
    if inner_wall:
        G.box(x0, iy[0], h, x1, iy[1], h + 1.0, 3)


def city_wall(out=None, length=8.0):
    """A straight 8 m city wall (4 m thick, 8 m high), outer face towards the camera. No stairs, tower or gate."""
    G = Grid(-3, -3, length + 3, 7, 14)
    wall_segment(G, 0, length)
    if out:
        draw(G, out)
    return G


def arch_carve(G, xa, xb, ya, yb, spring, c=0):
    """Cut a semicircular arch along y: width xb - xa, springing height `spring`. c != 0 fills the same profile (door leaves)."""
    r, cx = (xb - xa) / 2, (xa + xb) / 2
    for x in np.arange(xa + S / 2, xb, S):
        dz = math.sqrt(max(r * r - (x - cx) ** 2, 0))
        G.box(x - S / 2, ya, 0 if c == 0 else S, x + S / 2, yb, round((spring + dz) / S) * S, c)


def gate_tower(G, double, z=8.0):
    """Gate tower on the platform, facing y=0. double=True: surrounding gallery, double-eave hip-and-gable roof;
    otherwise single-eave hip-and-gable with front and back porches."""
    G.box(3, 1, z, 17, 7, z + S, 6)                                                       # tower plinth
    if double:
        for cx in (3, 5, 8, 12, 15, 17):                                                  # gallery columns
            a = min(max(cx - 0.25, 3), 16.5)
            for cy in (1, 6.5):
                G.box(a, cy, z + S, a + 0.5, cy + 0.5, z + 3.0, 12)
        for cy in (2.5, 4.5):
            for cx in (3, 16.5):
                G.box(cx, cy, z + S, cx + 0.5, cy + 0.5, z + 3.0, 12)
        G.box(3.5, 1, z + S, 16.5, 1.25, z + 1.25, 14)                                    # gallery railing
        G.box(3, 1.5, z + S, 3.25, 6.5, z + 1.25, 14)
        G.box(5, 2, z + S, 15, 6, z + 0.75, 3)                                            # tower body
        G.box(5, 2, z + 0.75, 15, 6, z + 6.5, 2)
        for a, b, c in ((5.25, 7.75, 7), (8.25, 11.75, 5), (12.25, 14.75, 7)):            # ground-floor doors / windows
            G.box(a, 1.75, z + (0.5 if c == 5 else 1.0), b, 2.25, z + 2.75, c)
        hip_roof(G, 3, 1, 17, 7, z + 3.0, 1.25, over=1.0)                                  # lower eave
        G.box(5, 2, z + 3.0, 15, 6, z + 6.5, 2)
        for a, b in ((5.25, 7.75), (8.25, 11.75), (12.25, 14.75)):                        # upper windows
            G.box(a, 1.75, z + 4.75, b, 2.25, z + 6.0, 7)
        hip_roof(G, 5, 2, 15, 6, z + 6.5, 2.75, over=1.25, gable_cap=2.5)                 # upper eave
    else:
        for cx in (4, 8, 12, 16):                                                         # front and back porch columns
            a = min(max(cx - 0.25, 4), 15.5)
            for cy in (1, 6.5):
                G.box(a, cy, z + S, a + 0.5, cy + 0.5, z + 3.5, 12)
        G.box(4, 2, z + S, 16, 6, z + 0.75, 3)
        G.box(4, 2, z + 0.75, 16, 6, z + 3.5, 2)
        for a, b, c in ((4.5, 7.5, 7), (8.5, 11.5, 5), (12.5, 15.5, 7)):
            G.box(a, 1.75, z + (0.5 if c == 5 else 1.0), b, 2.25, z + (2.75 if c == 5 else 2.5), c)
        hip_roof(G, 4, 1, 16, 7, z + 3.5, 2.75, over=1.0, gable_cap=2.5)


def city_gate(out=None, double=False, inner=False):
    """City gate, 20 x 8 m brick platform 8 m high, 6 m semicircular arch in the middle (springing 2, crown 5),
    two leaves filling the arch exactly; city wall (4 thick, 8 high) attached on both sides.
    inner=False: seen from outside. inner=True: seen from inside, with a 3 m wide brick ramp-stair along the
    inner face of the left wall (32 steps, 0.25 rise, 0.5 tread, 16 m long) ending on a 3 m landing."""
    left = 20.0 if inner else 2.0
    G = Grid(-left - 3, -4, 25, 11, 21)
    G.box(0, 0, 0, 20, 8, 0.75, 6)                                                         # ashlar footing
    G.box(0, 0, 0.75, 20, 8, 8, 3)                                                         # brick platform
    G.box(0, 0, 8 - S, 20, 8, 8, 1)
    arch_carve(G, 7, 13, -1, 9, 2.0)                                                       # gate passage
    dy = (6.5, 7.0) if inner else (1.0, 1.5)                                               # leaves sit at the outer end
    arch_carve(G, 7, 13, dy[0], dy[1], 2.0, c=5)
    G.box(10 - 0.25, dy[0] - S, S, 10 + 0.25, dy[1], 5.0, 13)                              # seam between the leaves
    G.box(8.5, -S, 5.75, 11.5, 0.0, 6.75, 11)                                              # blank stone plaque
    if inner:  # platform top: crenels outward, low wall inward
        G.box(0, 0, 8, 20, 0.5, 9.0, 3)
        crenel_parapet(G, 0, 20, 7.5, 8, 8)
    else:
        crenel_parapet(G, 0, 20, 0, 0.5, 8)
        G.box(0, 7.5, 8, 20, 8, 9.0, 3)
    outer = "back" if inner else "front"
    wall_segment(G, -left, 0, y0=2.0, outer=outer)
    wall_segment(G, 20, 22, y0=2.0, outer=outer)
    if inner:
        ya, yb = -1.0, 2.0
        for k in range(32):
            xa = -19.0 + k * 0.5
            G.box(xa, ya, 0, xa + 0.5, yb, (k + 1) * S, 3)
            G.box(xa, ya, (k + 1) * S, xa + 0.5, ya + 0.5, (k + 1) * S + 1.0, 3)          # low outer guard wall
        G.box(-3, ya, 0, 0, yb, 8 - S, 3)                                                  # top landing
        G.box(-3, ya, 8 - S, 0, yb, 8, 1)
        G.box(-3, ya, 8, 0, ya + 0.5, 9.0, 3)
        G.box(-3, 2.0, 8, 0, 2.5, 9.0, 0)                                                  # open the inner wall where the landing joins
        G.box(-19, ya + 0.5, 8, -3, yb, 8.25, 0)
    gate_tower(G, double)
    if out:
        draw(G, out)
    return G


def pavilion(out=None):
    """Roadside pavilion: 6 x 6 stone plinth 0.5 high with one step; four columns 5 m apart; bench railings on three
    sides; pyramid roof, eave 3, top about 5.5; a stele in the middle."""
    G = Grid(-3, -4, 9, 9, 8)
    G.box(0, 0, 0, 6, 6, 0.5, 6)
    G.box(2, -0.5, 0, 4, 0, 0.25, 6)
    for cx, cy in ((0.5, 0.5), (5, 0.5), (0.5, 5), (5, 5)):
        G.box(cx, cy, 0.5, cx + 0.5, cy + 0.5, 3.0, 12)
    G.box(1, 5, 0.5, 5, 5.5, 1.0, 14); G.box(1, 5.25, 1.0, 5, 5.5, 1.5, 14)              # back bench railing
    G.box(0.5, 1, 0.5, 1.0, 5, 1.0, 14); G.box(0.5, 1, 1.0, 0.75, 5, 1.5, 14)           # left
    G.box(5, 1, 0.5, 5.5, 5, 1.0, 14); G.box(5.25, 1, 1.0, 5.5, 5, 1.5, 14)             # right
    G.box(2.5, 2.75, 0.5, 3.5, 3.25, 0.75, 6); G.box(2.5, 2.75, 0.75, 3.5, 3.25, 2.5, 11)  # stele
    hip_roof(G, 0.5, 0.5, 5.5, 5.5, 3.0, 2.0, over=0.75)
    G.box(2.75, 2.75, 5.0, 3.25, 3.25, 5.5, 6)                                             # finial
    if out:
        draw(G, out)
    return G


def archway(out=None):
    """Three-bay, four-post stone archway (paifang), 14 x 2: posts 1 x 1, centre opening 4 wide 5 high, side openings
    3 wide 3.5 high; a small carved roof over each bay (centre top about 9), a blank plaque, drum stones at the posts."""
    G = Grid(-3, -3, 17, 5, 11)
    for cx, h in ((0, 5.0), (4, 7.5), (9, 7.5), (13, 5.0)):
        G.box(cx, 0.5, 0, cx + 1, 1.5, h, 6)
        G.box(cx + 0.25, 0, 0, cx + 0.75, 0.5, 1.25, 11); G.box(cx + 0.25, 1.5, 0, cx + 0.75, 2, 1.25, 11)
    G.box(4, 0.5, 5.0, 10, 1.5, 6.0, 6)                                                    # centre lintel
    G.box(6, 0.25, 6.0, 8, 1.75, 7.0, 11)                                                  # plaque
    G.box(4, 0.5, 6.0, 6, 1.5, 7.0, 6); G.box(8, 0.5, 6.0, 10, 1.5, 7.0, 6)
    G.box(3.75, 0.5, 7.0, 10.25, 1.5, 7.5, 6)
    gable_roof(G, 3.75, 0.5, 10.25, 1.5, 7.5, 1.25, over=0.5)                              # centre roof
    for a, b in ((0, 5), (9, 14)):
        G.box(a, 0.5, 3.5, b, 1.5, 5.0, 6)
        gable_roof(G, a - (0.25 if a == 0 else 0), 0.5, b + (0.25 if b == 14 else 0), 1.5, 5.0, 1.0, over=0.5)
    if out:
        draw(G, out)
    return G


def stone_bridge(out=None):
    """Single-arch stone bridge 6 x 12: parapets 1 m wide and 1 m high on both sides, 4 m walkway; semicircular
    arch 4 m span, crown 2; 10 steps at each end (0.25 rise, 0.5 tread) up to a 2 m landing at 2.75; end stones.
    No water or banks (those are terrain)."""
    G = Grid(-3, -3, 9, 15, 6)

    def deck(y):
        if y > 7:
            return deck(12 - y)
        if y < 5:
            return 0.25 + 0.25 * (int(y / 0.5) + 1)
        return 2.75

    for x, y in G.each(0, 0, 6, 12):
        G.box(x - S / 2, y - S / 2, 0, x + S / 2, y + S / 2, deck(y), 6)
    for y in np.arange(4 + S / 2, 8, S):  # arch opening
        r = abs(y - 6)
        G.box(0, y - S / 2, 0, 6, y + S / 2, round(math.sqrt(max(4 - r * r, 0)) / S) * S, 0)
    for y in np.arange(3.5 + S / 2, 8.5, S):  # arch ring in a different stone colour
        r = abs(y - 6)
        zi = math.sqrt(max(4 - r * r, 0)); zo = math.sqrt(max(6.25 - r * r, 0))
        for xx in (0, 5.75):
            G.box(xx, y - S / 2, round(zi / S) * S, xx + S, y + S / 2, round(zo / S) * S, 3)
    for y in np.arange(S / 2, 12, S):  # parapet panels
        z = deck(y)
        G.box(0, y - S / 2, z, 1, y + S / 2, z + 1.0, 11)
        G.box(5, y - S / 2, z, 6, y + S / 2, z + 1.0, 11)
    for y in (0, 2, 4, 6, 8, 10, 11.5):  # posts
        z = deck(min(y + 0.25, 11.75))
        G.box(0, y, z + 1.0, 1, y + 0.5, z + 1.5, 6)
        G.box(5, y, z + 1.0, 6, y + 0.5, z + 1.5, 6)
    for y in (-1.0, 12.0):  # end stones
        G.box(-0.5, y, 0, 1.0, y + 1.0, 1.25, 6)
        G.box(5.0, y, 0, 6.5, y + 1.0, 1.25, 6)
    if out:
        draw(G, out)
    return G


def wood_bridge(out=None):
    """Timber beam bridge 6 x 12: 1 m stone abutments at both ends; three rows of four piles; three long beams;
    cross planks, deck at 2 m; 1 m timber railings. No water or banks."""
    G = Grid(-3, -3, 9, 15, 5)
    for y in (0, 11):
        G.box(0, y, 0, 6, y + 1, 1.75, 6)
    for y in (3, 6, 9):
        for x in (0.25, 2.0, 3.75, 5.25):
            G.box(x, y - 0.25, 0, x + 0.5, y + 0.25, 1.25, 14)
        G.box(0, y - 0.25, 1.25, 6, y + 0.25, 1.5, 14)
    for x in (0.5, 2.75, 5.0):
        G.box(x, 0, 1.5, x + 0.5, 12, 1.75, 14)
    for y in np.arange(0, 12, S):
        if int(round(y / S)) % 4 != 3:
            G.box(0, y, 1.75, 6, y + S, 2.0, 14)
    for x in (0, 5.75):
        for y in (0, 2, 4, 6, 8, 10, 11.75):
            G.box(x, y, 2.0, x + S, y + S, 3.0, 14)
        G.box(x, 0, 2.75, x + S, 12, 3.0, 14)
        G.box(x, 0, 2.25, x + S, 12, 2.5, 14)
    if out:
        draw(G, out)
    return G


def octagon(G, cx, cy, r, z0, z1, c):
    for x, y in G.each(cx - r, cy - r, cx + r, cy + r):
        dx, dy = abs(x - cx), abs(y - cy)
        if dx <= r and dy <= r and dx + dy <= r * 1.4142:
            G.box(x - S / 2, y - S / 2, z0, x + S / 2, y + S / 2, z1, c)


def pagoda(out=None):
    """Seven-storey octagonal brick pagoda: plinth 9 across, 1 high, steps on four sides; ground storey 7 across and 4 high,
    then 2.5 per storey plus a 0.5 eave, shrinking upwards; a small door on the front and left of each storey (real door
    and blank plaque on the ground floor); pyramid top with bronze finial, about 27 m in all."""
    G = Grid(-7, -7, 7, 7, 29)
    octagon(G, 0, 0, 4.5, 0, 1.0, 6)
    for k in range(3):  # steps
        h = 1.0 - (k + 1) * 0.25
        G.box(-1, -4.5 - (k + 1) * 0.5, 0, 1, -4.5 - k * 0.5, h, 6)
        G.box(-4.5 - (k + 1) * 0.5, -1, 0, -4.5 - k * 0.5, 1, h, 6)
        G.box(-1, 4.5 + k * 0.5, 0, 1, 4.5 + (k + 1) * 0.5, h, 6)
        G.box(4.5 + k * 0.5, -1, 0, 4.5 + (k + 1) * 0.5, 1, h, 6)
    z = 1.0
    for n, r in enumerate([3.5, 3.25, 3.0, 3.0, 2.75, 2.5, 2.25]):
        h = 4.0 if n == 0 else 2.5
        octagon(G, 0, 0, r, z, z + h, 3)
        dh, dw = (2.5, 0.75) if n == 0 else (1.5, 0.5)
        G.box(-dw, -r - S, z + 0.25, dw, -r + S, z + 0.25 + dh, 5 if n == 0 else 13)  # front door
        G.box(-r - S, -dw, z + 0.25, -r + S, dw, z + 0.25 + dh, 13)                     # left door
        if n == 0:
            G.box(-0.75, -r - S, z + 3.0, 0.75, -r + S, z + 3.5, 11)                    # blank plaque
        z += h
        octagon(G, 0, 0, r + 0.75, z, z + S, 4)                                         # storey eave
        octagon(G, 0, 0, r + 0.25, z + S, z + 2 * S, 4)
        z += 0.5
    for k, rr in enumerate((2.25, 1.75, 1.25, 0.75, 0.5)):                               # pyramid top
        octagon(G, 0, 0, rr, z + k * S, z + (k + 1) * S, 4)
    z += 1.25
    G.box(-0.25, -0.25, z, 0.25, 0.25, z + 2.5, 17)                                       # finial
    G.box(-0.5, -0.5, z + 0.5, 0.5, 0.5, z + 1.0, 17)
    G.box(-0.5, -0.5, z + 1.5, 0.5, 0.5, z + 2.0, 17)
    if out:
        draw(G, out)
    return G


SHAPES = {
    "wall": lambda o: city_wall(o),
    "gate": lambda o: city_gate(o, double=False),
    "gate-inner": lambda o: city_gate(o, double=False, inner=True),
    "gate-double": lambda o: city_gate(o, double=True),
    "gate-double-inner": lambda o: city_gate(o, double=True, inner=True),
    "pavilion": pavilion,
    "archway": archway,
    "stone-bridge": stone_bridge,
    "wood-bridge": wood_bridge,
    "pagoda": pagoda,
}


def main():
    ap = argparse.ArgumentParser(description="Isometric voxel blockouts for image-edit models.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plan", help="draw a compound (or one building of it) from a plan file")
    pp.add_argument("--plan", required=True, help="plan JSON, see docs/plan-format.md")
    pp.add_argument("--type", required=True, help="type id in the plan")
    pp.add_argument("--tier", required=True, help="tier id inside that type")
    pp.add_argument("--out", required=True, help="output PNG")
    pp.add_argument("--part", help="draw only this building, rotated so its door faces the camera")
    pp.add_argument("--face", choices=["front", "back", "left", "right"], help="with --part: which edge to turn to the front")
    pp.add_argument("--eave", type=float, default=EAVE, help="eave height (m)")
    pp.add_argument("--ridge", type=float, default=RIDGE, help="ridge rise above the eave (m)")
    pp.add_argument("--base", type=float, default=BASE, help="plinth height (m)")
    pp.add_argument("--porch", type=float, default=0, help="with --part: front porch depth (m)")
    pp.add_argument("--bays", default="", help="with --part: bay count (3) or bay widths (4,4,4)")
    pp.add_argument("--facade", help="with --part: one letter per bay, e.g. WGW (see house())")
    pp.add_argument("--geshan", action="store_true", help="with --part: lattice doors across every bay")
    pp.add_argument("--terrace", type=float, default=0, help="with --part: terrace depth in front (m)")
    pp.add_argument("--people", default="", help="x,y;x,y scale figures (testing only, never for final images)")
    sp = sub.add_parser("shape", help="draw a built-in structure that has no plan entry")
    sp.add_argument("name", choices=sorted(SHAPES))
    sp.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.cmd == "shape":
        SHAPES[a.name](a.out)
        return
    people = [tuple(map(float, xy.split(","))) for xy in a.people.split(";")] if a.people else []
    tier = load(a.plan, a.type, a.tier)
    if a.part:
        p = next((x for x in tier["parts"] if x["id"] == a.part), None)
        if p is None:
            raise SystemExit(f"part {a.part!r} not in this tier")
        o = part_options(p, a.eave, a.ridge, a.base)
        units = (tier.get("units") or {}).get(a.part)
        if units and units.get("bays") and "bays" not in o:
            o["bays"] = units["bays"]
        if a.porch:
            o["porch"] = a.porch
        if a.terrace:
            o["terrace"] = a.terrace
        if a.bays:
            o["bays"] = [float(b) for b in a.bays.split(",")] if "," in a.bays else int(a.bays)
        if a.facade:
            o["facade"] = a.facade
        elif a.geshan:
            n = len(o["bays"]) if isinstance(o.get("bays"), list) else (o.get("bays") or 3)
            o["facade"] = "G" * n
        render_single(tier, a.part, a.out, o, people, a.face)
    else:
        render_tier(tier, a.out, people, eave=a.eave, rise=a.ridge, base=a.base)


if __name__ == "__main__":
    main()
