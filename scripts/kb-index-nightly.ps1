<#
.SYNOPSIS
  Nightly refresh of the KB semantic index (kb-semantic-retrieval).

.DESCRIPTION
  Wrapper around kb_index.py, meant to be run by the "KB Semantic Index Nightly"
  scheduled task. It is defensive on purpose: the whole reason this exists is that a
  skipped or silent re-index lets the index rot. So it:

    1. Resolves the repo root from its OWN location (no hardcoded repo path).
    2. Resolves a Python interpreter that actually has fastembed/qdrant-client/rank_bm25.
    3. PRE-FLIGHTS the corpus roots in kb_config.py. If ANY root does not resolve on
       disk, it writes a FAILED status and exits non-zero WITHOUT running the indexer -
       because a rebuild against a dead root indexes nothing while reporting success,
       which is exactly the failure mode this task exists to prevent.
    4. Runs the indexer, capturing stdout+stderr.
    5. Appends a timestamped record to the rolling log (trimmed to 90 days) and writes
       a machine-readable status.json (overwritten each run).
    6. Exits non-zero on any failure so Task Scheduler records it as a failure.

  Log:    C:\Users\Adam\Documents\Claude\reports\system-health\kb-index\kb-index-nightly.log
  Status: C:\Users\Adam\Documents\Claude\reports\system-health\kb-index\status.json
#>

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Paths - resolved from this script's own location, never hardcoded.
# ---------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$Indexer   = Join-Path $RepoRoot 'kb_index.py'
$Manifest  = Join-Path $RepoRoot 'index_data\manifest.json'

$ReportDir  = 'C:\Users\Adam\Documents\Claude\reports\system-health\kb-index'
$LogFile    = Join-Path $ReportDir 'kb-index-nightly.log'
$StatusFile = Join-Path $ReportDir 'status.json'

$null = New-Item -ItemType Directory -Force -Path $ReportDir

$StartTime = Get-Date
$Iso       = $StartTime.ToString('yyyy-MM-ddTHH:mm:sszzz')
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# Accumulates every line we want in the log for this run.
$RunLines = New-Object System.Collections.Generic.List[string]
function Add-Line([string]$s) { $RunLines.Add($s); Write-Host $s }
function Get-Tail([int]$n) {
    $a = $RunLines.ToArray()
    if ($a.Count -le $n) { return [string[]]$a }
    return [string[]]$a[($a.Count - $n)..($a.Count - 1)]
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-StatusJson {
    param(
        [string]$Status, [int]$ExitCode, [double]$DurationSeconds,
        $ChunksIndexed, $FilesChanged, $FilesDeleted, $ManifestEntries,
        [string[]]$ErrorTail
    )
    $tailValue = @()
    if ($Status -eq 'FAILED') { $tailValue = $ErrorTail }
    $obj = [ordered]@{
        last_run_iso     = $Iso
        status           = $Status
        exit_code        = $ExitCode
        duration_seconds = [math]::Round($DurationSeconds, 1)
        chunks_indexed   = $ChunksIndexed
        files_changed    = $FilesChanged
        files_deleted    = $FilesDeleted
        manifest_entries = $ManifestEntries
        error_tail       = $tailValue
    }
    $json = $obj | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($StatusFile, $json, $Utf8NoBom)
}

function Flush-Log {
    # Prefix each line of this run with the run's ISO timestamp (tab-separated),
    # append to the rolling log, then trim to the most recent 90 days so it cannot
    # grow unbounded. All lines of one run share the run timestamp, so a whole run
    # is kept or dropped atomically.
    $stamped = $RunLines | ForEach-Object { "$Iso`t$_" }
    if (Test-Path $LogFile) { $existing = [System.IO.File]::ReadAllLines($LogFile) } else { $existing = @() }
    $all = @($existing) + @($stamped)

    $cutoff = (Get-Date).AddDays(-90)
    $kept = foreach ($line in $all) {
        $ts = ($line -split "`t", 2)[0]
        $d = [ref]([datetime]::MinValue)
        if ([datetime]::TryParse($ts, $d)) {
            if ($d.Value -ge $cutoff) { $line }   # recent enough -> keep
            # else: older than 90 days -> drop
        } else {
            $line   # unparseable (defensive) -> keep so we never silently lose data
        }
    }
    [System.IO.File]::WriteAllLines($LogFile, [string[]]$kept, $Utf8NoBom)
}

function Resolve-Python {
    # Return @{ Exe=<path>; Pre=@(args) } for the first interpreter that can import
    # all three required packages, or $null. Detected on this machine 2026-08-10:
    # python3 is a Microsoft Store stub (unusable); the real 3.13 interpreter is below.
    # -W ignore silences Python's import-time warnings (e.g. fastembed's
    # RequestsDependencyWarning). We also drop $ErrorActionPreference to Continue for the
    # probe: otherwise, under 'Stop', PowerShell 5.1 escalates any native-command stderr
    # line into a terminating NativeCommandError and every candidate gets wrongly skipped.
    $probe = 'import fastembed, qdrant_client, rank_bm25'
    $cands = @(
        @{ Exe = 'C:\Users\Adam\AppData\Local\Programs\Python\Python313\python.exe'; Pre = @() },
        @{ Exe = 'py';     Pre = @('-3') },
        @{ Exe = 'python'; Pre = @() }
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        foreach ($c in $cands) {
            $probeArgs = @($c.Pre + @('-W', 'ignore', '-c', $probe))
            $null = & $c.Exe @probeArgs 2>&1
            if ($LASTEXITCODE -eq 0) { return $c }
        }
    } finally {
        $ErrorActionPreference = $prev
    }
    return $null
}

# ---------------------------------------------------------------------------
# 0. Resolve interpreter
# ---------------------------------------------------------------------------
Add-Line "KB nightly index run starting"
Add-Line "repo root: $RepoRoot"

$Py = Resolve-Python
if ($null -eq $Py) {
    Add-Line "FATAL: no Python interpreter with fastembed/qdrant-client/rank_bm25 found."
    $tail = Get-Tail 20
    Write-StatusJson -Status 'FAILED' -ExitCode 3 -DurationSeconds ((Get-Date)-$StartTime).TotalSeconds `
        -ChunksIndexed $null -FilesChanged $null -FilesDeleted $null -ManifestEntries $null -ErrorTail $tail
    Flush-Log
    exit 3
}
$PyDisplay = ($Py.Exe + ' ' + ($Py.Pre -join ' ')).Trim()
Add-Line "interpreter: $PyDisplay"

# ---------------------------------------------------------------------------
# 1. PRE-FLIGHT the corpus roots. Dead root => FAILED, do NOT run the indexer.
#    Delegated to scripts\kb_preflight.py (a real file, not an inline -c blob:
#    PowerShell 5.1 mangles multi-line strings passed to python -c).
# ---------------------------------------------------------------------------
$Preflight = Join-Path $ScriptDir 'kb_preflight.py'
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'   # don't let python stderr escalate to a terminating error
try {
    $pfArgs = @($Py.Pre + @($Preflight))
    $pfOut = & $Py.Exe @pfArgs 2>&1
    $pfExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
}
Add-Line "--- corpus root pre-flight ---"
foreach ($l in $pfOut) { Add-Line ([string]$l) }

if ($pfExit -ne 0) {
    Add-Line "PRE-FLIGHT FAILED: one or more corpus roots do not resolve. Indexer NOT run."
    $tail = Get-Tail 20
    Write-StatusJson -Status 'FAILED' -ExitCode $pfExit -DurationSeconds ((Get-Date)-$StartTime).TotalSeconds `
        -ChunksIndexed $null -FilesChanged $null -FilesDeleted $null -ManifestEntries $null -ErrorTail $tail
    Flush-Log
    exit $pfExit
}
Add-Line "pre-flight OK: all corpus roots resolve."

# ---------------------------------------------------------------------------
# 2. Run the indexer, capturing stdout + stderr.
# ---------------------------------------------------------------------------
$tmpOut = [System.IO.Path]::GetTempFileName()
$tmpErr = [System.IO.Path]::GetTempFileName()
$idxArgs = @($Py.Pre + @('-u', $Indexer))
Add-Line "running: $PyDisplay -u kb_index.py"

$proc = Start-Process -FilePath $Py.Exe -ArgumentList $idxArgs -WorkingDirectory $RepoRoot `
    -NoNewWindow -Wait -PassThru -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
$idxExit = $proc.ExitCode

$outText = if (Test-Path $tmpOut) { [System.IO.File]::ReadAllText($tmpOut) } else { '' }
$errText = if (Test-Path $tmpErr) { [System.IO.File]::ReadAllText($tmpErr) } else { '' }
Remove-Item $tmpOut, $tmpErr -ErrorAction SilentlyContinue

foreach ($l in ($outText -split "`r?`n")) { if ($l.Trim().Length) { Add-Line $l } }
if ($errText.Trim().Length) {
    Add-Line "--- stderr ---"
    foreach ($l in ($errText -split "`r?`n")) { if ($l.Trim().Length) { Add-Line $l } }
}

# ---------------------------------------------------------------------------
# 3. Parse indexer output + count manifest entries.
# ---------------------------------------------------------------------------
$combined = "$outText`n$errText"
$chunks = $null; $changed = $null; $deleted = $null
if ($combined -match 'files:\s*(\d+)\s*total\s*\|\s*(\d+)\s*new/changed\s*\|\s*(\d+)\s*deleted') {
    $changed = [int]$Matches[2]; $deleted = [int]$Matches[3]
}
if ($combined -match 'done\.\s*(\d+)\s*chunks indexed') {
    $chunks = [int]$Matches[1]
}

$manifestEntries = $null
if (Test-Path $Manifest) {
    try {
        $mArgs = @($Py.Pre + @('-c', "import json,io;print(len(json.load(io.open(r'$Manifest','r',encoding='utf-8'))))"))
        $mOut = & $Py.Exe @mArgs 2>$null
        if ($LASTEXITCODE -eq 0) { $manifestEntries = [int]($mOut | Select-Object -Last 1) }
    } catch { }
}

# ---------------------------------------------------------------------------
# 4. Decide status. OK requires clean exit AND the terminal "done." line.
# ---------------------------------------------------------------------------
$duration = ((Get-Date) - $StartTime).TotalSeconds
if ($idxExit -eq 0 -and $null -ne $chunks) {
    Add-Line "RESULT: OK  (exit=$idxExit, chunks=$chunks, changed=$changed, deleted=$deleted, manifest=$manifestEntries, ${duration}s)"
    Write-StatusJson -Status 'OK' -ExitCode $idxExit -DurationSeconds $duration `
        -ChunksIndexed $chunks -FilesChanged $changed -FilesDeleted $deleted -ManifestEntries $manifestEntries -ErrorTail @()
    Flush-Log
    exit 0
} else {
    Add-Line "RESULT: FAILED (exit=$idxExit, done-line seen=$($null -ne $chunks))"
    $tail = Get-Tail 20
    $exitForStatus = if ($idxExit -ne 0) { $idxExit } else { 1 }
    Write-StatusJson -Status 'FAILED' -ExitCode $exitForStatus -DurationSeconds $duration `
        -ChunksIndexed $chunks -FilesChanged $changed -FilesDeleted $deleted -ManifestEntries $manifestEntries -ErrorTail $tail
    Flush-Log
    exit $exitForStatus
}
