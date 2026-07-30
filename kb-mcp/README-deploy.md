# kb-mcp - Deploy Runbook (v0 draft; finalize during WS3 Phase 1)

What this is: the STA Shared Brain knowledge service. Serves kb_search / kb_fetch / context_get
over Streamable HTTP MCP at `https://kb.k12sta.com/mcp`, per-person URL keys (WS0-verified pattern).

## Files in this folder

| File | Purpose |
|---|---|
| `server.py` | The whole service (Starlette, stdlib JSON-RPC mirroring the WS0 stub) |
| `Dockerfile` | python:3.12-slim + starlette/uvicorn |
| `docker-compose.snippet.yml` | Paste into `/srv/stack/docker-compose.yml`; includes the Caddy routes |
| `kb_tokens.example` | Token file format; real file at `/srv/stack/secrets/kb_tokens`, chmod 600, never in git |
| `kb-exclusions.txt` | The SOW Section 10 exclusion list - used by sync AND server |
| `README-staff.md` | The Part B connect guide that ships in every assistant package |

## Deploy (server, once - WS3 Phase 1)

1. Copy this folder to `/srv/stack/kb-mcp/` on the server.
2. Create `/srv/stack/secrets/kb_tokens` from the example (Adam + Tyler keys first). `chmod 600`.
3. **Sync job (the mount-level exclusion guarantee)** - n8n schedule, every 15 min:

   ```bash
   cd /srv/stack/kb-repo && git pull --quiet
   rsync -a --delete \
     --exclude-from=/srv/stack/kb-mcp/kb-exclusions.txt \
     /srv/stack/kb-repo/Knowledge Base/sta/ /srv/stack/kb-serve/Knowledge Base/sta/
   rsync -a --delete \
     /srv/stack/kb-repo/context-files/shared/ /srv/stack/kb-serve/context-files/shared/
   ```

   The container mounts `kb-serve` (the filtered copy), never `kb-repo`. Excluded folders
   physically do not exist in the serving tree.
4. Merge `docker-compose.snippet.yml` into the stack compose; add the Caddyfile routes.
5. `docker compose up -d --build kb-mcp`
6. Test with MCP Inspector against `https://kb.k12sta.com/mcp?key=<adam's key>`, then connect
   Adam's Cowork as pilot user zero (URL-with-key, per WS0).

## Exclusion-gate test (REQUIRED before any staff key - SOW acceptance criterion)

With a staff key: `kb_fetch` on `sta-org/salesforce-org-schema/module-01-*.md` MUST return
"Not available", and `kb_search` for "plaintext credentials Case" MUST return no org-schema hits.
Run both. Record the result in the SOW changelog.

## Key issuance / revocation

- Issue: generate (`python3 -c "import secrets; print('sta-kb-' + secrets.token_urlsafe(18))"`),
  append `token,name` to the secrets file, send the person their full connector URL.
- Revoke: delete their line. Takes effect on their next request - no restart (file is re-read
  per call; corpus and team are small, this is deliberate simplicity over caching).

## Log redaction (SOW v1.2 hard requirement)

- uvicorn runs with `access_log=False` (full URLs would contain keys).
- `server.py` logs `timestamp person action` only. Caddy's log for kb.k12sta.com, if enabled,
  must strip query strings (`log { format filter { request>uri query delete key } }`) - or leave
  Caddy logging off for this site.

## Known v0 limits (revisit in WS3 Phase 3)

- Search is a live scan (fine at ~hundreds of .md files; index it if the corpus grows 10x).
- No SSE stream (GET returns 405) - matches the WS0 stub Claude accepted.
- MCP spec RC 2026-07-28: re-verify connector behavior at staff rollout (SOW Section 6).

## Status (2026-07-30)

The WS0 canned-stub `kb_search` (Cloudflare Worker returning a fixed TT10 result) was
replaced with a real stdlib-only BM25 engine (`kb_bm25.py`), ported from the proven
`Knowledge Base/kb-search.py`: tokenizer + suffix-stemmer, structural heading chunking,
BM25 (k1=1.5, b=0.75), self-refreshing in-memory index, cap 10, LOW CONFIDENCE fallback.
`server.py`'s `tool_kb_search` now calls it; the tool contract stays `kb_search(query)`.
Smoke-tested LOCALLY on Adam's PC on 2026-07-30 (full KB, both scopes, `kb-exclusions.txt`
applied; the three golden queries return real ranked hits over authed JSON-RPC from an
outside process). **NOT deployed.** The designed target — this runbook — is the STA
Lightsail server at `/srv/stack/kb-mcp/` behind Caddy at `https://kb.k12sta.com/mcp`,
which is **not yet provisioned**; there is nothing to deploy to. A cloudflared named-tunnel
interim was explored and **explicitly rejected as off-architecture** (kb.k12sta.com is a
plain A-record to the Lightsail box; neither k12sta.com nor buildwithbaker.io is a
Cloudflare zone, so no named tunnel is possible or wanted). Runnable code now lives in
`source/repos/kb-semantic-retrieval/kb-mcp/`; deploy here when the Lightsail host exists.

<!-- EOF -->
