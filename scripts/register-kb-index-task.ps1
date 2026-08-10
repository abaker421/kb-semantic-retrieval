<#
.SYNOPSIS
  Register (or re-register) the "KB Semantic Index Nightly" scheduled task.

.DESCRIPTION
  Modeled on C:\Users\Adam\Documents\Claude\Scheduled\register-wake-task.ps1 so it matches
  how the other scheduled tasks on this machine are registered: New-ScheduledTask* cmdlets,
  an Interactive / Limited principal (runs only when the user is logged on, no stored
  password), WakeToRun + StartWhenAvailable, and MultipleInstances IgnoreNew.

  The task runs scripts\kb-index-nightly.ps1 daily at 03:00 local to keep the KB semantic
  index current, so a skipped re-index can no longer silently rot the index.

  Primary action: powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File <nightly>
  Smart App Control was OFF on this machine (VerifiedAndReputablePolicyState = 0) and the
  execution policy permits -ExecutionPolicy Bypass, so this action runs without a fallback.
  If a future machine has SAC ENFORCED and blocks the powershell.exe action, re-run this
  script with -PythonFallback to register a cmd.exe action that calls python.exe directly
  and redirects output to the log (see README.md).

.PARAMETER PythonFallback
  Register a SAC/policy-resilient action: cmd.exe /c "<python> -u kb_index.py >> <log> 2>&1"
  instead of the powershell.exe action. Use only if the primary action is blocked.
#>
param(
    [switch]$PythonFallback
)

$ErrorActionPreference = 'Stop'

$TaskName  = "KB Semantic Index Nightly"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$Nightly   = Join-Path $ScriptDir 'kb-index-nightly.ps1'
$ReportDir = 'C:\Users\Adam\Documents\Claude\reports\system-health\kb-index'
$FallbackLog = Join-Path $ReportDir 'kb-index-nightly.fallback.log'

if (-not (Test-Path $Nightly)) { throw "Nightly script not found: $Nightly" }

# Idempotent: remove any prior registration first (mirrors register-wake-task.ps1).
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch { }

if ($PythonFallback) {
    # SAC/policy-resilient fallback: call python.exe directly via cmd.exe, redirecting to a log.
    $Py = 'C:\Users\Adam\AppData\Local\Programs\Python\Python313\python.exe'
    $null = New-Item -ItemType Directory -Force -Path $ReportDir
    $cmdArgs = '/c ""' + $Py + '" -u "' + (Join-Path $RepoRoot 'kb_index.py') + '" >> "' + $FallbackLog + '" 2>&1"'
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdArgs -WorkingDirectory $RepoRoot
    Write-Output "MODE: python fallback action (cmd.exe -> python.exe, redirect to $FallbackLog)"
} else {
    # Primary action: run the defensive wrapper via powershell.exe.
    $psArg = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $Nightly + '"'
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $psArg
    Write-Output "MODE: primary action (powershell.exe -> kb-index-nightly.ps1)"
}

$trigger = New-ScheduledTaskTrigger -Daily -At "3:00AM"

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries:$false `
    -DontStopIfGoingOnBatteries:$false `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Nightly (03:00) refresh of the KB semantic index via scripts\kb-index-nightly.ps1. Keeps the index current so a skipped re-index cannot silently rot it. Repo: $RepoRoot" |
    Out-Null

# ---- verification summary ----
Write-Output "=== REGISTERED TASK ==="
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, Description | Out-String | Write-Output

$t = Get-ScheduledTask -TaskName $TaskName
Write-Output "=== SETTINGS CHECK ==="
Write-Output ("WakeToRun               : {0}" -f $t.Settings.WakeToRun)
Write-Output ("StartWhenAvailable      : {0}" -f $t.Settings.StartWhenAvailable)
Write-Output ("DisallowStartOnBatteries: {0}" -f $t.Settings.DisallowStartIfOnBatteries)
Write-Output ("ExecutionTimeLimit      : {0}" -f $t.Settings.ExecutionTimeLimit)
Write-Output ("MultipleInstances       : {0}" -f $t.Settings.MultipleInstancesPolicy)
Write-Output ("LogonType               : {0}" -f $t.Principal.LogonType)
Write-Output ("RunLevel                : {0}" -f $t.Principal.RunLevel)
Write-Output ("UserId                  : {0}" -f $t.Principal.UserId)
Write-Output ("Trigger                 : {0}" -f ($t.Triggers | ForEach-Object { $_.StartBoundary }))
Write-Output ("Action.Execute          : {0}" -f ($t.Actions | ForEach-Object { $_.Execute }))
Write-Output ("Action.Arguments        : {0}" -f ($t.Actions | ForEach-Object { $_.Arguments }))

Write-Output "=== NEXT RUN TIME ==="
(Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime | Write-Output
Write-Output "DONE"
