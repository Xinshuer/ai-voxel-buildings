---
name: ai-voxel-buildings
description: Use when making buildings for a voxel game from planned sizes — drawing an isometric voxel blockout from a plan, turning it into a concept image with Qwen-Image-Edit-2511 in ComfyUI, running owner review rounds, then building tiered VOX models from the approved concept and previewing them in a game engine.
---

# Voxel buildings: plan → blockout → concept → review → model
# 体素建筑：规划 → 白模 → 概念图 → 审核 → 模型

A pipeline for buildings in a voxel game. It was worked out on a real town-rebuild project. The first attempt
used plain text-to-image and failed in three ways:

- **Wrong proportions** — doors and steps too big, too few bays; buildings looked like huts.
- **Wrong layout** — where each building, wall and opening sits in a compound was left to the model's imagination.
- **Wrong angle** — switching to a wide canvas turned the view into a flat front elevation.

Drawing a **blockout from the planned sizes first (先做白模)** and letting an image-edit model only put materials on
it locked proportion, layout and angle together.

**For whoever runs this (any AI agent or a person):** nothing here depends on a particular AI product. The steps
below are commands to run and criteria to judge by. You need:

- Python 3 with `numpy` and `Pillow`;
- a local ComfyUI with Qwen-Image-Edit-2511 and Qwen-Image-2512 (both Apache-2.0);
- your own voxel parts pipeline (requirements in `references/modeling.md`);
- optionally a game engine editor for the final preview.

## Read first

1. `references/rules.md` — recommended rules (推荐规矩, adapt per project): palette, whole-metre grid, no people, no vegetation, compounds keep their doors, and more. Ask the owner which to keep.
2. `references/blockout-and-redraw.md` — steps 1–3 in detail, with measured settings and ComfyUI pitfalls.
3. `references/modeling.md` — steps 5–6: what your voxel pipeline must do, checks, engine preview.
4. `references/review.md` — how to run review rounds and keep the log.
5. `docs/plan-format.md` — the plan JSON that `blockout.py` reads.

## Steps

### 1. Fix the sizes — the plan comes first (定尺寸，规划优先)
- Buildings in the plan: footprint, bays, door positions, walls and openings exactly as planned.
- Things not in the plan (city walls, gates, bridges, towers, archways): derive from real historical forms, **round to whole metres**, write the numbers in a list and have the owner check them.
- Sizes are read-only. Changing the plan is a separate task; ask the owner first.

### 2. Draw the blockout (做白模)
- `python scripts/blockout.py plan --plan PLAN --type T --tier R --out OUT.png [--part ID]` — 0.25 m voxels, isometric, seen from the front-left above. `shape NAME` draws structures with no plan entry.
- Colour legend: red = doors and columns; brown = windows; light wood = timber; grey-blue = brick/stone; dark blue-grey = tiles; white = plaster; near-black = open doorway.
- **No people in the blockout** (scale figures only while testing).
- Put all blockouts on one contact sheet and check every size and bay count before going on.

### 3. Put materials on it (上材质出概念图)
- One image: `scripts/edit_from_blockout.py`; a batch: `scripts/batch_redraw.py`. Qwen-Image-Edit-2511, **40 steps, cfg 4, no speed-up LoRA**.
- Redraw strength (上色强度 = denoise):
  - **1.0 for a single building** — best detail, structure barely changes;
  - **0.85 for a whole compound** — keeps the layout;
  - 0.7 is too close to the blockout (no detail); the 8-step LoRA rewrites structure.
- Prompt in this order:
  1. "keep the blockout's position, size and proportion; only swap materials and detail" (保持白模的位置、大小、比例不变，只换材质和细节);
  2. this building's construction and materials;
  3. the blockout colour legend;
  4. the shared palette;
  5. common prohibitions: no people, no vegetation, no compound walls, no loose props, no cutaways.
- Negative prompt: people, trees and plants, compound walls, **pink (粉色)**, plus this building's likely mistakes.
- Prompts live in a JSON file; format in README, example in `examples/redraw_prompts.json`.

### 4. Owner review (审核)
- `scripts/build_review.py` makes a review page. The owner marks each image; log it as in `references/review.md`.
- Change the prompt or blockout and redraw only the failed ones.
- When feedback applies generally ("walls should be separate assets"), promote it to a general rule in the log and in `references/rules.md`, and apply it to every image from then on.

### 5. Build the voxel model from the concept (照概念图做体素模型)
- Hand the approved concept to **your voxel parts pipeline**. It must produce three tiers (t32 / t16 / t8 voxels per metre), modules ≤ 8 m per axis on whole metres, constructive texture from a fixed hash, a side-by-side comparison with the concept, and a connectivity check for compounds. See `references/modeling.md`.
- Use the shared palette.

### 6. Preview in the game engine (游戏引擎里预览)
- An editor-only script loads the placement list, places the VOX files in an empty scene and saves an overview and close-ups.
- Delete the temporary script and mesh caches afterwards.
- Opening the editor is heavy: check memory and get the owner's OK first.

## Reporting

After each step tell the owner:
- what was done and where the files are;
- how it compares with the reference — what matches, what doesn't, and why;
- which decisions you made yourself and which the owner must make.

Ask one decision at a time, with a recommended option (一次只问一个问题，带推荐项). Report failed checks and scores honestly;
never change a model just to raise a score.

## Scripts

| script | what it does |
|---|---|
| `blockout.py` | isometric voxel blockout from a plan, or a built-in structure |
| `comfy.py` | small ComfyUI client: upload, submit, wait, download, free; Qwen t2i and edit workflows |
| `edit_from_blockout.py` | redraw one blockout at several step counts / strengths |
| `batch_redraw.py` | resumable batch redraw from a prompts JSON, with status file and per-image log |
| `compare_sheet.py` | side-by-side comparison sheet with labels |
| `build_review.py` | local HTML review page with Pass / Redo and a copyable summary |

Configuration is by command-line options and constants at the top of each script: ComfyUI address
(default `http://127.0.0.1:8189`, or env `COMFY_URL`), model file names in `comfy.py`, output folder (default `work/`).
