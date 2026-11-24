param([int]$Port = 8501)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create .venv and install requirements first. See README.md.' }
$localConfig = Join-Path $PSScriptRoot '.env.local'
if (Test-Path -LiteralPath $localConfig) {
    foreach ($line in Get-Content -LiteralPath $localConfig) {
        if ($line -match '^\s*(WORKSPACE_DATABASE_URL|HF_HOME|TRANSFORMERS_CACHE)\s*=\s*(.*?)\s*$') {
            $key = $Matches[1]
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            if (-not [Environment]::GetEnvironmentVariable($key, 'Process')) {
                [Environment]::SetEnvironmentVariable($key, $value, 'Process')
            }
        }
    }
}
if (-not $env:WORKSPACE_DATABASE_URL) { throw 'Set WORKSPACE_DATABASE_URL or create .env.local. See README.md.' }
& $pythonPath -m streamlit run streamlit_app.py --server.port $Port
exit $LASTEXITCODE
