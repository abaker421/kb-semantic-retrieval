# scripts/ — nightly index maintenance

These scripts keep the KB semantic index current automatically, so a skipped manual
re-index can no longer let the index silently rot. Windows Task Scheduler runs the indexer
nightly; a failed run surfaces on its own instead of compounding for weeks.

## What runs

| File | Role |
|---|---|
| `kb-index-nightly.ps1` | The defensive wrapper the scheduled task runs each night. Resolves the repo from its own path, resolves a Python interpreter that has the deps, **pre-flights the corpus roots**, runs `kb_index.py`, writes a log + status file, and exits non-zero on any failure. |
| `kb_preflight.py` | Helper called by the wrapper: prints each `kb_config.ROOTS` entry as `OK`/`DEAD` and exits non-zero if any root does not resolve on disk. |
| `register-kb-index-task.ps1` | Registers (or re-registers) the `KB Semantic Index Nightly` scheduled task. Idempotent. Modeled on `Documents\Claude\Scheduled\register-wake-task.ps1`. |

### Why the pre-flight matters

A rebuild against a **dead corpus root** indexes nothing while reporting success — that is
exactly the failure this task exists to prevent (it is how the index went 36 days stale). So
if any root in `kb_config.py` does not resolve, the wrapper writes a `FAILED` status and exits
non-zero **without running the indexer** at all.

## The scheduled task

- **Name:** `KB Semantic Index Nightly`
- **When:** daily at **03:00** local (America/Chicago), wakes the PC, catches up a missed run
- **Runs as:** the logged-on user, Interactive / Limited — **no stored password** (so a run is
  skipped only if nobody is logged on at 03:00; the missed-run catch-up covers that)
- **Guards:** stops if it runs longer than 2 hours; will not start a second instance if one is
  already running
- **Action:** `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "<repo>\scripts\kb-index-nightly.ps1"`

Register it:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\register-kb-index-task.ps1"
```

Smart App Control was **OFF** on this machine and the execution policy allows `-ExecutionPolicy
Bypass`, so the `powershell.exe` action runs directly. If a future machine has **SAC enforced**
and blocks that action, re-register with the resilient fallback (a `cmd.exe` action that calls
`python.exe` directly and redirects output to a log):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\register-kb-index-task.ps1" -PythonFallback
```

## Where the log and status live

Both under `C:\Users\Adam\Documents\Claude\reports\system-health\kb-index\`:

- **`kb-index-nightly.log`** — every run, one ISO-8601-timestamped, tab-separated line per
  output line. Trimmed to the most recent **90 days** each run so it cannot grow unbounded.
- **`status.json`** — overwritten each run. Fields:
  `last_run_iso`, `status` (`OK`|`FAILED`), `exit_code`, `duration_seconds`,
  `chunks_indexed`, `files_changed`, `files_deleted`, `manifest_entries`, and `error_tail`
  (last 20 output lines, populated only when `status` is `FAILED`).

> Note: nothing reads `status.json` automatically yet. The Monday System Monitor does **not**
> read `reports\system-health\`. Getting a failed run in front of a human within a day needs a
> small follow-up (see the PR that added these scripts).

## Interpreter

Detected on this machine (2026-08-10): `python3` is a Microsoft Store stub and unusable; the
real interpreter with `fastembed` / `qdrant-client` / `rank_bm25` is
`C:\Users\Adam\AppData\Local\Programs\Python\Python313\python.exe`. The wrapper resolves it
automatically (that path first, then `py -3`, then `python`), so a Python upgrade that moves the
path still works as long as one candidate has the deps.

## How to unregister

```powershell
Unregister-ScheduledTask -TaskName "KB Semantic Index Nightly" -Confirm:$false
```

This removes only the schedule. It does not touch the index, the repo, or the log/status files.
Re-run `register-kb-index-task.ps1` to recreate it.
