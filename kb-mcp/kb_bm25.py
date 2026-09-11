"""kb_bm25.py - stdlib-only BM25 retrieval engine for the kb-mcp service.

Ported from the proven reference engine at
`Knowledge Base/kb-search.py` (hand-rolled BM25, self-refreshing index cache).
This is the WS0-of-kb-semantic-retrieval / sparse half - NO fastembed, NO
qdrant, NO pip installs. Semantic hybrid is a later workstream (WS2 of the
kb-semantic-retrieval SOW); this module deliberately stays stdlib.

What it keeps from the reference, unchanged:
  - tokenizer: lowercase [a-z0-9]+ tokens len>=2
  - stem(): conservative suffix-normalizer (plural/gerund/past/adverb) applied
    IDENTICALLY at index and query time, so 'clocks/rebooting/randomly' match
    'clock/reboot/random'
  - structural chunking: a heading (#..###) plus its body; long bodies split
    with the heading repeated
  - BM25: k1=1.5, b=0.75, standard IDF
  - self-refreshing index: (file_count, max_mtime) signature; rebuild when the
    indexed file set changes or any indexed .md is newer than the build
  - output: [rank] score=X.X | slug | path:line | heading + a two-line snippet,
    cap at 10, LOW CONFIDENCE nearest-chunks on zero real hits

Deviations from the reference, and why (see FOR THE ARCHITECT note in the SOW):
  - The index cache lives IN-MEMORY in the long-running server process, keyed
    on the (file_count, max_mtime) signature, instead of a kb-search-index.json
    written into the KB root. The serving mount (/kb) is an rsync'd, possibly
    read-only copy that `rsync --delete` would clobber, so writing a cache file
    into it is unsafe. In-memory still self-refreshes on file-set/mtime change,
    which is the behaviour the acceptance criterion tests.
  - Hit paths are emitted KB-RELATIVE (e.g. `sta/school-tech/.../module-01.md`)
    rather than as absolute Windows paths, so the citation feeds kb_fetch
    directly (kb_fetch wants "a path exactly as returned by kb_search").
  - An optional `is_excluded(rel)` predicate is honoured so the service's
    mount-level exclusion list is enforced defense-in-depth at index time too.
"""

import math
import os
import re
from collections import Counter, defaultdict

K1 = 1.5
B = 0.75
MAX_CHUNK_LINES = 150
MAX_FILE_BYTES = 2 * 1024 * 1024
# Non-corpus directories, matched by exact name.
SKIP_DIRS = {"node_modules"}
# DIRECTORY name prefixes that prune the directory and its entire subtree. Mirrors
# EXCLUDE_DIR_PREFIXES in kb_config.py at this repo's root - duplicated, not imported,
# because kb-mcp/ is the Docker deploy unit and kb_config.py is not copied into the
# image. Keep the two in sync, or a file is citable in one retrieval layer and
# invisible in the other.
# "_" covers _to_delete, _retired, _raw, _duplicates, _staged: quarantined and
# superseded content that must never be citable.
# NOTE: DIRECTORY rule only. Underscore-prefixed FILES stay indexed on purpose -
# _known-issues.md, _summary.md, _syllabus.md and _article-index.md are real content,
# and the KB standard has _known-issues.md OUTRANK research modules on behavior it covers.
EXCLUDE_DIR_PREFIXES = ("_",)
# The exception list: underscore directories that ARE live reference and survive the
# prefix rule. Same six names as kb_config.py INCLUDE_DIR_NAMES - keep them in sync.
# A new underscore folder is EXCLUDED until someone adds it here.
INCLUDE_DIR_NAMES = {"_Apps", "_Claude-Projects", "_Research-Commissions",
                     "_System", "_Templates", "_prompts"}
# KB nav / generated files that are noise in search results (mirrors reference).
SKIP_ROOT_FILES = {"index.md", "index-lookup.md", "deep-research-prompts.md"}
SKIP_ANY_FILES = {"kb-search-index.json"}

TOKEN_RE = re.compile(r"[a-z0-9]+")
HEADING_RE = re.compile(r"^#{1,3}\s+\S")


def stem(w):
    """Conservative English suffix-normalizer (stdlib, no deps). Order matters:
    gerund/past/adverb first, then a guarded plural strip. Verbatim from the
    reference so index-time and query-time normalization stay identical."""
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("edly"):
        w = w[:-4]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    elif len(w) > 4 and w.endswith("ly"):
        w = w[:-2]
    if (len(w) > 3 and w.endswith("s")
            and not w.endswith(("ss", "us", "is"))):
        w = w[:-1]
    return w


def tokenize(text):
    return [stem(t) for t in TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def _chunk_lines(lines):
    """Split a file's lines into (start_idx0, heading, body_lines) segments."""
    heads = [i for i, ln in enumerate(lines) if HEADING_RE.match(ln)]
    segs = []
    first = heads[0] if heads else len(lines)
    if first > 0 and any(ln.strip() for ln in lines[:first]):
        segs.append((0, "(preamble)", lines[:first]))
    for k, h in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        heading = lines[h].lstrip("#").strip()
        segs.append((h, heading, lines[h:end]))
    out = []
    for start, heading, body in segs:
        if len(body) <= MAX_CHUNK_LINES:
            out.append((start, heading, body))
        else:
            for j in range(0, len(body), MAX_CHUNK_LINES):
                out.append((start + j, heading, body[j:j + MAX_CHUNK_LINES]))
    return out


def _make_snippet(body, heading):
    out = []
    for ln in body:
        s = ln.strip()
        if not s or s.lstrip("#").strip() == heading:
            continue
        out.append(s[:120])
        if len(out) == 2:
            break
    return "  ".join(out)


class KbIndex:
    """In-memory, self-refreshing BM25 index over a KB Markdown tree.

    kb_root      : directory to walk (whatever the service mounts; the caller
                   controls scope, this class does not widen it).
    is_excluded  : optional predicate(rel_path) -> bool; excluded files are
                   never indexed (mount-level exclusion, enforced here too).
    """

    def __init__(self, kb_root, is_excluded=None):
        self.kb_root = os.path.abspath(kb_root)
        self.is_excluded = is_excluded or (lambda rel: False)
        self._idx = None          # built lazily on first search
        self._signature = None    # (file_count, max_mtime) the index was built at

    # -- file walk -------------------------------------------------------
    def _iter_md_files(self):
        """Yield (abs_path, rel_path) for every indexable .md file."""
        for dirpath, dirnames, filenames in os.walk(self.kb_root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                           and (not d.startswith(EXCLUDE_DIR_PREFIXES)
                                or d in INCLUDE_DIR_NAMES)]
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                ap = os.path.join(dirpath, fn)
                rel = os.path.relpath(ap, self.kb_root).replace(os.sep, "/")
                if fn in SKIP_ANY_FILES:
                    continue
                if "/" not in rel and fn in SKIP_ROOT_FILES:
                    continue
                if self.is_excluded(rel):
                    continue
                try:
                    if os.path.getsize(ap) > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                yield ap, rel

    def _scan_signature(self):
        """(file_count, max_mtime) over the indexable set - the staleness key."""
        count = 0
        mx = 0.0
        for ap, _ in self._iter_md_files():
            count += 1
            try:
                m = os.path.getmtime(ap)
                if m > mx:
                    mx = m
            except OSError:
                pass
        return count, mx

    # -- build -----------------------------------------------------------
    def _build(self):
        chunks = []          # [slug, rel_path, start_line1, heading, snippet, dl]
        postings = defaultdict(list)
        total_dl = 0
        for ap, rel in self._iter_md_files():
            slug = os.path.dirname(rel) or rel
            try:
                with open(ap, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            for start, heading, body in _chunk_lines(lines):
                text = "\n".join(body)
                toks = tokenize(text)
                if not toks:
                    continue
                cid = len(chunks)
                tf = Counter(toks)
                dl = sum(tf.values())
                total_dl += dl
                for term, c in tf.items():
                    postings[term].append((cid, c))
                chunks.append([slug, rel, start + 1, heading,
                               _make_snippet(body, heading), dl])
        n = len(chunks)
        return {
            "N": n,
            "avgdl": (total_dl / n) if n else 0.0,
            "chunks": chunks,
            "postings": dict(postings),
        }

    def ensure_fresh(self):
        """Rebuild the in-memory index iff the file set / mtimes changed.
        Returns 'fresh' if the cached index was reused, 'rebuilt' otherwise."""
        sig = self._scan_signature()
        if self._idx is not None and sig == self._signature:
            return "fresh"
        self._idx = self._build()
        self._signature = sig
        return "rebuilt"

    # -- query -----------------------------------------------------------
    def _score(self, query):
        idx = self._idx
        N = idx["N"]
        avgdl = idx["avgdl"] or 1.0
        chunks = idx["chunks"]
        postings = idx["postings"]
        scores = defaultdict(float)
        for term in set(tokenize(query)):
            post = postings.get(term)
            if not post:
                continue
            df = len(post)
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            for cid, tf in post:
                dl = chunks[cid][5]
                denom = tf + K1 * (1 - B + B * dl / avgdl)
                scores[cid] += idf * (tf * (K1 + 1)) / denom
        return scores

    def _fallback_near(self, query, limit=3):
        """When BM25 finds nothing, rank by literal token overlap in
        heading+slug+snippet. Mirrors the reference's LOW CONFIDENCE path."""
        qtoks = set(tokenize(query))
        chunks = self._idx["chunks"]
        scored = []
        for cid, ch in enumerate(chunks):
            hay = (ch[0] + " " + ch[3] + " " + ch[4]).lower()
            ov = sum(1 for t in qtoks if t in hay)
            if ov:
                scored.append((ov, cid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [cid for _, cid in scored[:limit]]

    def search(self, query, top=10):
        """Return (hits, status, low_confidence, scanned).
        hits: list of dicts {rank, score, slug, path, line, heading, snippet}.
        low_confidence True when these are nearest-chunk fallbacks (0 real hits).
        status: 'fresh' | 'rebuilt' (whether the index refreshed this call)."""
        status = self.ensure_fresh()
        chunks = self._idx["chunks"]
        scores = self._score(query)
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        ranked = [(cid, s) for cid, s in ranked if s > 0][:top]

        low = False
        if not ranked:
            near = self._fallback_near(query)
            ranked = [(cid, 0.0) for cid in near]
            low = bool(near)

        hits = []
        for i, (cid, s) in enumerate(ranked, 1):
            slug, rel, line, heading, snippet, _ = chunks[cid]
            hits.append({
                "rank": i, "score": s, "slug": slug, "path": rel,
                "line": line, "heading": heading, "snippet": snippet,
            })
        return hits, status, low, self._idx["N"]

    def search_text(self, query, top=10):
        """Token-minimal text block for the MCP tool, mirroring kb-search.py's
        stdout format: one hit line + an indented two-line snippet, then a
        HITS/INDEX footer. Zero real hits -> LOW CONFIDENCE nearest chunks."""
        query = (query or "").strip()
        if not query:
            return "Empty query - give me search terms."
        hits, status, low, scanned = self.search(query, top=top)
        lines = []
        for h in hits:
            tag = "LOW CONFIDENCE " if low else ""
            lines.append("[%d] %sscore=%.1f | %s | %s:%d | %s" % (
                h["rank"], tag, h["score"], h["slug"], h["path"], h["line"],
                h["heading"]))
            if h["snippet"]:
                lines.append("    " + h["snippet"])
        if not hits:
            lines.append("HITS: 0 | INDEX: %s | scanned %d chunks (no near matches)"
                         % (status, scanned))
        elif low:
            lines.append("HITS: 0 | INDEX: %s | scanned %d chunks (nearest shown, LOW CONFIDENCE)"
                         % (status, scanned))
        else:
            lines.append("HITS: %d | INDEX: %s | scanned %d chunks"
                         % (len(hits), status, scanned))
        return "\n".join(lines)


if __name__ == "__main__":
    # CLI parity with the reference for spot-checking:
    #   python kb_bm25.py <kb_root> "query text" [top]
    import sys
    if len(sys.argv) < 3:
        print("usage: python kb_bm25.py <kb_root> \"query\" [top]")
        sys.exit(2)
    root = sys.argv[1]
    q = sys.argv[2]
    topn = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    print(KbIndex(root).search_text(q, top=topn))
