"""Minimal ComfyUI client: build Qwen-Image workflows, upload inputs, submit, wait, download, free memory.

Talks to ComfyUI only over HTTP, so ComfyUI can live anywhere. Configure with the constants below or
environment variables (COMFY_URL, COMFY_LOG). Model filenames are the names inside your ComfyUI model folders.

Functions: up, upload, submit, wait, download, t2i, edit, run, free.
"""
import json, os, re, subprocess, threading, time, urllib.error, urllib.parse, urllib.request, uuid

URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8189")
# Optional: ComfyUI's stderr log. When set, run() reads seconds-per-step from the progress bars.
LOG = os.environ.get("COMFY_LOG", "")

# Apache-2.0 models (see README "Model licences").
UNET_T2I = "qwen_image_2512_fp8_e4m3fn.safetensors"
UNET_EDIT = "qwen_image_edit_2511_fp8mixed.safetensors"
CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"
# Speed-up LoRAs. Measured: the 8-step edit LoRA rewrites structure (gatehouse -> hexagonal pavilion), so the
# redraw step does not use it. Kept for quick tests only.
LORA_T2I = {8: "Qwen-Image-2512-Lightning-8steps-V1.0-bf16.safetensors", 4: "Qwen-Image-2512-Lightning-4steps-V1.0-bf16.safetensors"}
LORA_EDIT = {8: "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", 4: "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"}
# Generic quality negatives (Chinese, the language the prompts were tested in).
NEG_CN = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲"

SAVE_NODE = "47"  # SaveImage node id in edit()


def up():
    """True when ComfyUI answers."""
    try:
        urllib.request.urlopen(URL + "/system_stats", timeout=3).read(); return True
    except Exception:
        return False


def wait_up(timeout=600, on_wait=None):
    """Block until ComfyUI answers; return False after `timeout` seconds."""
    t = time.time()
    while not up():
        if time.time() - t > timeout:
            return False
        if on_wait:
            on_wait()
        time.sleep(5)
    return True


def upload(path, name=None):
    """Upload a local image to ComfyUI's input folder; returns the name to use in LoadImage."""
    name = name or os.path.basename(path)
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + data + \
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(URL + "/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    res = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return (res.get("subfolder") + "/" if res.get("subfolder") else "") + res["name"]


def submit(wf):
    req = urllib.request.Request(URL + "/prompt", data=json.dumps({"prompt": wf}).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError("ComfyUI rejected the workflow: " + e.read().decode("utf-8", "replace")[:2000])


def wait(pid, node=None, timeout=3600):
    """Wait for a prompt. Returns {node_id: [image descriptor, ...]}; with `node`, only that node's first image.
    An image descriptor is {"filename", "subfolder", "type"}; pass it to download()."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = json.loads(urllib.request.urlopen(URL + "/history/" + pid, timeout=10).read())
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") != "success":
                raise RuntimeError("generation failed: " + json.dumps(st.get("messages", []), ensure_ascii=False)[:2000])
            outs = {nid: list(out.get("images", [])) for nid, out in h[pid]["outputs"].items()}
            if node:
                return outs[node][0]
            return outs
        time.sleep(0.5)
    raise RuntimeError("timed out waiting for ComfyUI")


def download(image, target):
    """Save one output image (descriptor from wait()) to a local path."""
    q = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
    data = urllib.request.urlopen(URL + "/view?" + q, timeout=120).read()
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "wb") as f:
        f.write(data)
    return target


class VramPeak:
    """Poll nvidia-smi every 0.25 s and keep the peak of whole-card VRAM used (per-process numbers are not
    available under Windows WDDM). Silently does nothing without nvidia-smi."""
    def __init__(self):
        self.peak = 0; self.base = None; self._stop = False
        self.t = threading.Thread(target=self._run, daemon=True)
    def _read(self):
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
        return int(o.strip().splitlines()[0])
    def _run(self):
        while not self._stop:
            try: self.peak = max(self.peak, self._read())
            except Exception: pass
            time.sleep(0.25)
    def __enter__(self):
        try: self.base = self._read()
        except Exception: self.base = None
        self.t.start(); return self
    def __exit__(self, *a):
        self._stop = True; self.t.join(2)


def log_size():
    return os.path.getsize(LOG) if LOG and os.path.exists(LOG) else 0


def step_times(since):
    """Seconds per step of every sampler progress bar written to LOG after byte offset `since`."""
    if not LOG or not os.path.exists(LOG):
        return []
    with open(LOG, "rb") as f:
        f.seek(since); txt = f.read().decode("utf-8", "replace")
    res = []
    # last tqdm frame: "100%|...| 50/50 [01:20<00:00,  1.60s/it]" or "4.2it/s"
    for m in re.finditer(r"100%\|[^|]*\|\s*(\d+)/(\d+) \[([\d:]+)<[\d:?]+,\s*([\d.]+)(s/it|it/s)", txt):
        n = int(m.group(1)); el = m.group(3).split(":"); secs = sum(int(x) * 60 ** i for i, x in enumerate(reversed(el)))
        rate = float(m.group(4)); spi = rate if m.group(5) == "s/it" else 1 / rate
        res.append({"steps": n, "elapsed": secs, "s_per_it": round(spi, 2)})
    out = []
    for r in res:  # drop repeated prints of the same bar
        if not out or out[-1] != r: out.append(r)
    return out


# ---------- workflows ----------
def t2i(prompt, w, h, seed, steps, cfg, lora=None, neg=NEG_CN, shift=3.1, prefix="qwen2512/t2i", lora_strength=1.0):
    """Text-to-image with Qwen-Image-2512."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET_T2I, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["4" if lora else "1", 0], "shift": shift}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": neg}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["5", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0],
                                                    "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }
    if lora:
        g["4"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": lora_strength}}
    return g


def edit(prompt, images, seed, steps, cfg, lora=None, prefix="qwen2511/edit", latent_from=None, denoise=1.0, shift=3.1, neg="",
         scale=True, lora_strength=1.0):
    """Qwen-Image-Edit-2511. images: names in ComfyUI's input folder (up to 3, see upload()) or [node, slot] refs.
    Image 1 goes through FluxKontextImageScale as in the official template. The starting latent is image 1 encoded
    (or latent_from), so `denoise` is the redraw strength: 1.0 for one building, 0.85 for a whole compound."""
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET_EDIT, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": shift}},
        "5": {"class_type": "CFGNorm", "inputs": {"model": ["4", 0], "strength": 1.0}},
    }
    model = ["5", 0]
    if lora:
        g["6"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["5", 0], "lora_name": lora, "strength_model": lora_strength}}
        model = ["6", 0]
    refs = []
    for i, im in enumerate(images, 1):
        if isinstance(im, str):
            g[f"2{i}"] = {"class_type": "LoadImage", "inputs": {"image": im}}
            ref = [f"2{i}", 0]
        else:
            ref = im
        if i == 1 and scale:
            g["30"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": ref}}
            ref = ["30", 0]
        refs.append(ref)
    for nid, text in (("40", prompt), ("41", neg)):
        g[nid] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": text}}
        for i, r in enumerate(refs, 1):
            g[nid]["inputs"][f"image{i}"] = r
    g["42"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["40", 0], "reference_latents_method": "index_timestep_zero"}}
    g["43"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["41", 0], "reference_latents_method": "index_timestep_zero"}}
    g["44"] = {"class_type": "VAEEncode", "inputs": {"pixels": latent_from or refs[0], "vae": ["3", 0]}}
    g["45"] = {"class_type": "KSampler", "inputs": {"model": model, "positive": ["42", 0], "negative": ["43", 0], "latent_image": ["44", 0],
                                                     "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "denoise": denoise}}
    g["46"] = {"class_type": "VAEDecode", "inputs": {"samples": ["45", 0], "vae": ["3", 0]}}
    g[SAVE_NODE] = {"class_type": "SaveImage", "inputs": {"images": ["46", 0], "filename_prefix": prefix}}
    return g


def run(wf):
    """Run a workflow. Returns (image descriptors, seconds, VRAM peak MB, VRAM before MB, per-step records)."""
    log_start = log_size()
    with VramPeak() as vp:
        t0 = time.time()
        pid = submit(wf)
        outs = wait(pid)
        dt = time.time() - t0
    images = [im for v in outs.values() for im in v]
    return images, round(dt, 1), vp.peak, vp.base, step_times(log_start)


def free():
    """Ask ComfyUI to unload models and free memory. Call it before switching between the t2i and edit models
    (each is about 20 GB), so they are never loaded at the same time."""
    req = urllib.request.Request(URL + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()
    time.sleep(3)
