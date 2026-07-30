#!/usr/bin/env python3
"""
WS0 retrieval spike - KB + Brain Semantic Retrieval Upgrade SOW.

Proves whether hybrid (dense + sparse) retrieval beats plain grep on the real KB.
The sparse/BM25 + chunking half runs offline. The dense/hybrid half downloads a
small embedding model from HuggingFace on first run (~130MB) - blocked in the Cowork
sandbox, fine on this PC / the STA server.

Usage:
    python3 ws0_spike.py "C:/Users/Adam/Documents/Claude/Knowledge Base"

Deps:
    pip install fastembed qdrant-client rank-bm25 numpy
    (add socksio only if you are behind a SOCKS proxy)

Gate to pass (per SOW Section 9): on the 10 meaning-not-words queries below, the
DENSE (or hybrid) top hit is a genuinely relevant note for at least 8/10, in cases
where grep returns the wrong note or nothing.
"""
import sys, os, re, glob, time

KB = sys.argv[1] if len(sys.argv) > 1 else "."
MAXCHARS = 1200  # recursive fallback: split oversized sections by paragraph

def chunk_markdown(text, path):
    title = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r'^#\s+(.+)$', text, re.M)
    if m: title = m.group(1).strip()
    chunks, cur_head, buf = [], title, []
    def flush():
        if not buf: return
        body = "\n".join(buf).strip()
        if not body: return
        pieces = [body]
        if len(body) > MAXCHARS:
            pieces, cur = [], ""
            for p in body.split("\n\n"):
                if len(cur) + len(p) > MAXCHARS and cur:
                    pieces.append(cur); cur = p
                else:
                    cur = (cur + "\n\n" + p).strip()
            if cur: pieces.append(cur)
        for pc in pieces:
            ctx = f"[{title} > {cur_head}]"  # Contextual Retrieval (KB module-01 / Anthropic 2024)
            chunks.append({"path": path, "title": title, "head": cur_head,
                           "text": pc, "embed_text": ctx + "\n" + pc})
    for line in text.splitlines():
        h = re.match(r'^(#{1,4})\s+(.+)$', line)
        if h:
            flush(); buf = []; cur_head = h.group(2).strip()
        else:
            buf.append(line)
    flush()
    return chunks

def load_chunks(kb):
    files = glob.glob(os.path.join(kb, "**", "*.md"), recursive=True)
    out = []
    for f in files:
        try: t = open(f, encoding="utf-8", errors="replace").read()
        except Exception: continue
        out.extend(chunk_markdown(t, f))
    return files, out

def tok(s): return re.findall(r"[a-z0-9]+", s.lower())

def build_bm25(chunks):
    from rank_bm25 import BM25Okapi
    return BM25Okapi([tok(c["embed_text"]) for c in chunks])

def bm25_search(bm25, chunks, query, k=5):
    sc = bm25.get_scores(tok(query))
    order = sorted(range(len(sc)), key=lambda i: sc[i], reverse=True)[:k]
    return [(chunks[i], sc[i]) for i in order]

def grep_search(files, query, k=5):
    terms = tok(query); hits = []
    for f in files:
        try: t = open(f, encoding="utf-8", errors="replace").read().lower()
        except Exception: continue
        s = sum(t.count(term) for term in terms)
        if s: hits.append((f, s))
    hits.sort(key=lambda x: x[1], reverse=True)
    return hits[:k]

def build_dense(chunks, queries, k=5):
    from fastembed import TextEmbedding
    import numpy as np
    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    vecs = np.array(list(model.embed([c["embed_text"] for c in chunks])))
    qv = {q: np.array(v) for q, v in zip(queries, model.embed(queries))}
    norms = np.linalg.norm(vecs, axis=1)
    def search(q):
        v = qv[q]
        sims = vecs @ v / (norms * np.linalg.norm(v) + 1e-9)
        order = sims.argsort()[::-1][:k]
        return [(chunks[i], float(sims[i])) for i in order]
    return search

def hybrid(bm25, chunks, dense, query, k=5):
    # simple reciprocal-rank fusion of sparse + dense
    def ranks(pairs):
        return {id(p[0]): r for r, p in enumerate(pairs)}
    b = bm25_search(bm25, chunks, query, 20)
    d = dense(query) if dense else []
    br, dr = ranks(b), ranks(d)
    pool = {id(c): c for c, _ in b + d}
    def rrf(cid): return 1/(60+br.get(cid,999)) + 1/(60+dr.get(cid,999))
    ranked = sorted(pool.values(), key=lambda c: rrf(id(c)), reverse=True)[:k]
    return ranked

QUERIES = [
    "how do I stop the model from forgetting to save my decisions",
    "keep a running clone up to date without wiping the remote",
    "which write can silently corrupt a file tail with padding",
    "make an agent sound less like a machine wrote it",
    "find sales without surfacing ones that already happened",
    "let non-Anthropic models call real tools from a chat box",
    "stop staff assistants from reading stale frozen knowledge",
    "why a page fetch comes back empty and what to use instead",
    "group tools so one process serves a whole domain",
    "prove a saved file was not cut off mid-write",
]

def rel(p): return os.path.relpath(p, KB)

def main():
    t0 = time.time()
    print(f"KB: {KB}")
    files, chunks = load_chunks(KB)
    print(f"files: {len(files)}  chunks: {len(chunks)}  ({round(time.time()-t0,1)}s)")
    bm25 = build_bm25(chunks)
    try:
        dense = build_dense(chunks, QUERIES)
        print("dense: AVAILABLE")
    except Exception as e:
        dense = None
        print(f"dense: SKIPPED - {e}")
    print("=" * 90)
    for q in QUERIES:
        print(f"\nQ: {q}")
        g = grep_search(files, q)
        print("  grep   ->", rel(g[0][0]) if g else "NO MATCH")
        b = bm25_search(bm25, chunks, q)
        print(f"  bm25   -> {rel(b[0][0]['path'])}  [{b[0][0]['head']}]")
        if dense:
            d = dense(q)
            print(f"  dense  -> {rel(d[0][0]['path'])}  [{d[0][0]['head']}]")
            h = hybrid(bm25, chunks, dense, q)
            print(f"  hybrid -> {rel(h[0]['path'])}  [{h[0]['head']}]")
    print("\n" + "=" * 90)
    print("GATE: for >=8/10, is the dense/hybrid top hit a genuinely relevant note where grep missed?")

if __name__ == "__main__":
    main()
