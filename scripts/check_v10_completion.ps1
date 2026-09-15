[CmdletBinding()]
param([switch]$SkipCompose, [switch]$Runtime)
$ErrorActionPreference = "Stop"
$utf8Output = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8Output
$OutputEncoding = $utf8Output
$env:PYTHONUTF8 = "1"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$failures = [System.Collections.Generic.List[string]]::new()
function Invoke-Check([string]$Name, [scriptblock]$Action) {
  try { & $Action; if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }; Write-Host "[PASS] $Name" -ForegroundColor Green }
  catch { $failures.Add("${Name}: $($_.Exception.Message)"); Write-Host "[FAIL] $Name - $($_.Exception.Message)" -ForegroundColor Red }
}
Push-Location $root
try {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
  if (-not $python) { throw "Can Python 3." }
  if ($python.Name -eq "py.exe") { Invoke-Check "V10 static/artifact validation" { py -3 scripts\check_v10_static.py } }
  else { Invoke-Check "V10 static/artifact validation" { python scripts\check_v10_static.py } }

  $node = Get-Command node -ErrorAction SilentlyContinue
  if ($node) {
    Invoke-Check "Chat JavaScript syntax" { node --check apps/web/app.js }
    Invoke-Check "Data Studio JavaScript syntax" { node --check apps/data-studio/app.js }
    Invoke-Check "Knowledge Studio JavaScript syntax" { node --check apps/knowledge-studio/app.js }
    Invoke-Check "AI Encyclopedia JavaScript syntax" { node --check apps/ai-encyclopedia/app.js }
  } else { Write-Host "[SKIP] Node.js khong co." -ForegroundColor Yellow }

  Invoke-Check "PowerShell script syntax" {
    $syntaxErrors = @()
    Get-ChildItem -LiteralPath scripts -Filter "*.ps1" -File | ForEach-Object {
      $tokens = $null; $errors = $null
      [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors) | Out-Null
      $syntaxErrors += $errors
    }
    if ($syntaxErrors.Count) { throw ($syntaxErrors | ForEach-Object Message | Select-Object -First 5) -join "; " }
  }

  if (-not $SkipCompose) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
      if (-not (Test-Path .env)) { Write-Host "[INFO] .env chua co; chay scripts\setup_v10_env.cmd truoc khi Docker Compose config/runtime." -ForegroundColor Yellow }
      else {
        Invoke-Check "Docker Compose V10 config" { docker compose config --quiet }
        Invoke-Check "Docker Compose production override config" { docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet }
        if ($Runtime) {
          Invoke-Check "V10 endpoint/unit tests in containers" { & scripts\check_v10_unit_tests.ps1 }
          Invoke-Check "V10 authenticated runtime smoke test" { & scripts\check_v10_runtime.ps1 }
        }
      }
    } else { Write-Host "[SKIP] Docker CLI khong co." -ForegroundColor Yellow }
  }
} finally { Pop-Location }
if ($failures.Count) { Write-Host "`nV10 check that bai:" -ForegroundColor Red; $failures | ForEach-Object { Write-Host " - $_" }; exit 1 }
Write-Host "`nV10 completion checks dat." -ForegroundColor Green
