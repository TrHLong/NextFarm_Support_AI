$ErrorActionPreference = 'Stop'
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$envFile = Join-Path $ProjectRoot '.env'
if (-not (Test-Path $envFile)) { throw 'Thiếu .env; chạy scripts\setup_v9_env.cmd trước.' }
Get-Content $envFile | ForEach-Object {
  if ($_ -match '^([^#][^=]*)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process') }
}
$login = Invoke-RestMethod -Uri 'http://localhost:18100/auth/login' -Method Post -ContentType 'application/json' -Body (@{username='kythuat.01';password=$env:NEXTFARM_TECH_PASSWORD}|ConvertTo-Json)
$headers = @{Authorization="Bearer $($login.access_token)"}
$status = Invoke-RestMethod -Uri 'http://localhost:18600/ml/status' -Headers $headers
$status | ConvertTo-Json -Depth 12
if (-not $status.reference_bootstrap_ready) { throw 'AI chưa hoàn tất static-reference bootstrap.' }
if ($status.shared_model_count -ne 10) { throw "Cần 10 shared models, hiện có $($status.shared_model_count)." }
Write-Host "[OK] phase=$($status.training_phase); runtime=$($status.runtime_reading_count)/$($status.runtime_retrain_threshold); production_ready=$($status.production_ready)"
