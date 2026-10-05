# Stops the development stack started by dev-up.ps1 (by listening port, so unrelated processes on this machine are never touched).
$ports = [ordered]@{ frontend = 5199; assistant = 8100; backend = 4000; 'ai-engine' = 8000; llm = 8081; postgres = 15433 }
foreach ($name in $ports.Keys) {
  $c = Get-NetTCPConnection -LocalPort $ports[$name] -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $c) { Write-Host ("{0,-10} not running" -f $name); continue }
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
  Stop-Process -Id $c.OwningProcess -Force
  if ($proc.ParentProcessId) { $parent = Get-Process -Id $proc.ParentProcessId -ErrorAction SilentlyContinue; if ($parent -and $parent.ProcessName -in 'python', 'node') { Stop-Process -Id $parent.Id -Force -ErrorAction SilentlyContinue } }
  Write-Host ("{0,-10} stopped (:{1})" -f $name, $ports[$name])
}
