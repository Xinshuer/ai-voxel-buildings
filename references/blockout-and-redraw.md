# Blockout and redraw: method and pitfalls / 白模与上色

## Why not text-to-image directly / 为什么不直接用文字出图

- Text-to-image draws doors, windows and steps too big and bays too few, so buildings look like huts.
  - Example: a 20 m, five-bay hall in the plan came out as three bays, 8 m wide.
  - Long buildings get squashed by a square canvas.
- A wide canvas fixes the bay count, but the view turns into a flat front elevation instead of the usual three-quarter top-down view.
- Describing a whole compound in words never puts things in the right place: the garden moves to the front, partition walls cut off side rooms, openings disappear.
- Drawing a small figure as a scale reference helps a little, but people must not appear in the final image.

A blockout fixes all three: proportion, layout and camera angle.

## Blockout (`scripts/blockout.py`)

- 0.25 m voxels, isometric: `u = (x − y)·cos30`, `v = (x + y)·sin30 + z`. Seen from the front-left above, so the front and left gable are visible.
- Drawn far to near by `i + j − k`. Each voxel paints top, front and left faces at brightness 1.0, 0.86, 0.72.
- Usage:
  - compound: `python scripts/blockout.py plan --plan PLAN --type TYPE --tier TIER --out OUT.png`
  - one building: add `--part ID` (it is rotated so its door faces the camera), plus `--eave --ridge --base --porch --bays --facade --geshan --terrace` or per-part `blockout` options in the plan.
  - structures with no plan entry (city wall, gates, pavilion, archway, bridges, pagoda): `python scripts/blockout.py shape NAME --out OUT.png`. Derive their sizes from real examples, round to whole metres, and list them for the owner to check.
- Colour legend: red = doors and columns, brown = windows, light wood = plain timber, grey-blue = brick and stone, dark blue-grey = roof tiles, white = plaster, near-black = open doorway / dark interior.
- The closer the blockout is to the final construction, the better the redraw:
  - build porches, columns, lattice doors and terraces into it;
  - a gatehouse that touches the compound wall needs clearly visible bays, or it gets redrawn as a one-bay gate tower.
- Make a contact sheet of all blockouts and check every size and bay count before moving on.

## Redraw with Qwen-Image-Edit-2511 / 上色

- 40 steps, cfg 4, euler / simple, shift 3.1, through a CFGNorm node. Image 1 goes through FluxKontextImageScale first. The starting latent is the blockout itself, so **denoise = redraw strength** (上色强度). No speed-up LoRA.
- Measured strengths:
  - **1.0** — best for a single building. Tiles, brackets, lattice doors, moss all appear; structure stays almost identical (occasionally a single-slope roof becomes two slopes).
  - **0.85** — best for a whole compound. Layout, well and openings survive; colours correct.
  - 0.8 — like 0.85, but added an extra pavilion.
  - 0.7 — still looks like the blockout; no detail.
  - 8-step Lightning LoRA — rewrites structure (gatehouse → hexagonal pavilion, well → pavilion). Avoid.
- Prompt structure (tested in Chinese; keep this order):
  1. Lock the blockout: 「把这张方块白模重画成精致的等轴测体素风格游戏建筑素材图。保持视角、构图，以及××的位置、大小、比例完全不变，不加不减，只换上真实的材质和细节」 ("redraw this block blockout as a detailed isometric voxel game asset; keep the view, composition and the position, size and proportion of X exactly; add nothing, remove nothing; only swap in real materials and detail").
  2. This building's construction and materials.
  3. The colour legend of the blockout.
  4. The shared palette.
  5. Common prohibitions: no people, no vegetation, no compound walls (single building), no loose props, no cutaways.
- Say out loud anything the model might misread: "the small grey cube in the narrow side yard is a well with a stone curb, not a pavilion"; "the building on the street is a three-bay gatehouse, do not turn it into a gate tower".
- Pin colours explicitly: "roof tiles are blue-grey (not green)"; for a city wall, "mid grey brick with a slight blue tint, not dark blue, not grey-green, clear mortar lines, rain streaks".
- Negative prompt: 「人物，行人，树木，竹子，花草，草丛，粉色墙面，粉红色，绿色瓦片，青绿色屋顶」 (people, trees, bamboo, flowers, grass, pink walls, pink, green tiles, teal roof) plus mistakes specific to the building, e.g. for a city wall 「深蓝色墙面，灰绿色墙面，光滑无砖缝的墙面」.
- Large areas of one material (a city wall) get little detail in a full view. Leave brick detail to the modelling step; if you need to fix the brick pattern, make a separate close-up.
- Prompts file format: see README ("Prompts file"). Example: `examples/redraw_prompts.json`.

## ComfyUI and the machine / ComfyUI 的坑

- Run a separate ComfyUI instance on its own port (default here 8189) so you never disturb one the owner already uses on 8188:
  `python main.py --listen 127.0.0.1 --port 8189 --disable-pinned-memory --database-url sqlite:///PATH/comfy8189.db --cache-none`
  - `--cache-none`: node results are not kept in RAM between jobs.
- **Do not add `--highvram`.** Qwen fills 16 GB of VRAM and runs more than ten times slower.
- The t2i model (2512) and the edit model (2511) are about 20 GB each. **Call `/free` before switching models** (`--free` in the scripts) so both are never loaded together.
- Timing on a 16 GB card: one 1328² image at 50 steps ≈ 3.6 min; an edit at 40 steps ≈ 3.5–7 min.
- Long batches must:
  - be interruptible and re-runnable, skipping finished images;
  - write a status file and a per-image log with time, RAM peak and VRAM peak;
  - be watched on a timer: re-run the script if it died, restart ComfyUI if it died, and check for **GPU driver timeouts** (on Windows: event `nvlddmkm` 153 / TDR).
- When done, stop only the process you started (keep its PID in a file).
