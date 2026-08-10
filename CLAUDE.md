# CLAUDE.md - kb-semantic-retrieval

See @README.md for what this project is.

Retrieval-layer upgrade for the KB and Markdown brains: semantic (embedding) search plus
dense-primary ranking over the existing Markdown, without changing the files themselves.

## Git status: GitHub repo (private)
Under version control: **`abaker421/kb-semantic-retrieval`** (private), branch `main`.
Follow the standard protected-`main` PR flow used by every other repo in `source/repos`:
branch + PR, never push `main` directly, let Adam merge (no self-merge, no `--auto`).
`gh` is authed as **buildwithbaker** (write); plain `git push` can hit a stale credential,
so push via the gh token as `x-access-token` (same pattern as the other abaker421 repos).
Commit identity: `Adam Baker <bakeradm6@gmail.com>`. `index_data/` and `__pycache__/` are
gitignored generated data; only `kb_tokens.example` is tracked, never a live `kb_tokens`.

## Run
```
pip install fastembed qdrant-client rank-bm25 numpy
python3 kb_index.py                      # incremental; persists to ./index_data/
python3 kb_search.py "your question"     # dense-primary search
python3 kb_search.py --k 8 "TT10 clock frozen error"
```
- `kb_index.py` is incremental - re-run any time; only new/changed files re-embed and
  deleted files purge. That is the fix for the 45-minute full-embed cost (33,736 chunks).
- `kb_search.py` is dense-primary: semantic first, BM25 added only for exact-token queries
  (error codes, version strings, `"quoted"` text), then a cross-encoder rerank when one is
  installed. This is deliberate - naive RRF hybrid was polluted by BM25 junk in the WS0
  spike.
- Corpus roots are in `kb_config.py` (`ROOTS`): Knowledge Base, Project Blueprints,
  Backups/skills, and the three brains (personal, work, creative).

## Nightly maintenance (you usually do NOT need to run kb_index.py by hand)
As of 2026-08-10 the index is refreshed automatically every night at 03:00 local by the
Windows scheduled task **`KB Semantic Index Nightly`** (see `scripts/README.md`). It runs
`scripts\kb-index-nightly.ps1`, which pre-flights the corpus roots, runs `kb_index.py`, and
writes a log + `status.json` to `C:\Users\Adam\Documents\Claude\reports\system-health\kb-index\`.
So after a deep-research commission you no longer have to run `kb_index.py` yourself - the new
modules are picked up on the next nightly run (or run it by hand if you need them retrievable
immediately). Manage the task with `scripts\register-kb-index-task.ps1`.

## Where it must run
**Not in the Cowork cloud sandbox** - HuggingFace is blocked by its proxy, so the embedding
model cannot download. Run on Adam's PC or the STA server.

## Do not touch
- `index_data/` is the generated Qdrant store - regenerate with `kb_index.py`, never edit.
- `__pycache__/` is generated.
- Index hygiene matters: keep `node_modules` and binaries out of the corpus (a WS0 finding).
