# From concept image to voxel model / 照概念图做体素模型

This repository does not ship a voxel modeller. Plug in **your own voxel parts pipeline** (接你自己的体素零件流水线):
a set of parametric parts (roof, tiles, walls, columns, doors, windows, plinths…) and an assembler that turns a
per-building assembly description into VOX files. Whatever you use, it must meet the requirements below.

## Requirements for the pipeline / 流水线要满足的要求

1. **Three tiers (三档).** Output t32, t16 and t8 — 32, 16 and 8 voxels per metre. t16 and t8 are derived from t32, never drawn separately.
2. **Modules ≤ 8 m (模块不超过 8 米).** Each module box is at most 8 m per axis (256 voxels at t32) and aligned to whole metres. Split long buildings by bay and deep ones into front and back blocks.
3. **Constructive texture (构造性纹理).** Colour per construction unit — one brick, one tile, one window-paper pane, one wood grain strip — picked by a fixed integer hash, so results are reproducible. Never scatter random per-voxel noise.
4. **Match the concept (对图).** Render the model from the concept image's camera and place them side by side (`scripts/compare_sheet.py`); also measure the colour difference per material region.
5. **Connectivity check (连通检查).** For compounds, prove that every door is reachable (details below).
6. Assembly is generated from a small script per building (sizes and part list live there); never hand-edit the generated assembly JSON.
7. Full rebuild is deterministic: re-running everything gives byte-identical files.

## Rules while modelling

- **The concept image is the main reference** for parts, proportions and colours. Hard sizes from the plan override the concept; the owner's rulings override both. Record anything you cannot honour as a plan override.
- Use the one shared palette (example values in `references/rules.md`).
- Backs you cannot see in the concept follow the front's construction; say so in the report.
- Loose props, vegetation and people never go into the building model. Compound walls are separate VOX files placed together at preview time.

## Checks

- A quality score is fine as a guide, but **never add parts just to raise a score**. Low scores usually come from "micro-structure": large blank walls, long flat facades, empty porches. If you score, also compute an exterior-only score with the unseen interior filled solid.
- **Concept comparison**: render at the concept's angle, place side by side, compare colours per material region.
- **Compound connectivity**:
  - whole-metre layer: building rects, wall cells, wells and ponds block; cells covered only by eaves are walkable; flood-fill from outside the main gate; the cell in front of every door must be reached;
  - voxel layer: a walker about 0.6 m wide and 1.9 m tall, max step 0.25 m;
  - clear space in front of doors, and no overlap between assets.
- Run the pipeline's full test suite; a full `--check` rebuild must match byte for byte.

## Preview in the game engine / 游戏引擎里预览

Write an **editor-only** preview script (do not commit it) that:

- opens an empty scene with a warm directional light and a ground plane;
- reads a placement list (`file`, `position`, `yaw`) and loads each VOX at the chosen tier — rotate around the vertical axis first, then translate;
- uses an orthographic camera at about Euler(38, 45, 0) and saves an overview and close-ups as PNGs.

Launch the editor in batch mode with that method (e.g. Unity's `-projectPath … -executeMethod Class.Method -logFile …`), then leave it open for the owner to orbit.

- If your importer caches meshes, close the editor and delete the cache entries for a model after changing its VOX, or you will see stale or mismatched meshes. Give preview models names that cannot collide with the game's own assets.
- Opening the editor is heavy: check memory and get the owner's OK first.
- Afterwards delete the temporary script, its metadata file and the mesh cache entries.
