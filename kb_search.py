#!/usr/bin/env python3
"""
WS1 search - dense-primary retrieval with exact-token sparse assist and reranking.

    python3 kb_search.py "how do I stop the model from forgetting to save decisions"
    python3 kb_search.py --k 8 "TT10 clock frozen error"

Fusion policy (from WS0 findings): dense is primary. Sparse (BM25) is added ONLY when the
query contains exact tokens (error codes, versions, quoted strings) - naive RRF let BM25
keyword-coincidence junk pollute results. A cross-encoder reranks the union when available.
"""
import os, sys, re, pickle, functools
import kb_config as C
from kb_common import tok

_EXACT = re.compile(r'"[^"]+"|\b[A-Z]{2,}\d|\bv?\d+\.\d+|\b[A-Z0-9]{3,}-[A-Z0-9]+|\bTT\d+\b')


def has_exact_tokens(q):
    return bool(_EXACT.search(q))


@functools.lru_cache(maxsize=1)
def _load():
    from fastembed import TextEmbedding
    from qdrant_client import QdrantClient
    embedder = TextEmbedding(model_name=C.EMBED_MODEL)
    client = QdrantClient(path=C.QDRANT_PATH)
    bm25 = pickle.load(open(C.BM25_PATH, "rb")) if os.path.exists(C.BM25_PATH) else None
    return embedder, client, bm25


@functools.lru_cache(maxsize=1)
def _reranker():
    """Return a scorer fn(query, [docs]) -> [float], or None. Prefer fastembed (no torch)."""
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        for name in (C.RERANK_MODEL, "Xenova/ms-marco-MiniLM-L-6-v2"):
            try:
                ce = TextCrossEncoder(model_name=name)
                return lambda q, docs: list(ce.rerank(q, docs))
            except Exception:
                continue
    except Exception:
        pass
    try:
        from sentence_transformers import CrossEncoder
        ce = CrossEncoder(C.RERANK_MODEL)
        return lambda q, docs: list(ce.predict([(q, d) for d in docs]))
    except Exception:
        return None


def _key(p):
    return (p["path"], p["head"], p["text"][:60])


def search(query, k=C.FINAL_K):
    embedder, client, bm25 = _load()
    qv = list(embedder.embed([query]))[0]
    hits = client.query_points(C.COLLECTION, query=list(map(float, qv)),
                               limit=C.DENSE_TOPN, with_payload=True).points
    cand, seen = [], set()
    for h in hits:
        pl = dict(h.payload); pl["_dense"] = float(h.score)
        cand.append(pl); seen.add(_key(pl))

    # Exact-token queries: add sparse candidates the dense pass missed.
    if bm25 and has_exact_tokens(query):
        scores = bm25["bm25"].get_scores(tok(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:C.SPARSE_TOPN]
        for i in order:
            pl = dict(bm25["meta"][i])
            if _key(pl) not in seen:
                pl["_dense"] = 0.0; cand.append(pl); seen.add(_key(pl))

    # Rerank the candidate pool (dense-primary fallback if no reranker).
    rr = _reranker()
    if rr and cand:
        docs = [f"{p['title']} > {p['head']}\n{p['text']}" for p in cand]
        for p, s in zip(cand, rr(query, docs)):
            p["_score"] = float(s)
    else:
        for p in cand:
            p["_score"] = p["_dense"]
    cand.sort(key=lambda p: p["_score"], reverse=True)
    return cand[:k]


def _fmt(p):
    rel = p["path"]
    return f"[{p['label']}] {os.path.basename(p['path'])}  >  {p['head']}\n    {rel}\n    {p['text'][:200].strip()}..."


def main():
    args = sys.argv[1:]
    k = C.FINAL_K
    if "--k" in args:
        i = args.index("--k"); k = int(args[i + 1]); del args[i:i + 2]
    if not args:
        print('usage: python3 kb_search.py [--k N] "your query"'); return
    q = " ".join(args)
    for rank, p in enumerate(search(q, k), 1):
        print(f"\n{rank}. score={p['_score']:.3f}  " + _fmt(p))


if __name__ == "__main__":
    main()
