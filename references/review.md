# Review: showing the owner and keeping a record / 审核

## Review page

`scripts/build_review.py` writes a local HTML page:

- one card per building, concept image first, with name, id and size;
- Pass / Redo buttons and a note box;
- folded: notes (how the sizes were derived), the prompt; with `--show-blockout` and `--previous`, the blockout and the previous round's image;
- choices are kept in the browser; the footer turns them into a text summary to copy back.

## Review log

One table per round, in a `review-log.md` in the work folder:

| # | Concept (name, id) | Verdict (pass / redo / drop / add) | What to change |
|---|---|---|---|

- Quote the owner's words, then write how you will change it.
- If the owner asks "why is there an X?", first say truthfully where it came from (the prompt asked for it, the model added it, or you added it when deriving the design), then the fix.
- Images the owner does not mention count as passed.
- Feedback that applies generally ("walls should be separate assets") is promoted to a **general rule** under the table, marked as set by the owner or inferred by you. Inferred rules apply only if the owner does not object. Copy accepted rules into `references/rules.md`.

## Redraw

- Change the prompt or the blockout — through the scripts that generate them, never by hand-editing generated JSON.
- Move old images out of the output folder (don't delete them); the batch script fills the gaps.
- Trial the few you are least sure of first. If they work, run the rest; fix any systematic problem a trial reveals (e.g. city-wall colour) before the full run.
- Build the review page again for the next round.
