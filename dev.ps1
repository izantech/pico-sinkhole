<#
.SYNOPSIS
    Development and deployment automation script for pico-sinkhole.

.DESCRIPTION
    Automates uploading code, running tests, monitoring logs, and interacting
    with Raspberry Pi Pico W / Pico 2 W devices over serial using mpremote.

.PARAMETER Action
    Action to perform: deploy, sync, monitor, test, run-local, ls, reset, help

.PARAMETER Port
    Optional COM port (e.g. COM7). If omitted, automatically detected.

.EXAMPLE
    .\dev.ps1 deploy
    .\dev.ps1 monitor
    .\dev.ps1 test
    .\dev.ps1 ls
#>

[CmdletBinding()]
param (
    [Parameter(Position = 0)]
    [ValidateSet("deploy", "sync", "monitor", "logs", "repl", "test", "run-local", "ls", "reset", "update-lists", "help")]
    [string]$Action = "deploy",

    [Parameter(Position = 1)]
    [string]$Port = "",

    [switch]$Mpy
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot

function Write-Header {
    param([string]$Text)
    Write-Host "`n=== $Text ===" -ForegroundColor Cyan
}

function Ensure-Mpremote {
    if (-not (Get-Command mpremote -ErrorAction SilentlyContinue)) {
        Write-Host "[INFO] Installing mpremote..." -ForegroundColor Yellow
        python -m pip install mpremote
    }
}

function Ensure-MpyCross {
    if (-not (Get-Command mpy-cross -ErrorAction SilentlyContinue)) {
        Write-Host "[INFO] Installing mpy-cross..." -ForegroundColor Yellow
        python -m pip install mpy-cross
    }
}

function Find-PicoPort {
    if ($Port) {
        return $Port
    }
    
    # Try mpremote auto-detect
    $devOutput = & mpremote devs 2>&1
    if ($LASTEXITCODE -eq 0 -and $devOutput) {
        $firstLine = ($devOutput | Select-Object -First 1)
        if ($firstLine -match '(COM\d+)') {
            return $Matches[1]
        }
    }

    # Fallback to CIM PnP query for RP2 / Raspberry devices
    $pnp = Get-CimInstance Win32_PnPEntity | Where-Object { 
        $_.Caption -match 'USB Serial.*(COM\d+)' -or 
        $_.DeviceID -match 'USB\\VID_2E8A' 
    } | Select-Object -First 1

    if ($pnp -and $pnp.Caption -match '(COM\d+)') {
        return $Matches[1]
    }

    return ""
}

function Get-MpremotePrefix {
    param([string]$comPort)
    if ($comPort) {
        return @("connect", $comPort)
    }
    return @()
}

function Run-Deploy {
    Ensure-Mpremote
    $targetPort = Find-PicoPort
    if ($targetPort) {
        Write-Host "[OK] Detected MicroPython device on: $targetPort" -ForegroundColor Green
    } else {
        Write-Host "[WARN] No specific COM port auto-detected; attempting default mpremote connection..." -ForegroundColor Yellow
    }

    if (-not (Test-Path "$ScriptDir\config.json")) {
        Write-Host "[WARN] config.json not found. Copying config.example.json -> config.json..." -ForegroundColor Yellow
        Copy-Item "$ScriptDir\config.example.json" "$ScriptDir\config.json"
        Write-Host "[IMPORTANT] Please edit config.json to add your WiFi SSID and password!" -ForegroundColor Magenta
    }

    $prefix = Get-MpremotePrefix $targetPort

    Write-Header "Syncing Files to Pico"
    try {
        Write-Host "-> Copying config.json..." -ForegroundColor Gray
        & mpremote @prefix cp "$ScriptDir\config.json" :config.json

        Write-Host "-> Copying blocklist.txt..." -ForegroundColor Gray
        & mpremote @prefix cp "$ScriptDir\blocklist.txt" :blocklist.txt

        Write-Host "-> Copying whitelist.txt..." -ForegroundColor Gray
        & mpremote @prefix cp "$ScriptDir\whitelist.txt" :whitelist.txt

        if (Test-Path "$ScriptDir\blocklist.bloom") {
            Write-Host "-> Copying blocklist.bloom..." -ForegroundColor Gray
            & mpremote @prefix cp "$ScriptDir\blocklist.bloom" :blocklist.bloom
        }

        Write-Host "-> Copying main.py..." -ForegroundColor Gray
        & mpremote @prefix cp "$ScriptDir\main.py" :main.py

        Write-Host "-> Ensuring :src directory..." -ForegroundColor Gray
        & mpremote @prefix mkdir :src 2>$null

        $srcFiles = Get-ChildItem -Path "$ScriptDir\src" -Filter "*.py"

        if ($Mpy) {
            # Precompile to .mpy: removes the on-device compile spike at boot and
            # shrinks resident code RAM. mpy-cross version must match the
            # firmware's bytecode ABI (same MicroPython minor version).
            Ensure-MpyCross
            $mpyDir = "$ScriptDir\build\mpy"
            New-Item -ItemType Directory -Force $mpyDir | Out-Null

            foreach ($file in $srcFiles) {
                $baseName = $file.BaseName
                $mpyPath = "$mpyDir\$baseName.mpy"
                Write-Host "-> Compiling src/$($file.Name) -> build/mpy/$baseName.mpy..." -ForegroundColor Gray
                & mpy-cross $file.FullName -o $mpyPath
                if ($LASTEXITCODE -ne 0) { throw "mpy-cross failed on $($file.Name)" }
                & mpremote @prefix cp $mpyPath ":src/$baseName.mpy"
            }
        }
        else {
            foreach ($file in $srcFiles) {
                Write-Host "-> Copying src/$($file.Name)..." -ForegroundColor Gray
                & mpremote @prefix cp $file.FullName ":src/$($file.Name)"
            }
        }

        # Sweep :src on the device: remove anything not in the expected set
        # (stale .py after -Mpy, stale .mpy after plain deploy, and orphans
        # from locally deleted or renamed modules)
        $expected = $srcFiles | ForEach-Object { if ($Mpy) { "$($_.BaseName).mpy" } else { $_.Name } }
        $lsOutput = & mpremote @prefix ls :src 2>$null
        foreach ($line in $lsOutput) {
            if ($line -match '^\s*\d+\s+(\S.*)$') {
                $name = $Matches[1].Trim()
                if ($name.EndsWith("/")) {
                    # Unexpected directory (e.g. a stray __pycache__): remove recursively
                    $dirName = $name.TrimEnd("/")
                    Write-Host "-> Removing stale directory :src/$dirName..." -ForegroundColor DarkYellow
                    & mpremote @prefix rm -r ":src/$dirName" 2>$null
                }
                elseif ($expected -notcontains $name) {
                    Write-Host "-> Removing stale :src/$name..." -ForegroundColor DarkYellow
                    & mpremote @prefix rm ":src/$name" 2>$null
                }
            }
        }

        Write-Host "`n[SUCCESS] All files deployed successfully!" -ForegroundColor Green
        Write-Host "[INFO] Resetting Pico and starting application..." -ForegroundColor Cyan
        & mpremote @prefix reset
        
        Write-Host "[INFO] Streaming serial logs (Press Ctrl+C to stop monitor)..." -ForegroundColor Yellow
        & mpremote @prefix repl
    }
    catch {
        Write-Host "`n[ERROR] Deployment failed: $_" -ForegroundColor Red
        Write-Host "[TIP] If Thonny or another program is open, close or disconnect it so the COM port is free!" -ForegroundColor Yellow
    }
}

function Run-Monitor {
    Ensure-Mpremote
    $displayPort = if ($targetPort) { $targetPort } else { "auto" }
    Write-Header "Connecting to Serial Console ($displayPort)"
    Write-Host "[INFO] Press Ctrl+] or Ctrl+C to exit REPL" -ForegroundColor Yellow
    & mpremote @prefix repl
}

function Run-Ls {
    Ensure-Mpremote
    $targetPort = Find-PicoPort
    $prefix = Get-MpremotePrefix $targetPort
    Write-Header "Files on Pico Root (/)"
    & mpremote @prefix ls :
    Write-Header "Files on Pico (/src)"
    & mpremote @prefix ls :src
}

function Run-Reset {
    Ensure-Mpremote
    $targetPort = Find-PicoPort
    $prefix = Get-MpremotePrefix $targetPort
    Write-Host "[INFO] Resetting device..." -ForegroundColor Cyan
    & mpremote @prefix reset
}

function Run-Test {
    Write-Header "Running Host Unit Test Suite"
    python -m unittest discover -s tests -p "test_*.py" -v
}

function Run-Local {
    Write-Header "Starting Sinkhole on Local PC (Desktop Mode)"
    python main.py
}

function Run-UpdateLists {
    Write-Header "Building Bloom Filter Blocklist (blocklist.bloom)"
    python "$ScriptDir\tools\build_bloom.py"
}

# Main Dispatcher
switch ($Action) {
    "deploy"    { Run-Deploy }
    "sync"      { Run-Deploy }
    "monitor"   { Run-Monitor }
    "logs"      { Run-Monitor }
    "repl"      { Run-Monitor }
    "ls"        { Run-Ls }
    "reset"     { Run-Reset }
    "test"      { Run-Test }
    "run-local" { Run-Local }
    "update-lists" { Run-UpdateLists }
    "help"      {
        Write-Host @"
Pico-Sinkhole Dev Tool
Usage:
    .\dev.ps1 deploy       - Sync all files to connected Pico, reset, and stream logs
    .\dev.ps1 deploy -Mpy  - Same, but precompile src/ with mpy-cross (less RAM on device;
                             mpy-cross version must match firmware's MicroPython version)
    .\dev.ps1 monitor      - Open live serial monitor / REPL
    .\dev.ps1 ls           - List files on Pico filesystem
    .\dev.ps1 reset        - Soft reset connected Pico
    .\dev.ps1 test         - Run Python test suite on PC
    .\dev.ps1 run-local    - Run sinkhole locally on PC for testing
    .\dev.ps1 update-lists - Build blocklist.bloom from hagezi lists (see tools\build_bloom.py)
"@
    }
}
