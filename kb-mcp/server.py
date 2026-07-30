"""STA Shared Brain - kb-mcp service (v0 draft, pre-WS3).

Streamable-HTTP MCP server over the work-scope knowledge folders.
Mirrors the WS0 spike's proven JSON-RPC handling (worker.js) - deliberately
framework-light because the MCP spec is volatile (2026-07-28 RC pending).

Auth (per WS0 verdict 2026-06-12): per-person key in the connector URL
(?key=...), Bearer header also accepted for non-Claude clients. A request
with no/bad key gets 401. Keys live in TOKENS_FILE, one "token,name" per line.

Logging: one line per request, key ALWAYS redacted (SOW v1.2 requirement).

Exclusion enforcement is primarily mount-level (the sync job rsyncs the repo
to a serving copy MINUS excluded folders - see README-deploy.md). EXCLUDE_FILE
adds defense-in-depth: any listed relative prefix is refused even if present.
"""

import json
import os
import re
import time
from pathlib import Path

from kb_bm25 import KbIndex
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

KB_ROOT = Path(os.environ.get("KB_ROOT", "/kb")).resolve()
CONTEXT_ROOT = Path(os.environ.get("CONTEXT_ROOT", "/context")).resolve()
TOKENS_FILE = os.environ.get("TOKENS_FILE", "/run/secrets/kb_tokens")
EXCLUDE_FILE = os.environ.get("EXCLUDE_FILE", "")  # optional, one rel-path prefix per line
MAX_FETCH_BYTES = int(os.environ.get("MAX_FETCH_BYTES", "200000"))
PROTOCOL_FALLBACK = "2025-06-18"


def load_tokens() -> dict:
    tokens = {}
    try:
        for line in Path(TOKENS_FILE).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "," not in line:
                continue
            token, name = line.split(",", 1)
            tokens[token.strip()] = name.strip()
    except FileNotFoundError:
        pass
    return tokens


def load_excludes() -> list:
    if not EXCLUDE_FILE:
        return []
    try:
        return [
            l.strip().strip("/")
            for l in Path(EXCLUDE_FILE).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
    except FileNotFoundError:
        return []


EXCLUDES = load_excludes()


def is_excluded(rel: str) -> bool:
    rel = rel.replace("\\", "/").strip("/")
    return any(rel == e or rel.startswith(e + "/") for e in EXCLUDES)


def authed_user(request: Request):
    """Return the person name for a valid key, else None. Never log the key."""
    tokens = load_tokens()  # re-read each call: revocation = delete a line, no restart needed
    key = request.query_params.get("key", "")
    if key and key in tokens:
        return tokens[key]
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and auth[7:] in tokens:
        return tokens[auth[7:]]
    return None


def log_line(person: str, what: str):
    # SOW v1.2: the key param must never appear in logs. Only person + action.
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} kb-mcp {person} {what}", flush=True)


def safe_resolve(root: Path, rel: str):
    """Resolve rel under root; refuse traversal, symlink escape, and excluded paths."""
    candidate = (root / rel.replace("\\", "/").lstrip("/")).resolve()
    if not str(candidate).startswith(str(root) + os.sep) and candidate != root:
        return None
    if root == KB_ROOT and is_excluded(str(candidate.relative_to(root))):
        return None
    return candidate


# ---------------------------------------------------------------- tools

def first_heading(text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


# BM25 engine (kb_bm25.KbIndex) built once per process, over whatever this
# service mounts at KB_ROOT. The mount already enforces scope (sta/ only on the
# server, via the rsync exclusion filter - see README-deploy.md); is_excluded is
# passed for defense-in-depth. The index self-refreshes on file-set/mtime change
# inside search(), so a doc edited between calls is reflected on the next call.
_KB_INDEX = None


def kb_index() -> KbIndex:
    global _KB_INDEX
    if _KB_INDEX is None:
        _KB_INDEX = KbIndex(str(KB_ROOT), is_excluded=is_excluded)
    return _KB_INDEX


def tool_kb_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Empty query - give me search terms."
    # Reference caps at 10; keep `limit` as an optional, backward-compatible
    # extra (the tool contract is kb_search(query)) but never exceed 10.
    limit = max(1, min(int(args.get("limit") or 10), 10))
    return kb_index().search_text(query, top=limit)


def tool_kb_fetch(args: dict) -> str:
    rel = (args.get("path") or "").strip()
    target = safe_resolve(KB_ROOT, rel) if rel else None
    if target is None or not target.is_file() or target.suffix.lower() not in (".md", ".txt"):
        return f"Not available: '{rel}'. Use a path exactly as returned by kb_search."
    data = target.read_bytes()
    clipped = len(data) > MAX_FETCH_BYTES
    text = data[:MAX_FETCH_BYTES].decode("utf-8", errors="replace")
    note = f"\n\n[clipped at {MAX_FETCH_BYTES} bytes - ask for a specific section]" if clipped else ""
    return f"# Source: {rel}\n\n{text}{note}"


def tool_context_get(args: dict) -> str:
    name = (args.get("name") or "").strip()
    if not CONTEXT_ROOT.is_dir():
        return "No shared-context folder is mounted on this server."
    if not name:
        files = sorted(p.name for p in CONTEXT_ROOT.glob("*.md"))
        return "Shared context files (call context_get with a name):\n" + "\n".join(f"- {f}" for f in files)
    target = safe_resolve(CONTEXT_ROOT, name)
    if target is None or not target.is_file():
        return f"No shared context file named '{name}'. Call context_get with no name to list them."
    return f"# Source: shared-context/{name}\n\n{target.read_text(encoding='utf-8', errors='replace')}"


TOOLS = [
    {
        "name": "kb_search",
        "description": "Search STA's company knowledge base (product docs, troubleshooting, "
                       "implementation workflows, research) by meaning-adjacent BM25 ranking. "
                       "Returns up to 10 ranked hits (score, module slug, path:line, heading, "
                       "snippet); follow up with kb_fetch + the path for full text.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "search terms"}},
            "required": ["query"]},
    },
    {
        "name": "kb_fetch",
        "description": "Fetch the full text of one knowledge-base document by the path kb_search returned.",
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "relative path from kb_search results"}},
            "required": ["path"]},
    },
    {
        "name": "context_get",
        "description": "List or fetch STA shared context files (company profile, team roster, "
                       "product how-tos). Call with no name to list; with a name to fetch.",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "context filename, e.g. sta-company-profile.md"}},
            "required": []},
    },
]

TOOL_FUNCS = {"kb_search": tool_kb_search, "kb_fetch": tool_kb_fetch, "context_get": tool_context_get}


# ---------------------------------------------------------------- JSON-RPC

def rpc_result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def rpc_error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


async def mcp_endpoint(request: Request):
    person = authed_user(request)
    if person is None:
        # 401 makes Claude attempt OAuth (WS0 Test A) - that is fine for an
        # UNkeyed URL: it fails loudly instead of silently serving anonymous.
        return JSONResponse({"error": "unauthorized - connector URL must include ?key=<your key>"}, status_code=401)

    if request.method == "GET":
        return Response(status_code=405)  # no SSE stream in v0

    try:
        msg = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(rpc_error(None, -32700, "parse error"), status_code=400)

    if msg.get("id") is None:
        return Response(status_code=202)  # notification

    method = msg.get("method", "")
    if method == "initialize":
        proto = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_FALLBACK
        log_line(person, "initialize")
        return JSONResponse(rpc_result(msg["id"], {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sta-knowledge", "version": "0.1.0"},
        }))
    if method == "ping":
        return JSONResponse(rpc_result(msg["id"], {}))
    if method == "tools/list":
        log_line(person, "tools/list")
        return JSONResponse(rpc_result(msg["id"], {"tools": TOOLS}))
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        func = TOOL_FUNCS.get(name)
        if func is None:
            return JSONResponse(rpc_error(msg["id"], -32602, f"unknown tool: {name}"))
        log_line(person, f"tools/call {name}")
        try:
            text = func(params.get("arguments") or {})
        except Exception as exc:  # never leak a stack trace to the client
            log_line(person, f"ERROR {name}: {type(exc).__name__}")
            text = f"Tool '{name}' hit an internal error. Tell Adam - the server log has details."
        return JSONResponse(rpc_result(msg["id"], {"content": [{"type": "text", "text": text}]}))
    return JSONResponse(rpc_error(msg["id"], -32601, f"method not found: {method}"))


app = Starlette(routes=[Route("/mcp", mcp_endpoint, methods=["GET", "POST", "OPTIONS"])])

if __name__ == "__main__":
    import uvicorn
    # access_log=False: uvicorn's access log would print full URLs including
    # the key param. Our own log_line() covers auditing, key-free. (SOW v1.2)
    uvicorn.run(app, host="0.0.0.0", port=8787, access_log=False)
# EOF
