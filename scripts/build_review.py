"""Build a local review page: one card per concept image, with Pass / Redo buttons and a note box.

Choices are stored in the browser (localStorage). The footer turns them into a plain-text summary the reviewer
copies back to whoever runs the pipeline. Re-run this script after every redraw round.

Each card shows the concept image, name, id, size, and folded: notes (how sizes were derived), the prompt,
and with --show-blockout / --previous the blockout and the previous round's image.

Usage:
  python build_review.py --prompts examples/redraw_prompts.json --images work/concepts --out work/review.html
                         [--title "Concept review"] [--round 2] [--show-blockout] [--previous work/concepts-round1]
Images are expected at <images>/<category>/<id>.png (the layout batch_redraw.py writes).
"""
import argparse, html, json, os
from pathlib import Path

esc = html.escape


def rel(path, page_dir):
    return Path(os.path.relpath(Path(path).resolve(), page_dir.resolve())).as_posix()


def main():
    ap = argparse.ArgumentParser(description="Local review page for concept images.")
    ap.add_argument("--prompts", required=True, help="prompts JSON")
    ap.add_argument("--images", required=True, help="folder with <category>/<id>.png")
    ap.add_argument("--out", default="work/review.html")
    ap.add_argument("--title", default="Concept review")
    ap.add_argument("--round", type=int, default=1, help="round number (also keeps each round's choices separate)")
    ap.add_argument("--root", help="folder blockout paths are relative to (default: the prompts file's folder)")
    ap.add_argument("--show-blockout", action="store_true", help="fold the blockout into each card")
    ap.add_argument("--previous", help="folder of the previous round's images, folded into each card")
    ap.add_argument("--order", default="", help="comma-separated category order")
    a = ap.parse_args()

    prompts = Path(a.prompts)
    root = Path(a.root) if a.root else prompts.parent
    page = Path(a.out); page.parent.mkdir(parents=True, exist_ok=True)
    pdir = page.parent
    items = json.loads(prompts.read_text("utf-8"))
    title = a.title + (f" (round {a.round})" if a.round > 1 else "")
    store_id = "concept-review-" + "".join(ch for ch in prompts.stem + str(a.round) if ch.isalnum())
    order = [c for c in a.order.split(",") if c]
    cats = [c for _, c in sorted((order.index(c) if c in order else 99, c) for c in {i.get("category", "") for i in items})]

    sections = []
    for cat in cats:
        cards = []
        for it in [i for i in items if i.get("category", "") == cat]:
            concept = rel(Path(a.images) / cat / f"{it['id']}.png", pdir)
            figs = []
            if a.show_blockout and it.get("blockout"):
                b = rel(root / it["blockout"], pdir)
                figs.append(f'<figure><a href="{esc(b)}" target="_blank"><img src="{esc(b)}" loading="lazy" alt=""></a>'
                            f'<figcaption>blockout (strength {esc(str(it.get("strength", 1.0)))})</figcaption></figure>')
            if a.previous:
                p1 = rel(Path(a.previous) / cat / f"{it['id']}.png", pdir)
                figs.append(f'<figure><a href="{esc(p1)}" target="_blank"><img src="{esc(p1)}" loading="lazy" alt=""></a>'
                            f'<figcaption>previous round</figcaption></figure>')
            extra = f'<details open><summary>Blockout / previous</summary><div class="olds">{"".join(figs)}</div></details>' if figs else ""
            notes = it.get("notes", "")
            if isinstance(notes, list):
                notes = "; ".join(map(str, notes))
            cards.append(f"""
<article class="card" data-id="{esc(it['id'])}" data-name="{esc(it.get('name', it['id']))}">
  <a class="concept" href="{esc(concept)}" target="_blank"><img src="{esc(concept)}" loading="lazy" alt="{esc(it.get('name', ''))}"></a>
  <div class="body">
    <h3>{esc(it.get('name', it['id']))}</h3>
    <p class="meta"><code>{esc(it['id'])}</code> · {esc(str(it.get('size', '')))}</p>
    <div class="choice">
      <button data-v="pass">Pass</button><button data-v="redo">Redo</button>
      <input class="note" placeholder="Note: what to change, or drop this one">
    </div>
    {extra}
    <details><summary>Notes</summary><p>{esc(str(notes))}</p></details>
    <details><summary>Prompt</summary><p>{esc(it.get('prompt', ''))}</p></details>
  </div>
</article>""")
        sections.append(f'<section><h2>{esc(cat or "uncategorised")} <span class="n">{len(cards)}</span></h2><div class="grid">{"".join(cards)}</div></section>')

    out = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
:root {{ --bg:#f3efe6; --card:#fffdf8; --fg:#2b2a27; --mute:#6f6a60; --line:#ddd5c5; --pass:#2f7a4b; --redo:#b0432f; --accent:#3b5a78; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1d1c1a; --card:#272522; --fg:#ece6da; --mute:#a59e91; --line:#3b3833; --pass:#5fb07c; --redo:#e07a63; --accent:#8fb1d1; color-scheme:dark; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.6 system-ui,"Microsoft YaHei","PingFang SC",sans-serif; padding:0 max(16px,3vw) 120px; }}
header {{ position:sticky; top:0; z-index:5; background:var(--bg); border-bottom:1px solid var(--line); padding:12px 0; display:flex; flex-wrap:wrap; gap:12px 20px; align-items:center; }}
header h1 {{ font-size:20px; margin:0; }}
.stat b {{ font-variant-numeric:tabular-nums; }}
.filters button, .choice button, .tools button {{ border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:6px; padding:4px 10px; cursor:pointer; font:inherit; }}
.filters button.on {{ border-color:var(--accent); color:var(--accent); font-weight:600; }}
h2 {{ font-size:18px; margin:28px 0 10px; }} h2 .n {{ color:var(--mute); font-weight:400; font-size:14px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(min(340px,100%),1fr)); gap:16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }}
.card.pass {{ outline:3px solid var(--pass); }} .card.redo {{ outline:3px solid var(--redo); }}
.concept img {{ width:100%; aspect-ratio:1; object-fit:cover; display:block; background:#eee6d6; }}
.body {{ padding:10px 14px 14px; min-width:0; }}
.body h3 {{ margin:0; font-size:16px; }}
.meta {{ margin:2px 0 8px; color:var(--mute); font-size:13px; }}
.choice {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:6px; }}
.choice button[data-v=pass].on {{ background:var(--pass); color:#fff; border-color:var(--pass); }}
.choice button[data-v=redo].on {{ background:var(--redo); color:#fff; border-color:var(--redo); }}
.note {{ flex:1 1 160px; min-width:0; border:1px solid var(--line); border-radius:6px; padding:4px 8px; background:var(--bg); color:var(--fg); font:inherit; }}
details {{ font-size:13px; color:var(--mute); margin-top:4px; }} details p {{ margin:4px 0; color:var(--fg); }}
.olds {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }}
.olds figure {{ margin:0; width:140px; }} .olds img {{ width:140px; height:140px; object-fit:contain; background:#efe9dc; border-radius:4px; }}
.olds figcaption {{ font-size:11px; word-break:break-all; }}
footer {{ position:fixed; left:0; right:0; bottom:0; background:var(--card); border-top:1px solid var(--line); padding:10px max(16px,3vw); }}
footer textarea {{ width:100%; height:64px; font:12px/1.5 ui-monospace,Consolas,monospace; background:var(--bg); color:var(--fg); border:1px solid var(--line); border-radius:6px; }}
.tools {{ display:flex; gap:8px; align-items:center; margin-bottom:6px; flex-wrap:wrap; }}
.hidden {{ display:none !important; }}
</style></head><body>
<header>
  <h1>{esc(title)}</h1>
  <span class="stat"><b id="total">0</b> images · pass <b id="cPass">0</b> · redo <b id="cRedo">0</b> · not reviewed <b id="cTodo">0</b></span>
  <span class="filters"><button data-f="all" class="on">All</button> <button data-f="todo">Not reviewed</button> <button data-f="redo">Redo</button> <button data-f="pass">Pass</button></span>
</header>
<p style="color:var(--mute);margin:12px 0 0">Click an image to open it full size. Choices are saved in this browser. Copy the summary at the bottom and send it back.</p>
{''.join(sections)}
<footer>
  <div class="tools"><b>Summary</b><button id="copy">Copy summary</button><span id="tip" style="color:var(--mute);font-size:13px"></span></div>
  <textarea id="out" readonly></textarea>
</footer>
<script>
const STORE = '{store_id}';
let state = {{}};
try {{ state = JSON.parse(localStorage.getItem(STORE) || '{{}}'); }} catch (e) {{}}
const cards = [...document.querySelectorAll('.card')];
let filter = 'all';
function save() {{ try {{ localStorage.setItem(STORE, JSON.stringify(state)); }} catch (e) {{}} }}
function render() {{
  let p = 0, r = 0;
  const pass = [], redo = [], todo = [];
  for (const c of cards) {{
    const s = state[c.dataset.id] || {{}};
    c.classList.toggle('pass', s.v === 'pass'); c.classList.toggle('redo', s.v === 'redo');
    c.querySelectorAll('.choice button').forEach(b => b.classList.toggle('on', b.dataset.v === s.v));
    const label = c.dataset.name + ' (' + c.dataset.id + ')' + (s.note ? ': ' + s.note : '');
    if (s.v === 'pass') {{ p++; pass.push(label); }} else if (s.v === 'redo') {{ r++; redo.push(label); }} else todo.push(c.dataset.name + ' (' + c.dataset.id + ')');
    const show = filter === 'all' || (filter === 'todo' && !s.v) || s.v === filter;
    c.classList.toggle('hidden', !show);
  }}
  document.querySelectorAll('section').forEach(sec => sec.classList.toggle('hidden', !sec.querySelector('.card:not(.hidden)')));
  total.textContent = cards.length; cPass.textContent = p; cRedo.textContent = r; cTodo.textContent = cards.length - p - r;
  out.value = 'Concept review (' + cards.length + ' images)\\nPass ' + p + ': ' + (pass.join('; ') || 'none') + '\\nRedo ' + r + ': ' + (redo.join('; ') || 'none') + '\\nNot reviewed ' + todo.length + ': ' + (todo.join('; ') || 'none');
}}
cards.forEach(c => {{
  const id = c.dataset.id, s = state[id] || {{}};
  const note = c.querySelector('.note'); note.value = s.note || '';
  c.querySelectorAll('.choice button').forEach(b => b.onclick = () => {{
    const cur = state[id] || {{}}; cur.v = cur.v === b.dataset.v ? undefined : b.dataset.v; state[id] = cur; save(); render();
  }});
  note.oninput = () => {{ const cur = state[id] || {{}}; cur.note = note.value; state[id] = cur; save(); render(); }};
}});
document.querySelectorAll('.filters button').forEach(b => b.onclick = () => {{
  filter = b.dataset.f; document.querySelectorAll('.filters button').forEach(x => x.classList.toggle('on', x === b)); render();
}});
copy.onclick = async () => {{
  try {{ await navigator.clipboard.writeText(out.value); tip.textContent = 'Copied'; }}
  catch (e) {{ out.select(); tip.textContent = 'Selected, press Ctrl+C / Cmd+C'; }}
}};
render();
</script></body></html>"""
    page.write_text(out, "utf-8")
    print(page, len(items), "images in", len(cats), "categories")


if __name__ == "__main__":
    main()
