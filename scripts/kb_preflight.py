"""
Corpus-root pre-flight for the nightly indexer.

Prints one line per root in kb_config.ROOTS ("OK  " or "DEAD" + tab + label + tab + path)
and exits non-zero (2) if ANY root does not resolve on disk. The nightly wrapper refuses to
run kb_index.py when this fails, because a rebuild against a dead root indexes nothing while
reporting success - the exact silent-rot failure the scheduled task exists to prevent.

Self-locating: adds the repo root (parent of this script's dir) to sys.path so it imports
kb_config regardless of the current working directory.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kb_config as C

dead = []
for label, root in C.ROOTS:
    ok = os.path.isdir(root)
    print(("OK  " if ok else "DEAD") + "\t" + label + "\t" + root)
    if not ok:
        dead.append(label)

sys.exit(2 if dead else 0)
