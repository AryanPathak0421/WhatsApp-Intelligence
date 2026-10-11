# Starts the whole development stack as detached background processes (they survive this shell and any tool time limit).
#   powershell -ExecutionPolicy Bypass -File scripts/dev/dev-up.ps1            # everything that is installed
#   powershell -ExecutionPolicy Bypass -File scripts/dev/dev-up.ps1 -NoLlm      # skip the language-model server
# Logs: private-data/logs/*.log. Stop with dev-down.ps1. Development only: secrets are generated once into private-data/dev.env (git-ignored).
param([switch]$NoLlm)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$data = Join-Path $root 'private-data'
$logs = Join-Path $data 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$py = Join-Path $root 'ai-engine\.venv\Scripts\python.exe'
$node = (Get-Command node).Source

function Test-Port([int]$p) { [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) }
function Start-Svc([string]$name, [int]$port, [string]$exe, [string[]]$argv, [string]$cwd) {
  if (Test-Port $port) { Write-Host ("{0,-10} already listening on :{1}" -f $name, $port); return }
  $p = Start-Process -FilePath $exe -ArgumentList $argv -WorkingDirectory $cwd -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "$name.log") -RedirectStandardError (Join-Path $logs "$name.err.log")
  Write-Host ("{0,-10} started (pid {1}) -> :{2}" -f $name, $p.Id, $port)
}
function Wait-Port([int]$p, [int]$seconds = 90) { $end = (Get-Date).AddSeconds($seconds); while (-not (Test-Port $p) -and (Get-Date) -lt $end) { Start-Sleep 2 } }

# --- secrets (generated once) ---
$envFile = Join-Path $data 'dev.env'
if (-not (Test-Path $envFile)) {
  $hex = { param($n) -join ((1..$n) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }) }
  @("JWT_ACCESS_SECRET=$(& $hex 48)", "JWT_REFRESH_SECRET=$(& $hex 48)", "FIELD_ENCRYPTION_KEY=$(& $hex 64)") | Set-Content $envFile -Encoding ASCII
}
Get-Content $envFile | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }

# --- 1. database ---
$pgDir = Join-Path $root 'scripts\dev\embedded-pg'
if (-not (Test-Path "$pgDir\node_modules")) { Push-Location $pgDir; npm install --no-audit --no-fund | Out-Null; Pop-Location }
Start-Svc 'postgres' 15433 $node @('start.mjs') $pgDir
Wait-Port 15433

# --- 2. AI engine (+ annotation tool) ---
$env:PYTHONPATH = '.'; $env:PYTHONIOENCODING = 'utf-8'
$env:ANNOTATION_BATCH_DIR = Join-Path $data 'batches'; $env:ANNOTATION_FILE = Join-Path $data 'annotations\annotations.jsonl'
Start-Svc 'ai-engine' 8000 $py @('-m', 'uvicorn', 'app.api.main:app', '--port', '8000', '--log-level', 'info') (Join-Path $root 'ai-engine')

# --- 3. backend API ---
$env:NODE_ENV = 'development'; $env:PORT = '4000'
$env:DATABASE_URL = 'postgresql://wa:wa_dev_pw@localhost:15433/wa_intel_dev'
$env:QUEUE_MODE = 'inline'; $env:AI_ENGINE_URL = 'http://localhost:8000'; $env:CORS_ORIGIN = 'http://localhost:5199'
$env:UPLOAD_DIR = Join-Path $data 'uploads'
Start-Svc 'backend' 4000 $node @('node_modules/tsx/dist/cli.mjs', 'src/index.ts') (Join-Path $root 'backend')

# --- 4. language model server (optional) ---
$llm = $null
if (-not $NoLlm) {
  $server = Get-ChildItem (Join-Path $data 'llm\llama.cpp') -Recurse -Filter 'llama-server.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
  $model = Get-ChildItem (Join-Path $data 'llm\models') -Filter '*00001-of-*.gguf' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($server -and $model) {
    Start-Svc 'llm' 8081 $server.FullName @('-m', $model.FullName, '--port', '8081', '--host', '127.0.0.1', '-c', '8192', '--jinja', '-t', '8', '--no-webui') $data
    $llm = $model.BaseName
  } else { Write-Host 'llm        not installed (see docx/07-assistant and docx/12-datasets-and-models)' }
}

# --- 5. assistant ---
$env:BACKEND_URL = 'http://localhost:4000/api'
$env:LLM_BASE_URL = 'http://localhost:8081/v1'; $env:LLM_MODEL = if ($llm) { $llm } else { 'local' }
$env:ASSISTANT_AUDIT_FILE = Join-Path $data 'assistant\audit.jsonl'; $env:ASSISTANT_FEEDBACK_FILE = Join-Path $data 'assistant\feedback.jsonl'
$env:ASSISTANT_DOCS_DIR = Join-Path $data 'assistant\docs'; $env:ASSISTANT_PORT = '8100'
New-Item -ItemType Directory -Force (Join-Path $data 'assistant') | Out-Null
Start-Svc 'assistant' 8100 $py @('-m', 'wa_assistant') (Join-Path $root 'assistant')

# --- 6. frontend (5173 belongs to another app on this machine; 5199 is used here) ---
$env:VITE_API_TARGET = 'http://localhost:4000'; $env:VITE_ASSISTANT_TARGET = 'http://localhost:8100'
Start-Svc 'frontend' 5199 $node @('node_modules/vite/bin/vite.js', '--port', '5199', '--strictPort') (Join-Path $root 'frontend')

Write-Host "`nPanel: http://localhost:5199   Annotation tool: http://localhost:8000/annotate   Logs: $logs"
