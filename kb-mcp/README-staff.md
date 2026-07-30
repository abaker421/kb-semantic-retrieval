# Connect Your Assistant to STA Knowledge (~5 minutes)

Your AI assistant can answer from STA's live company knowledge - product docs, troubleshooting
guides, how-tos - instead of an old snapshot. One-time setup:

1. **Find your personal access link** in your welcome note. It looks like:
   `https://kb.k12sta.com/mcp?key=sta-kb-xxxxxxxx` - the key is yours alone; don't share it.
2. Open **Claude desktop → Settings → Connectors → Add custom connector**.
3. Name: `STA Knowledge`. URL: paste your full access link (including the `?key=` part). Add.
4. Toggle **STA Knowledge on** in your project's connector list.
5. Paste this line into your project instructions:
   > Before answering any question about STA products, customers, policies, or company facts,
   > search the STA Knowledge connector and prefer its content over memory.
6. **Verify:** ask your assistant *"Search STA Knowledge for TT10 time clock specs."*
   A working setup returns specs naming the source document.

Troubleshooting: connector missing from the project = toggle it on in project settings.
"Unauthorized" = your link is missing the `?key=` part, or your key was reset - ask Adam.
Searches return nothing = tell Adam (the content sync needs a kick; your setup is fine).

<!-- EOF -->
