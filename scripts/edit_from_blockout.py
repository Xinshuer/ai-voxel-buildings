"""Redraw ONE blockout with Qwen-Image-Edit-2511, for trying strengths and step counts before a batch.

Position, size and door openings are locked by the blockout; the edit model only swaps materials and detail.
The prompt comes from an entry of the prompts JSON (same format as batch_redraw.py, see README).

Each spec is "steps" or "steps@strength", e.g. 40@0.85. Strength below 1 keeps more of the blockout.
Steps 8 uses the 8-step Lightning LoRA (fast, but it tends to rewrite structure; for quick checks only).

Usage:
  python edit_from_blockout.py --prompts examples/redraw_prompts.json --id example_hall [--blockout PATH]
                               [--out work/tests] [--url http://127.0.0.1:8189] [--free] [40 40@0.85 ...]
Output: <out>/<id>-edit<steps>[-d<strength*100>].png
"""
import argparse, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import comfy

DEFAULT_OUT = Path("work") / "tests"
DEFAULT_SPECS = ["40"]


def main():
    ap = argparse.ArgumentParser(description="Redraw one blockout with Qwen-Image-Edit-2511.")
    ap.add_argument("--prompts", required=True, help="prompts JSON")
    ap.add_argument("--id", required=True, help="entry id in the prompts JSON")
    ap.add_argument("--blockout", help="blockout PNG (default: the entry's blockout, relative to the prompts file)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--url", default=comfy.URL)
    ap.add_argument("--seed", type=int, help="override the entry's seed")
    ap.add_argument("--free", action="store_true", help="unload models first (after running the t2i model)")
    ap.add_argument("specs", nargs="*", help="steps or steps@strength (default: 40 at the entry's strength)")
    a = ap.parse_args()
    comfy.URL = a.url.rstrip("/")

    import json
    prompts = Path(a.prompts)
    items = {i["id"]: i for i in json.loads(prompts.read_text("utf-8"))}
    if a.id not in items:
        sys.exit(f"{a.id!r} is not in {prompts}")
    item = items[a.id]
    src = Path(a.blockout) if a.blockout else prompts.parent / item["blockout"]
    if not src.exists():
        sys.exit(f"blockout missing: {src}")
    default_strength = float(item.get("strength", 1.0))
    specs = [(int(s.split("@")[0]), float(s.split("@")[1]) if "@" in s else default_strength) for s in (a.specs or DEFAULT_SPECS)]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    if not comfy.wait_up(600):
        sys.exit(f"ComfyUI at {comfy.URL} is not running")
    if a.free:
        comfy.free()  # never keep the ~20 GB t2i and edit models loaded together
    name = comfy.upload(str(src), "blockout_" + a.id + ".png")
    seed = a.seed if a.seed is not None else int(item.get("seed", 0))

    for steps, denoise in specs:
        t0 = time.time()
        lora = comfy.LORA_EDIT[8] if steps == 8 else None
        wf = comfy.edit(item["prompt"], [name], seed=seed, steps=steps, cfg=1.0 if lora else 4.0, lora=lora,
                        neg=item.get("neg", comfy.NEG_CN), denoise=denoise, prefix=f"tests/{a.id}-edit{steps}")
        image = comfy.wait(comfy.submit(wf), node=comfy.SAVE_NODE, timeout=2400)
        tag = f"edit{steps}" + (f"-d{int(round(denoise * 100))}" if denoise < 1 else "")
        target = out / f"{a.id}-{tag}.png"
        comfy.download(image, str(target))
        print(steps, "steps", round(time.time() - t0), "s", target, flush=True)
    print("done")


if __name__ == "__main__":
    main()
