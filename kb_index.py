#!/usr/bin/env python3
"""
WS1 indexer - build/update the persistent semantic index.

Incremental: only changed/new files are re-embedded; deleted files are purged.
Run again any time; it diffs against the manifest.

    pip install fastembed qdrant-client rank-bm25 numpy
    python kb_index.py

Output: persistent Qdrant collection + BM25 pickle + manifest under ./index_data/.
"""
import os, json, pickle, uuid, time
import kb_config as C
from kb_common import iter_files, chunk_markdown, tok, file_hash


def load_manifest():
    if os.path.exists(C.MANIFEST_PATH):
        return json.load(open(C.MANIFEST_PATH, encoding="utf-8"))
    return {}


def save_manifest(m):
    os.makedirs(C.DATA_DIR, exist_ok=True)
    json.dump(m, open(C.MANIFEST_PATH, "w", encoding="utf-8"))


def pid(path, i):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path}::{i}"))


def main():
    from fastembed import TextEmbedding
    from qdrant_client import QdrantClient, models
    os.makedirs(C.DATA_DIR, exist_ok=True)

    manifest = load_manifest()
    current = {}   # path -> (label, text, hash)
    pruned_dirs = {}
    for label, path in iter_files(pruned_dirs):
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        current[path] = (label, text, file_hash(text))

    # Underscore dirs are excluded by default and C.INCLUDE_DIR_NAMES is the only way back
    # in - so that allow-list can go stale and silently drop a new LIVE folder. Log what we
    # pruned every run: an unfamiliar name here means "go add it to INCLUDE_DIR_NAMES".
    if pruned_dirs:
        summary = ", ".join(f"{d} ({n} .md)" for d, n in sorted(pruned_dirs.items()))
        print(f"pruned dirs: {len(pruned_dirs)} names | {sum(pruned_dirs.values())} .md skipped "
              f"| allow-listed: {', '.join(C.INCLUDE_DIR_NAMES)} | {summary}", flush=True)
    else:
        print(f"pruned dirs: none | allow-listed: {', '.join(C.INCLUDE_DIR_NAMES)}", flush=True)

    changed = [p for p, (_, _, h) in current.items() if manifest.get(p) != h]
    deleted = [p for p in manifest if p not in current]
    print(f"files: {len(current)} total | {len(changed)} new/changed | {len(deleted)} deleted")

    embedder = TextEmbedding(model_name=C.EMBED_MODEL)
    client = QdrantClient(path=C.QDRANT_PATH)

    dim = len(list(embedder.embed(["dimension probe"]))[0])
    existing = [c.name for c in client.get_collections().collections]
    if C.COLLECTION not in existing:
        client.create_collection(
            C.COLLECTION,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )

    def purge(path):
        client.delete(C.COLLECTION, points_selector=models.FilterSelector(
            filter=models.Filter(must=[models.FieldCondition(
                key="path", match=models.MatchValue(value=path))])))

    for p in deleted:
        purge(p)

    t0 = time.time()
    total = len(changed)
    total_chunks = 0
    for n, path in enumerate(changed, 1):
        label, text, h = current[path]
        purge(path)  # clear old chunks (handles shrink)
        chunks = chunk_markdown(text, path, label)
        if chunks:
            vecs = list(embedder.embed([c["embed_text"] for c in chunks]))
            points = [models.PointStruct(
                id=pid(path, i), vector=list(map(float, v)),
                payload={"path": c["path"], "label": c["label"], "title": c["title"],
                         "head": c["head"], "text": c["text"]})
                for i, (c, v) in enumerate(zip(chunks, vecs))]
            client.upsert(C.COLLECTION, points=points)
            total_chunks += len(chunks)
        manifest[path] = h
        if n % 10 == 0 or n == total:
            el = time.time() - t0
            pct = 100 * n / total if total else 100
            eta = (el / n) * (total - n) if n else 0
            print(f"  {n}/{total} files ({pct:.0f}%) | {total_chunks} chunks | "
                  f"{round(el)}s elapsed | ~{round(eta)}s left", flush=True)

    for p in deleted:
        manifest.pop(p, None)
    save_manifest(manifest)

    print("rebuilding BM25 sparse index ...", flush=True)
    from rank_bm25 import BM25Okapi
    meta, corpus, offset = [], [], None
    while True:
        pts, offset = client.scroll(C.COLLECTION, limit=2000, offset=offset,
                                    with_payload=True, with_vectors=False)
        for pt in pts:
            pl = pt.payload
            meta.append(pl)
            header = "[" + pl["label"] + ": " + pl["title"] + " > " + pl["head"] + "]"
            corpus.append(tok(header + "\n" + pl["text"]))
        if offset is None:
            break
    pickle.dump({"bm25": BM25Okapi(corpus), "meta": meta}, open(C.BM25_PATH, "wb"))
    print(f"done. {len(meta)} chunks indexed. total {round(time.time() - t0)}s", flush=True)


if __name__ == "__main__":
    main()
