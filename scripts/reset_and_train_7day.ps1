param(
  [int]$Days = 7,
  [int]$Sites = 12,
  [int]$Seed = 20260928
)

$ErrorActionPreference = "Stop"
$Project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location $Project

if ($Days -lt 7) { throw "Days must be at least 7." }
if ($Sites -lt 9) { throw "Sites must be at least 9 for unseen-customer holdout." }

$generated = @(
  (Join-Path $Project "data"),
  (Join-Path $Project "model-artifacts"),
  (Join-Path $Project "benchmarks"),
  (Join-Path $Project ".pytest_cache")
)
foreach ($path in $generated) {
  $resolved = [IO.Path]::GetFullPath($path)
  if (Test-Path -LiteralPath $resolved) {
    Write-Host "[DELETE] $resolved"
    Remove-Item -LiteralPath $resolved -Recurse -Force
  }
}
New-Item -ItemType Directory -Path (Join-Path $Project "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Project "model-artifacts") -Force | Out-Null

Write-Host "[TRAIN] synthetic dataset: $Days days, $Sites sites, seed $Seed"
docker compose run --rm --no-deps `
  ai-analytics-service `
  python /app/train_device_models.py `
  --data /data/device-v11-7day `
  --artifacts /models/device-v11-7day `
  --generate --days $Days --sites $Sites --seed $Seed

Write-Host "[DONE] Read model-artifacts\device-v11-7day\runs\ for metrics."
