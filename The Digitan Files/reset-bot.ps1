# Reset Digitan bot and restart it from the local bot folder.
# Run this from PowerShell: .\reset-bot.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$venvPython = Join-Path $scriptDir '.venv\Scripts\python.exe'
$pythonExe = if (Test-Path $venvPython) { $venvPython } else { 'python' }
$botPath = Join-Path $scriptDir 'bot.py'

Write-Host "Stopping existing Digitan bot Python processes..."
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    try {
        $_.Path -and $_.Path -like "*$scriptDir*"
    } catch {
        $false
    }
} | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Starting Digitan bot..."
Start-Process -FilePath $pythonExe -ArgumentList "`"$botPath`"" -WorkingDirectory $scriptDir
Write-Host "Digitan bot restart command issued. Check the PowerShell window or bot logs for startup confirmation."