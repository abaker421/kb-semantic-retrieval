# kb-mcp Exclusion List - Sign-Off Sheet
*Drafted 2026-06-24 for Adam's sign-off · a build-time gate: this must be signed before the sta-server is built and the first staff assistant key is issued. NOT urgent today - the server is approved but NOT yet built, and everything is still local on Adam's PC (no staff keys exist). Corrected 2026-06-25: an earlier draft wrongly called the server "released."*

## Why this exists
When built, the kb-mcp server will serve `Knowledge Base/sta/` to staff assistants. Exclusion is enforced twice: the sync job's `rsync --exclude` (mount-level) and `server.py` `EXCLUDE_FILE` (defense-in-depth, prefix match on paths relative to `sta/`). **Anything not excluded will be served on the first staff key.** The current `kb-exclusions.txt` lists only 3 entries against ~90 `sta/` topics, so the real risk is *under*-exclusion. This sheet enumerates the full scope so the gap is a decision, not an oversight. The leak risk is not live now (no server, no keys); it goes live the moment the server is built, which is why this is signed as part of the build, not before it exists.

## ⚠ VERIFIED BUG - fix before sign-off
`kb-exclusions.txt` line for pricing strategy reads `sales-enablement/b2b-public-sector-quote-and-pricing-strategy`, but the topic actually lives at **`sales-marketing/b2b-public-sector-quote-and-pricing-strategy`**. The exclusion path does not match the real path, so `is_excluded()` returns false and **pricing strategy would be served despite being on the exclude list.** Correct the prefix to `sales-marketing/...` (the Claude Code prompt does this).

## Tier 1 - EXCLUDE, confirmed (already on the list)
- `sta-org/salesforce-org-schema` - internal Salesforce object/field map. Confidential.
- `sta-org/leadership-transition-and-team-health` - people/leadership-sensitive. Confidential.

## Tier 2 - RECOMMEND EXCLUDE, your call (my read; check the box to confirm)
- [ ] `sales-marketing/b2b-public-sector-quote-and-pricing-strategy` - pricing/quote strategy. Already default-excluded in intent; **fix the path (above) or it leaks.** Include only if sales assistants genuinely need it.
- [ ] `product-vendor-evaluation-briefings` - internal vendor/competitor evaluations; likely contains positioning you would not hand a vendor or a new staffer's assistant.
- [ ] `k12-attendance-technology-competitive-landscape` - competitive intel on attendance rivals. Market research, but reads as internal sales strategy.
- [ ] `security/salesforce-security-and-event-monitoring` - EXCLUDE **only if** it documents STA's actual SF security config (vs generic how-to). Check the module; config = exclude, generic = fine.
- [ ] `security/google-admin-console-security-audit` - same test: STA's real admin/security posture = exclude; generic audit method = fine.

## Tier 3 - SAFE to serve (my read - everything else)
General professional + product knowledge with no STA secrets: all of `ai-platform/`, `k12-education/`, `web-dev/`, `school-tech/` (your own help/product content), `salesforce/` flows, `it-administration/`, `it-support/`, `google-workspace/`, `github/`, `slack/`, `tools/`, `training-design/`, `podcast/`, `marketing/`, `sales-enablement/` (coaching/personas), most of `sales-marketing/` (methodology, email, CS/retention), `security/` framework topics (`cis-controls-v81`, `k12-cybersecurity-threat-landscape`, `password-manager-selection`, `ai-agent-access-control-and-governance`), `sta-org/sta-company-profile`, `sta-org/k12sta-web-content-archive` (public site content), and the standalone topics (`ada-title-ii-...`, `unistyle-seo-...`, `report-design-for-humans-html`, `k12-attendance-buyer-psychology`, `k12-attendance-policy-and-funding-catalysts`).

→ **Note:** `k12-attendance-buyer-psychology` is a judgment call - it is buyer-psychology research, not a secret, but if you treat your buyer-psychology playbook as proprietary, move it to Tier 2.

## Sign-off block
- [ ] Path bug fixed (`sales-enablement/` → `sales-marketing/`)
- [ ] Tier 2 decisions made (check each above)
- [ ] Two security modules eyeballed for STA-specific config
- [ ] `kb-exclusions.txt` updated to match these decisions
- [ ] **Adam signs:** ______________________  Date: __________
- [ ] Only after all boxes: issue the first staff key.

*This is a sign-off, not a build. Nothing here was changed in kb-exclusions.txt - the Claude Code prompt applies the path fix and any Tier 2 additions you check.*
<!-- EOF -->
