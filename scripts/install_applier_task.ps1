<#
.SYNOPSIS
  Register (or remove) a Windows Scheduled Task that runs the proposal applier
  on an interval.

.DESCRIPTION
  The applier reads APPROVED proposals from the vault's '00 - Proposals/' queue
  and applies them. It holds vault write access and is deliberately a SEPARATE
  process from the Hermes gateway (which runs the locked-down agent): the agent
  never holds write creds, the applier does. That trust separation is why this
  is an OS scheduled task, not a `hermes cron` job running inside the gateway.

  Approval is the Obsidian status-flip: you set `status: approved` on a
  proposal, and the next sweep applies it. Interval = approval latency.

  Idempotent: re-running re-registers the task. Run from the checkout whose
  agent venv holds the applier (i.e. after this branch is on main and you have
  run `uv sync --project agent`), so the task points at a stable path — not a
  temporary worktree.

.EXAMPLE
  pwsh scripts/install_applier_task.ps1 -VaultRoot "C:\Users\taylor\Documents\Taylor Notes"

.EXAMPLE
  pwsh scripts/install_applier_task.ps1 -Uninstall
#>
param(
  [string]$VaultRoot,
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [int]$IntervalMinutes = 10,
  [string]$TaskName = "PA-ApplyProposals",
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed scheduled task '$TaskName'."
  return
}

if (-not $VaultRoot) { throw "-VaultRoot is required (the Obsidian vault root)." }
if (-not (Test-Path $VaultRoot)) { throw "VaultRoot not found: $VaultRoot" }

$exe = Join-Path $RepoRoot "agent\.venv\Scripts\apply-proposals.exe"
if (-not (Test-Path $exe)) {
  throw "Applier not installed at $exe. Run 'uv sync --project agent' in $RepoRoot first."
}

$action = New-ScheduledTaskAction -Execute $exe -Argument ('--vault-root "{0}"' -f $VaultRoot)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
  -RepetitionDuration ([TimeSpan]::FromDays(3650))
# IgnoreNew: never overlap two sweeps. StartWhenAvailable: catch up after sleep.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
# A per-user task that runs as the current user does NOT require admin. Catch
# the failure and explain rather than letting a raw access-denied surface.
try {
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Applies approved proposals from the PA vault queue every $IntervalMinutes min." | Out-Null
} catch {
  Write-Error ("Failed to register '{0}': {1}" -f $TaskName, $_.Exception.Message)
  Write-Host "If this was access-denied, retry from an elevated PowerShell."
  exit 1
}

Write-Host "Registered '$TaskName': every $IntervalMinutes min"
Write-Host "  $exe --vault-root `"$VaultRoot`""
Write-Host "Verify:   Get-ScheduledTask -TaskName $TaskName"
Write-Host "Run now:  Start-ScheduledTask -TaskName $TaskName"
