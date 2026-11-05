# Recommended rules (adapt per project) / 推荐规矩（可按项目改）

These came out of a real production run. They are defaults, not laws: at the start of a new project, ask the
owner which ones to keep, then follow the kept ones on every image and every model.

## Never in the concept image or the model / 画面和模型里都不出现

1. **No people (不画人).** Scale is locked by the blockout, not by figures. A scale figure is fine while testing a blockout, never in the final image.
2. **No vegetation (不画植被).** Trees, bamboo, grass, flowers and reeds are separate assets. Moss in the roof-tile channels counts as roof material and is drawn.
3. **No compound walls (院墙、围墙单独做).** Courtyard and boundary walls are separate assets. In a whole-compound image the walls only show the layout; model them separately.
4. **No loose props (散放道具单独做).** Water jars, pots, carts, haystacks, weapon racks, incense burners, stone lanterns are separate props. Things fixed to the building belong to it: counters, cabinets, stoves, troughs; a well counts as a fixed fixture.
5. **Exterior only.** No cutaways or section views.
6. **A bridge is only the bridge.** Water and banks are terrain.

## Construction / 构造

7. **Compounds keep their doors (整组建筑留门).** Decide every opening on purpose; never seal a building in with walls.
   - Openings come from the plan's `doors` and `walls[].gaps`.
   - After modelling, run a connectivity check: flood-fill from outside the main gate; the cell in front of every door must be reachable, and every courtyard has a way in and out.
8. **Whole-metre grid (整米格).** Assume the game manages footprint, navigation and destruction on a 1 m grid:
   - building outer boxes, module boxes, wall runs and openings all land on whole metres;
   - every wall is exactly one cell (1 m) thick;
   - detail lives in the sub-voxels inside a cell.
9. **No projecting balconies on two-storey buildings (不挑廊，用腰檐).** Use a short tiled pent eave between the floors; set the upper gallery back inside the footprint. Projecting balconies tend to clip through neighbours.
10. **Eaves may overhang the wall (屋檐外伸).** Walls sit exactly on the plan; the roof extends past them, and the module box may be one whole metre larger than the footprint. The overhang is only above eave height, so the cell below stays walkable.
11. City gates get a stair up to the wall walk, along the inner face of the wall, modelled with the gate.

## Colour / 颜色（示例色板）

One palette for the whole settlement. Example (late-imperial southern Chinese town):

- plaster walls slightly warm white; grey-blue brick with clear mortar lines; grey-blue stone plinths;
- blue-grey roof tiles, with clumps of bright green moss in the tile channels;
- vermilion lacquer on columns, doors, windows and gable boards; natural wood for brackets, beams and rafter ends; warm off-white window paper;
- plain houses use little vermilion — only the gable boards and door frames.
- **Never write 「粉」 in a Chinese prompt (提示词别用「粉」).** Qwen reads 「白灰粉墙」 (whitewashed wall) as pink. Put 粉色 / 粉红色 in the negative prompt instead.
- Example voxel palette entries (RGB, several shades per material):
  - tile: `[[84,104,128],[36,46,62],[116,136,160],[24,32,46],[140,158,180],[66,84,106]]`
  - moss: `[[112,176,58],[86,148,44],[134,196,72],[160,212,92]]`
- If the engine re-tints assets by theme, make sure these finished colours bypass that step.

## Working habits / 做事

- Every building is re-derived from its function, the plan, the setting and real historical architecture. Older assets are not references.
- Run one heavy job at a time: image generation, voxel build/render, and the game editor never run together. Check free memory first and ask the owner before starting.
- Ask one decision at a time, with a recommended option. Report failed checks and low scores as they are; never add parts just to raise a score.
