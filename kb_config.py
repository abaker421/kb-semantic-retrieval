"""
WS1 config for the KB + Brain semantic retrieval index.
Edit ROOTS if your paths differ. Everything else has sane defaults.
"""
import os

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, "Documents", "Claude")

# Corpus scope A (Adam's choice 2026-07-03): KB + blueprints/SOWs + skills + both brains.
# Each root is (label, absolute_path). Label is stored as metadata and shown in citations.
ROOTS = [
    ("kb",           os.path.join(CLAUDE, "Knowledge Base")),
    ("blueprint",    os.path.join(CLAUDE, "Project Blueprints")),
    ("skill",        os.path.join(CLAUDE, "Backups", "skills")),
    # Brains relocated in the 2026-06-25 restructure. The old "Brain" and
    # "The Architect/STA-Brain" folders no longer exist; do NOT point brain-sta at
    # "The Architect/Adam-Work-Brain" - that is a 2-file README-STALE-COPY stub.
    ("brain-personal", os.path.join(CLAUDE, "Adam-Personal-Brain")),
    ("brain-sta",    os.path.join(CLAUDE, "Projects", "STA Projects", "Work Assistant", "Adam-Work-Brain")),
    ("brain-creative", os.path.join(CLAUDE, "Creative Brains")),
]

# Only Markdown for v1. HTML reports / binaries are noise for retrieval.
INCLUDE_EXT = (".md",)

# Path fragments that exclude a file entirely (index hygiene - WS0 found node_modules leaking in).
EXCLUDE_DIRS = (
    os.sep + "node_modules" + os.sep,
    os.sep + ".git" + os.sep,
    os.sep + "dist" + os.sep,
    os.sep + "dist-extension" + os.sep,
    os.sep + "_Archived" + os.sep,
    os.sep + "__pycache__" + os.sep,
    os.sep + ".obsidian" + os.sep,   # Obsidian vault config/workspace - not corpus content
    os.sep + ".trash" + os.sep,      # Obsidian soft-deleted notes (Adam-Work-Brain) - must not re-enter corpus
)
# DIRECTORY name prefixes that prune the directory and its entire subtree.
# "_" covers _to_delete, _staged, _retired, _raw, _Skills, _pre-sync-*, _pre-synthesis-*:
# quarantined, superseded and pre-install content that must never be citable.
# NOTE: this is a DIRECTORY rule only. Underscore-prefixed FILES stay indexed on purpose -
# _known-issues.md, _summary.md, _syllabus.md and _article-index.md are real content, and
# the KB standard has _known-issues.md OUTRANK research modules on behavior it covers.
EXCLUDE_DIR_PREFIXES = ("_",)

# Generated one-liner surfaces - skip so they don't dilute real content.
EXCLUDE_BASENAMES = ("_index.md", "index-lookup.md", "index.md")

# Models (download from HuggingFace on first run; cached after).
EMBED_MODEL = "BAAI/bge-small-en-v1.5"        # 384-dim, CPU-friendly
RERANK_MODEL = "BAAI/bge-reranker-base"        # cross-encoder; optional, auto-skipped if unavailable

# Storage - persistent on-disk Qdrant + a sidecar manifest + BM25 pickle.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index_data")
QDRANT_PATH = os.path.join(DATA_DIR, "qdrant")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")   # path -> content hash (incremental re-index)
BM25_PATH = os.path.join(DATA_DIR, "bm25.pkl")
COLLECTION = "kb"

# Chunking
MAXCHARS = 1200   # recursive fallback split for oversized sections

# Retrieval defaults
DENSE_TOPN = 40   # dense candidates pulled before rerank
SPARSE_TOPN = 20  # sparse candidates added only for exact-token queries
FINAL_K = 6       # results returned after rerank
