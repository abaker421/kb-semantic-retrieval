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
# "_" covers _to_delete, _staged, _retired, _raw, _Skills, _pre-sync-*, _pre-synthesis-*,
# _pre-edit-*, _pre-survey-*: quarantined and superseded content that must never be citable.
# Not everything it catches is quarantine, though - Backups\skills\_install-state is a LIVE
# skill state store that simply holds no .md today, so excluding it currently costs nothing.
# If it ever gains .md files they will vanish silently, and the pruned-dir log kb_index.py
# prints is the only place that would show it.
# NOTE: this is a DIRECTORY rule only. Underscore-prefixed FILES stay indexed on purpose -
# _known-issues.md, _summary.md, _syllabus.md and _article-index.md are real content, and
# the KB standard has _known-issues.md OUTRANK research modules on behavior it covers.
EXCLUDE_DIR_PREFIXES = ("_",)

# THE EXCEPTION to EXCLUDE_DIR_PREFIXES. Exact directory BASENAMES that survive the
# prefix rule and get indexed. The rule, plainly:
#   1. An underscore-prefixed directory is EXCLUDED by default.
#   2. This list is the only way one gets back in - inclusion is a deliberate act.
#   3. So a NEWLY CREATED live underscore folder is silently excluded until someone
#      adds it here. The pruned-directory log kb_index.py prints on every run is how
#      you notice: a new name appearing in that log is the signal to come edit this list.
# Chosen over a deny-list of quarantine names on purpose - a deny-list fails toward
# INDEXED, so every new quarantine folder leaks until a human remembers it. This fails
# toward excluded.
# These are live reference content, not superseded material:
#   _Apps                 - the SOWs, incl. this repo's own scope document the README cites
#   _Claude-Projects      - per-project working context
#   _Research-Commissions - deep-research deliverables
#   _System               - capture.md / log.md / what-goes-where.md; the brains' routing
#                           docs, so excluding them breaks brain navigation
#   _Templates            - authoring templates
#   _prompts              - the fixed save location for deep-research commission prompts
# EXCLUDE_DIRS still wins over this list (it is checked per-file, after the walk), so
# _Archived stays excluded even if it were ever added here.
#
# Allow-listing a parent does NOT un-prune its underscore children. Every directory name is
# re-tested at its own level of the walk, so an underscore folder nested inside an allow-listed
# one is still pruned and still shows up in the pruned-dir log. That is load-bearing, not
# incidental: _Claude-Projects\behind-the-bell-assistant\_pre-edit-2026-09-02 holds a superseded
# snapshot of a LIVE context file, and if the child were inherited-in it would compete with the
# current file in search results. Verified 2026-09-08: parent 131 entries, child 0, and the live
# context-sta-company-proj.md ranks 1 while no PRE-EDIT path appears at all. Keep it that way.
#
# TRAP for whoever later adds a root for the real deep-research prompt folder
# (Projects\STA Projects\Deep Research\_prompts, ~126 .md, outside ROOTS today): that root's own
# basename is "_prompts". The prefix test must apply only to subdirectories DURING the walk, as
# it does now - os.walk yields the root itself in dirpath and never in dirs, so the root escapes
# the test. An implementation that also tested the root's basename would prune the entire new
# root, index nothing from it, and still exit 0 with a green run.
INCLUDE_DIR_NAMES = (
    "_Apps",
    "_Claude-Projects",
    "_Research-Commissions",
    "_System",
    "_Templates",
    # Expected to contribute 0 files, deliberately kept: the real ~126-file prompt folder is
    # outside ROOTS (see the TRAP note above), and the only in-scope _prompts holds no .md.
    # Listed so that adding the root is the only remaining step, not two separate discoveries.
    "_prompts",
)

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
