# Plan format (what `blockout.py plan` reads)

A plan is one JSON file describing building types. Each type has one or more tiers (size or wealth variants).
A tier is one compound on a whole-metre grid. Full example: [`examples/plan.json`](../examples/plan.json).

Units are metres. Origin is the tier's front-left corner; **x** runs right along the frontage, **y** runs back
into the depth, **z** is up. The camera looks from the front-left, so the `y = 0` face and the `x = 0` face are visible.
Keep every rectangle, wall and opening on whole metres (see the grid rule in `references/rules.md`).

```jsonc
{
  "types": [
    {
      "id": "hall_court",                 // --type
      "tiers": [
        {
          "tier": "standard",             // --tier
          "footprint": { "width": 20, "depth": 20 },
          "parts":    [ ... ],
          "units":    { ... },            // optional
          "doors":    [ ... ],
          "windows":  [ ... ],            // optional
          "walls":    [ ... ],            // optional
          "fixtures": [ ... ],            // optional
          "blockers": [ ... ]             // optional
        }
      ]
    }
  ]
}
```

## parts

| field | meaning |
|---|---|
| `id` | unique in the tier; `--part` picks one |
| `kind` | `building`, `shed`, `platform` or `yard` |
| `rect` | `[x0, y0, x1, y1]` footprint (not for `yard`) |
| `rects` | `yard` only: list of rectangles |
| `roof` | building: `"lean_to"` gives a single-slope roof; default is an overhanging gable |
| `storeys` | building: `2` adds a pent eave between floors and raises the eave to 6 m |
| `surface` | yard: `"garden"` paints the ground light (default: paved) |
| `style` | shed: `"pavilion"` draws four posts and a pyramid roof; otherwise an open lean-to shed |
| `blockout` | optional per-part drawing options, merged last (see below) |

### `blockout` options for a building (the `house()` function)

| option | default | meaning |
|---|---|---|
| `base` | 0.25 | plinth height; ≥ 0.5 adds front steps |
| `skirt` | 0.75 | brick wall skirt height |
| `eave` / `rise` | 3.0 / 2.6 | eave height; ridge rise above the eave |
| `over` | 0.5 | eave overhang |
| `bays` | 3 | bay count, or a list of bay widths that adds up to the frontage |
| `porch` | 0 | front porch depth; the front wall steps back and a column stands on every bay line |
| `facade` | none | one letter per bay: `G` lattice doors, `O` lattice doors with an open centre, `B`/`b` plank doors closed/removed, `K` open bay, `W` sill wall + window, `D` door (from `doors`, or centred), `w` small window, `-` blank wall |
| `roof` | `gable` | `gable`, `xieshan` (hip-and-gable) or `lean` |
| `storeys`, `eave1`, `upper` | 1, 3.25, `windows` | two storeys: pent-eave height; `gallery` sets the upper floor back 1 m behind a railing |
| `terrace`, `terrace_h`, `terrace_w`, `terrace_sides` | 0 | raised terrace in front, with steps |
| `chimney` | [] | list of `[x, y]` 1 × 1 m chimneys |
| `vents`, `ridge_orn`, `auto_windows`, `front_steps` | | small switches, see `HOUSE` in `blockout.py` |

For a `shed`: `z_hi`, `z_lo`, `post_step`, `back_wall`, `rows`. For a `platform`: `height`.

## units

`{ "<part id>": { "bays": [4, 4, 4] } }` — bay widths per building, used when they add up to the frontage.

## doors

| field | meaning |
|---|---|
| `id` | unique |
| `on` | `{ "part": id, "edge": "front" \| "back" \| "left" \| "right" }` for a building door, or `{ "wall": id }` for a wall gate |
| `kind` | `"gate"` for a gate in a wall (needs a matching wall gap) |
| `at` | `[x, y]` centre of the opening, in tier coordinates |
| `width`, `height` | metres (height defaults: 2.2 door, 2.6 gate) |

`--part` rotates the building so the door edge faces the camera (or use `--face`).

## windows

`{ "partId": id, "edge": "front" | "left", "at": [x, y], "width": 1.5, "sill": 0.9, "height": 1.0 }`

## walls

| field | meaning |
|---|---|
| `id` | referenced by gate doors |
| `thickness`, `height` | metres; keep the thickness a whole metre |
| `path` + `closed` | centre-line polyline; segments are thickened by `thickness` |
| `cells` | optional list of `[x0, y0, x1, y1]` whole-metre cells; used instead of `path` when present |
| `gaps` | `[{ "ref": door id or null, "from": [x, y], "to": [x, y] }]` openings along the wall line; always carved, a gate door is drawn back into its gap |

## fixtures and blockers

- `fixtures`: `{ "kind": "well", "rect": [...] }` draws a well with a stone curb (use at least 2 × 2 m).
- `blockers`: `{ "kind": "pond" | "rock", "rect": [...] }`.

Anything else in the file is ignored, so the plan can carry your own fields (names, owners, notes).
