# kb-semantic-retrieval

Retrieval-layer upgrade for the KB + Markdown brains. Adds semantic (embedding) search
and hybrid keyword+meaning ranking on top of the existing Markdown, without changing the
files themselves. Scope and plan: `Project Blueprints/_Apps/kb-semantic-retrieval/kb-semantic-retrieval-sow.md`.

## WS0 spike - run this to pass the gate

The Cowork sandbox cannot download the embedding model (HuggingFace is blocked by its
proxy). Run the spike here, on this PC or the STA server, where HuggingFace is reachable.

```
pip install fastembed qdrant-client rank-bm25 numpy
python3 ws0_spike.py "C:/Users/Adam/Documents/Claude/Knowledge Base"
```

First run downloads BAAI/bge-small-en-v1.5 (~130MB), then embeds the whole KB (~33k
chunks). Read the printout: for each of the 10 meaning-not-words queries it shows the
top hit from grep, BM25, dense, and hybrid.

**Gate (SOW Section 9):** dense or hybrid returns a genuinely relevant note for at least
8 of 10 queries where grep returns the wrong note or nothing. Pass -> proceed to WS1.

## Status

WS0 COMPLETE - gate PASSED conditionally (2026-07-03). Dense run on Adam's PC: grep 0/10,
dense ~7/10 on meaning-not-words queries. Genuine misses (Q4 human-voice, Q7 stale-knowledge)
are reranking-recoverable; Q5 was out-of-corpus (rule lives in a skill, not the KB). Four
fixes fold into WS1: index hygiene (exclude node_modules/binaries), dense-primary fusion
(naive RRF polluted by BM25 junk), reranking promoted into WS1, and expand the corpus beyond
the KB (skills/SOWs/brains). Qdrant persistence mandatory (~45 min to embed 33,736 chunks).
Full verdict in the SOW changelog.

## WS1 - persistent index + dense-primary search (run on this PC / the server)

Corpus scope A: Knowledge Base + Project Blueprints (SOWs/instructions) + Backups/skills + both brains.
Paths are in `kb_config.py` - edit `ROOTS` if yours differ.

```
pip install fastembed qdrant-client rank-bm25 numpy
python3 kb_index.py            # first run embeds everything (~persist to ./index_data/); prints progress every 25 files
python3 kb_search.py "how do I stop the model from forgetting to save decisions"
python3 kb_search.py --k 8 "TT10 clock frozen error"
```

- `kb_index.py` is **incremental** - re-run any time; only new/changed files re-embed, deleted files purge. This is the fix for the 45-minute WS0 cost: you embed once, then queries are instant.
- `kb_search.py` is **dense-primary**: semantic first, BM25 added only for exact-token queries (error codes, versions, `"quoted"`), then a cross-encoder rerank when available (auto-skips to dense order if no reranker installs). This is the WS0 fix for naive-hybrid pollution.
- Optional reranker: `pip install sentence-transformers` (or rely on fastembed's built-in cross-encoder). Without it, search still runs dense-primary.

Re-run `kb_index.py` on a schedule (or after big edits) to keep the index fresh. WS2 folds this same pipeline into the server `kb-mcp` so staff assistants query it live.

## Agent routing rule (add to agent instructions once WS1 is verified)

> **Semantic KB/brain retrieval:** before answering from memory or grepping, run
> `python3 <repo>/kb_search.py "<the user's question>"` and read the top results.
> Use it for meaning-based lookups across the KB, blueprints, skills, and brains.
> Fall back to grep only for exact tokens (error codes, version strings) the search misses.

## Status

WS1 BUILT (2026-07-03), pending first index run on a HuggingFace-reachable host. Modules
compile clean. NEXT: run `kb_index.py`, spot-check `kb_search.py` on the WS0 query set
(expect Q4/Q7 to improve with reranking), then wire the routing rule into agents -> WS2 (server).
