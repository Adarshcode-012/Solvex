$ErrorActionPreference = 'Stop'

$backendPort = 8001
$frontendPort = 5173
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot 'backend'
$frontendDir = Join-Path $repoRoot 'frontend'

function Assert-PortFree([int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        $ownerName = if ($owner) { $owner.Name } else { 'unknown process' }
        throw "Port $Port is already in use by PID $($listener.OwningProcess) ($ownerName). Stop that process or choose another port."
    }
}

Assert-PortFree $backendPort
Assert-PortFree $frontendPort

$providerEnvNames = @('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY')
$placeholderMarkers = @('placeholder', 'your-key', 'your_key', 'changeme', 'xxxx', 'example')
Get-ChildItem Env: | Where-Object {
    $isRelevant = ($providerEnvNames -contains $_.Name) -or $_.Name.StartsWith('SOLVEX_', [StringComparison]::OrdinalIgnoreCase)
    $value = $_.Value.Trim()
    $wrappedPlaceholder = $value.StartsWith('<') -and $value.EndsWith('>')
    $containsPlaceholder = $false
    foreach ($marker in $placeholderMarkers) {
        if ($value.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $containsPlaceholder = $true }
    }
    $isRelevant -and $value -and ($wrappedPlaceholder -or $containsPlaceholder)
} | ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" }

Write-Host 'netstat -ano | findstr :8001 (before backend start)'
netstat -ano | findstr ':8001'

Write-Host 'Open two PowerShell terminals and run the commands below.'
Write-Host 'keys: loaded from backend/.env'
Write-Host 'BACKEND:'
Write-Host 'cd .\backend; $env:BACKEND_PORT=''8001''; .\venv\Scripts\python.exe -u dev_server.py 2>&1 | Tee-Object -FilePath .\dev.log'
Write-Host 'FRONTEND:'
Write-Host 'cd .\frontend; $env:DEV_API_PORT=''8001''; npm run dev -- --host 127.0.0.1'
Write-Host "Backend URL: http://127.0.0.1:$backendPort"
Write-Host "Frontend URL: http://127.0.0.1:$frontendPort"
