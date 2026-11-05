"""Batch redraw: for every entry of a prompts JSON, put materials on its blockout with Qwen-Image-Edit-2511
(40 steps, cfg 4, no speed-up LoRA, denoise = the entry's strength) and save to <out>/<category>/<id>.png.

Interruptible and re-runnable: entries whose output already exists are skipped. To redraw one, move its old
image away (don't delete it) and run again. Every attempt is appended to <out>/redraw-log.jsonl (seconds,
RAM peak %, VRAM peak MB); overall state goes to <out>/redraw-status.json so a watcher can check progress.

The script does not start ComfyUI. It waits up to 10 minutes for it, then exits with a reason.
Start ComfyUI yourself, for example:
  python main.py --listen 127.0.0.1 --port 8189 --disable-pinned-memory --cache-none
Do not add --highvram. If the t2i model ran last on that server, pass --free once so only one model is loaded.

Prompts file format: see README ("Prompts file"). Blockout paths are relative to --root
(default: the prompts file's folder).

Usage:
  python batch_redraw.py --prompts examples/redraw_prompts.json [--out work/concepts] [--root DIR]
                         [--url http://127.0.0.1:8189] [--steps 40] [--free] [id ...]
"""
import argparse, json, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import comfy

DEFAULT_OUT = Path("work") / "concepts"
DEFAULT_STEPS = 40
DEFAULT_CFG = 4.0
CONNECT_TIMEOUT = 600   # seconds to wait for ComfyUI
JOB_TIMEOUT = 2400      # seconds per image


def mem_percent():
    """Whole-machine RAM used (%). Uses psutil when installed, else the Windows API, else None."""
    try:
        import psutil
        return psutil.virtual_memory().percent
    except ImportError:
        pass
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(100.0 * (m.ullTotalPhys - m.ullAvailPhys) / m.ullTotalPhys, 1)
    except Exception:
        return None


def vram_used():
    """Whole-card VRAM used and total (MB) from nvidia-smi."""
    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True).stdout.strip().splitlines()[0]
    used, total = (int(x) for x in o.split(","))
    return used, total


class Peaks:
    """While one image renders, sample RAM % and VRAM every 0.5 s in the background and keep the peaks."""

    def __init__(self):
        self.mem = 0.0; self.vram = 0; self.vram_total = 0; self._stop = False
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop:
            try:
                m = mem_percent()
                if m is not None:
                    self.mem = max(self.mem, m)
                u, tot = vram_used(); self.vram = max(self.vram, u); self.vram_total = tot
            except Exception:
                pass
            time.sleep(0.5)

    def __enter__(self):
        self.mem_base = mem_percent()
        try:
            self.vram_base = vram_used()[0]
        except Exception:
            self.vram_base = None
        self.t.start(); return self

    def __exit__(self, *a):
        self._stop = True; self.t.join(2)


def main():
    ap = argparse.ArgumentParser(description="Batch redraw blockouts with Qwen-Image-Edit-2511.")
    ap.add_argument("--prompts", required=True, help="prompts JSON (list of entries)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output folder (default work/concepts)")
    ap.add_argument("--root", help="folder that blockout paths are relative to (default: the prompts file's folder)")
    ap.add_argument("--url", default=comfy.URL, help="ComfyUI address")
    ap.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    ap.add_argument("--cfg", type=float, default=DEFAULT_CFG)
    ap.add_argument("--free", action="store_true", help="unload models first (after running the t2i model)")
    ap.add_argument("ids", nargs="*", help="only these entry ids")
    a = ap.parse_args()
    comfy.URL = a.url.rstrip("/")

    prompts = Path(a.prompts)
    root = Path(a.root) if a.root else prompts.parent
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    log_path, status_path = out / "redraw-log.jsonl", out / "redraw-status.json"

    def status(**kw):
        kw["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        status_path.write_text(json.dumps(kw, ensure_ascii=False, indent=1), "utf-8")

    def log(row):
        row["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    items = json.loads(prompts.read_text("utf-8"))
    if a.ids:
        unknown = set(a.ids) - {i["id"] for i in items}
        if unknown:
            sys.exit("not in the prompts file: " + ", ".join(sorted(unknown)))
        items = [i for i in items if i["id"] in a.ids]
    total = len(items)

    if not comfy.wait_up(CONNECT_TIMEOUT, on_wait=lambda: status(state=f"waiting for ComfyUI at {comfy.URL}", done=0, total=total)):
        status(state=f"exit: ComfyUI at {comfy.URL} did not answer within {CONNECT_TIMEOUT // 60} min (this script does not start it)",
               done=0, total=total)
        sys.exit("ComfyUI is not running")
    if a.free:
        comfy.free()

    def target_of(item):
        return out / item.get("category", "") / f"{item['id']}.png"

    done = sum(1 for i in items if target_of(i).exists())
    for item in items:
        target = target_of(item)
        if target.exists():
            continue
        src = root / item["blockout"]
        if not src.exists():
            log(dict(id=item["id"], name=item.get("name"), ok=False, error=f"blockout missing: {src}"))
            continue
        status(state="rendering", done=done, total=total, current=item["id"], name=item.get("name"))
        for attempt in (1, 2):
            try:
                t0 = time.time()
                with Peaks() as pk:
                    name = comfy.upload(str(src), "redraw_" + item["id"] + ".png")
                    wf = comfy.edit(item["prompt"], [name], seed=int(item.get("seed", 0)), steps=a.steps, cfg=a.cfg, lora=None,
                                    neg=item.get("neg", comfy.NEG_CN), denoise=float(item.get("strength", 1.0)),
                                    prefix=f"redraw/{item['id']}")
                    image = comfy.wait(comfy.submit(wf), node=comfy.SAVE_NODE, timeout=JOB_TIMEOUT)
                comfy.download(image, str(target))
                done += 1
                log(dict(id=item["id"], name=item.get("name"), ok=True, steps=a.steps, strength=item.get("strength", 1.0), seed=item.get("seed", 0),
                         seconds=round(time.time() - t0, 1), mem_base_pct=pk.mem_base, mem_peak_pct=pk.mem,
                         vram_base_mb=pk.vram_base, vram_peak_mb=pk.vram, vram_total_mb=pk.vram_total, file=str(target)))
                break
            except Exception as e:
                log(dict(id=item["id"], name=item.get("name"), ok=False, attempt=attempt, error=str(e)[:500]))
                if not comfy.up():
                    status(state="exit: ComfyUI went away", done=done, total=total, current=item["id"], error=str(e)[:300])
                    sys.exit("ComfyUI went away")
                time.sleep(10)

    status(state="all done" if done == total else "pass finished with failures, see redraw-log.jsonl", done=done, total=total)
    print("done", done, "/", total)


if __name__ == "__main__":
    main()
