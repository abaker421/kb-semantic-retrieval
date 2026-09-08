"""Shared helpers: file walk, structural chunking, tokenizer, hashing."""
import os, re, hashlib
import kb_config as C


def tok(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def file_hash(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def _count_md(root):
    """.md files in a subtree we are about to prune (for the pruned-dir log)."""
    n = 0
    for _, _, files in os.walk(root):
        n += sum(1 for f in files if f.endswith(C.INCLUDE_EXT))
    return n


def iter_files(pruned_dirs=None):
    """Yield (label, abspath) for every included Markdown file across all roots.

    Directories whose basename starts with any C.EXCLUDE_DIR_PREFIXES entry are pruned
    along with their whole subtree, so quarantined/superseded content cannot be cited -
    UNLESS the basename is in C.INCLUDE_DIR_NAMES, the explicit allow-list of live
    underscore folders. This is deliberately a DIRECTORY-only test: underscore-prefixed
    FILES are still indexed (see the note on EXCLUDE_DIR_PREFIXES in kb_config.py).

    pruned_dirs: optional dict, populated as {directory basename: .md files skipped}.
    The allow-list is a single place that can go stale, so callers pass this in and log
    it - a newly created live underscore folder then shows up in the run output instead
    of vanishing silently.
    """
    for label, root in C.ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            # prune in place so os.walk never descends into the excluded subtree
            keep = []
            for d in dirs:
                if d.startswith(C.EXCLUDE_DIR_PREFIXES) and d not in C.INCLUDE_DIR_NAMES:
                    if pruned_dirs is not None:
                        pruned_dirs[d] = pruned_dirs.get(d, 0) + _count_md(os.path.join(dirpath, d))
                    continue
                keep.append(d)
            dirs[:] = keep
            for name in files:
                if not name.endswith(C.INCLUDE_EXT):
                    continue
                if name in C.EXCLUDE_BASENAMES:
                    continue
                full = os.path.join(dirpath, name)
                norm = os.sep + os.path.relpath(full, root) + os.sep
                if any(frag in (os.sep + full + os.sep) for frag in C.EXCLUDE_DIRS):
                    continue
                yield label, full


def chunk_markdown(text, path, label):
    """Structural chunking on headings, recursive fallback for oversized sections,
    contextual header prepended to each chunk's embed text (KB module-01 / Anthropic 2024)."""
    title = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"^#\s+(.+)$", text, re.M)
    if m:
        title = m.group(1).strip()
    chunks, cur_head, buf = [], title, []

    def flush():
        if not buf:
            return
        body = "\n".join(buf).strip()
        if not body:
            return
        pieces = [body]
        if len(body) > C.MAXCHARS:
            pieces, cur = [], ""
            for p in body.split("\n\n"):
                if len(cur) + len(p) > C.MAXCHARS and cur:
                    pieces.append(cur); cur = p
                else:
                    cur = (cur + "\n\n" + p).strip()
            if cur:
                pieces.append(cur)
        for idx, pc in enumerate(pieces):
            ctx = f"[{label}: {title} > {cur_head}]"
            chunks.append({
                "path": path, "label": label, "title": title,
                "head": cur_head, "text": pc, "embed_text": ctx + "\n" + pc,
            })

    for line in text.splitlines():
        h = re.match(r"^(#{1,4})\s+(.+)$", line)
        if h:
            flush(); buf = []; cur_head = h.group(2).strip()
        else:
            buf.append(line)
    flush()
    return chunks
