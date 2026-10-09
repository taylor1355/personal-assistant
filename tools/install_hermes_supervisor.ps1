<#
.SYNOPSIS
    Install / uninstall / check the Hermes gateway crash-restart supervisor (PA-104).

.DESCRIPTION
    Registers tools\hermes_gateway_supervisor.py to run at logon under pythonw
    (no console window), so the gateway self-heals when it crashes mid-session
    instead of staying down until the next login.

    RUN MANUALLY, as a separate user-approved step. Nothing here executes as a
    side effect of building the repo, and the /work worker that authored this
    script never runs it. You invoke it yourself:

        powershell -ExecutionPolicy Bypass -File tools\install_hermes_supervisor.ps1
        powershell -ExecutionPolicy Bypass -File tools\install_hermes_supervisor.ps1 -Check
        powershell -ExecutionPolicy Bypass -File tools\install_hermes_supervisor.ps1 -Uninstall

    Default method is an at-logon Scheduled Task (no admin required, LIMITED run
    level). Use -Method Startup to instead drop a hidden-window launcher into the
    Startup folder.

.PARAMETER Method
    Task (default) - register the "HermesGatewaySupervisor" scheduled task.
    Startup       - write a hidden-window .vbs launcher into the Startup folder.

.PARAMETER Check
    Report install state and resolved interpreter, change nothing.

.PARAMETER Uninstall
    Remove the scheduled task and/or the Startup-folder launcher.

.NOTES
    No admin rights required. The scheduled task runs at the current user's
    logon with LIMITED privileges.
#>

[CmdletBinding()]
param(
    [ValidateSet("Task", "Startup")]
    [string]$Method = "Task",
    [switch]$Check,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$TaskName = "HermesGatewaySupervisor"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SupervisorScript = Join-Path $RepoRoot "tools\hermes_gateway_supervisor.py"
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupLauncher = Join-Path $StartupDir "HermesGatewaySupervisor.vbs"

function Resolve-Pythonw {
    <#
      Resolve a pythonw.exe interpreter, in priority order:
        1. `uv python find` (the canonical uv-managed cpython)
        2. %APPDATA%\uv\python\cpython-3.11-*\pythonw.exe
        3. this repo's agent\.venv\Scripts\pythonw.exe
      Returns $null if none found.
    #>
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        try {
            $found = & uv python find 2>$null | Select-Object -First 1
            if ($found) {
                $candidate = Join-Path (Split-Path -Parent $found) "pythonw.exe"
                if (Test-Path $candidate) { return $candidate }
            }
        } catch {
            # uv present but `python find` failed - fall through to path search.
        }
    }

    $uvRoot = Join-Path $env:APPDATA "uv\python"
    if (Test-Path $uvRoot) {
        $match = Get-ChildItem -Path $uvRoot -Filter "cpython-3.11-*" -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "pythonw.exe" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($match) { return $match }
    }

    $venvPythonw = Join-Path $RepoRoot "agent\.venv\Scripts\pythonw.exe"
    if (Test-Path $venvPythonw) { return $venvPythonw }

    return $null
}

function Get-InstallState {
    # schtasks writes to stderr and exits non-zero when the task is absent;
    # that's expected here, so suppress it rather than let $ErrorActionPreference
    # ("Stop") escalate a native-command stderr write into a terminating error.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $null = & schtasks /query /tn $TaskName 2>&1
        $taskInstalled = ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $prev
    }
    $startupInstalled = Test-Path $StartupLauncher
    return [PSCustomObject]@{
        TaskInstalled    = $taskInstalled
        StartupInstalled = $startupInstalled
    }
}

function Invoke-Check {
    $pythonw = Resolve-Pythonw
    $state = Get-InstallState
    $pythonwLabel = if ($pythonw) { $pythonw } else { "<NOT FOUND>" }
    $taskLabel = if ($state.TaskInstalled) { "installed" } else { "not installed" }
    $startupLabel = if ($state.StartupInstalled) { "installed" } else { "not installed" }
    Write-Host "Hermes gateway supervisor - install state"
    Write-Host "  repo root         : $RepoRoot"
    Write-Host "  supervisor script : $SupervisorScript"
    Write-Host "  pythonw resolved  : $pythonwLabel"
    Write-Host "  scheduled task    : $taskLabel"
    Write-Host "  startup launcher  : $startupLabel"
    if (-not (Test-Path $SupervisorScript)) {
        Write-Warning "Supervisor script not found at $SupervisorScript"
    }
}

function Invoke-Uninstall {
    $removed = $false
    $state = Get-InstallState
    if ($state.TaskInstalled) {
        schtasks /delete /tn $TaskName /f | Out-Null
        Write-Host "Removed scheduled task '$TaskName'."
        $removed = $true
    }
    if ($state.StartupInstalled) {
        Remove-Item $StartupLauncher -Force
        Write-Host "Removed Startup launcher '$StartupLauncher'."
        $removed = $true
    }
    if (-not $removed) {
        Write-Host "Nothing to uninstall - supervisor is not installed."
    }
}

function Assert-Prereqs {
    param([string]$Pythonw)
    if (-not $Pythonw) {
        Write-Error @"
Could not resolve a pythonw.exe interpreter. Install one of:
  - uv (https://docs.astral.sh/uv/) then: uv python install 3.11
  - or bootstrap this repo's agent venv: uv sync --project agent
Then re-run this installer.
"@
    }
    if (-not (Test-Path $SupervisorScript)) {
        Write-Error "Supervisor script not found at $SupervisorScript"
    }
}

function Install-Task {
    param([string]$Pythonw)
    # /rl LIMITED - no elevation. /sc onlogon - fires at this user's logon.
    # The XML-free schtasks form can't express restart-on-failure, so register
    # the base task then patch the settings via the Scheduled Tasks COM API.
    $action = "`"$Pythonw`" `"$SupervisorScript`""
    schtasks /create /tn $TaskName /tr $action /sc onlogon /rl LIMITED /f | Out-Null

    # Patch restart-on-failure + run-if-idle-off via the COM scheduler service.
    try {
        $svc = New-Object -ComObject "Schedule.Service"
        $svc.Connect()
        $folder = $svc.GetFolder("\")
        $task = $folder.GetTask($TaskName)
        $def = $task.Definition
        $def.Settings.RestartCount = 3
        $def.Settings.RestartInterval = "PT1M"
        $def.Settings.DisallowStartIfOnBatteries = $false
        $def.Settings.StopIfGoingOnBatteries = $false
        $def.Settings.ExecutionTimeLimit = "PT0S"  # no time limit (runs forever)
        # TASK_CREATE_OR_UPDATE = 6, TASK_LOGON_INTERACTIVE_TOKEN = 3
        $folder.RegisterTaskDefinition($TaskName, $def, 6, $null, $null, 3) | Out-Null
    } catch {
        Write-Warning "Registered the task, but could not patch restart-on-failure settings: $_"
    }

    Write-Host "Installed scheduled task '$TaskName' (at logon, no console)."
    Write-Host "  interpreter: $Pythonw"
    Write-Host "  script     : $SupervisorScript"
    Write-Host "Start it now without logging out:  schtasks /run /tn $TaskName"
}

function Install-Startup {
    param([string]$Pythonw)
    # A .vbs shim launches pythonw with window style 0 (hidden) so no console
    # flashes at logon. pythonw already detaches from a console, but the .vbs
    # form guarantees a hidden launch regardless of association quirks.
    $vbs = @"
' Auto-generated by tools\install_hermes_supervisor.ps1 (PA-104).
' Launches the Hermes gateway supervisor hidden at logon.
Set shell = CreateObject("WScript.Shell")
shell.Run """$Pythonw"" ""$SupervisorScript""", 0, False
"@
    Set-Content -Path $StartupLauncher -Value $vbs -Encoding ASCII
    Write-Host "Installed Startup launcher '$StartupLauncher'."
    Write-Host "  interpreter: $Pythonw"
    Write-Host "  script     : $SupervisorScript"
    Write-Host "It will start at your next logon. To start now:"
    Write-Host "  wscript `"$StartupLauncher`""
}

# ----- dispatch -----

if ($Check) {
    Invoke-Check
    return
}

if ($Uninstall) {
    Invoke-Uninstall
    return
}

$pythonw = Resolve-Pythonw
Assert-Prereqs -Pythonw $pythonw

if ($Method -eq "Startup") {
    Install-Startup -Pythonw $pythonw
} else {
    Install-Task -Pythonw $pythonw
}
