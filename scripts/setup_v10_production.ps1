[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CorsAllowOrigins
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$envPath = Join-Path $projectRoot ".env"
$originValues = @($CorsAllowOrigins.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($originValues.Count -eq 0) { throw "Cần ít nhất một HTTPS origin production." }
foreach ($origin in $originValues) {
    $parsed = $null
    if (-not [Uri]::TryCreate($origin, [UriKind]::Absolute, [ref]$parsed) -or $parsed.Scheme -ne 'https' -or [string]::IsNullOrWhiteSpace($parsed.Host)) {
        throw "Origin production không hợp lệ hoặc không dùng HTTPS: $origin"
    }
}
$normalizedOrigins = $originValues -join ','

Push-Location $projectRoot
try {
    & (Join-Path $PSScriptRoot "setup_v10_env.cmd")
    if ($LASTEXITCODE -ne 0) { throw "Không tạo được .env V10." }

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -match '^([^#=]+)=(.*)$') { $values[$matches[1].Trim()] = $matches[2].Trim() }
    }
    foreach ($required in @('MQTT_INGEST_PASSWORD','MQTT_SIMULATOR_PASSWORD','NEXTFARM_INGEST_KEY')) {
        if ([string]::IsNullOrWhiteSpace($values[$required])) { throw "Thiếu $required trong .env." }
    }

    $lines = Get-Content -LiteralPath $envPath -Encoding UTF8
    $updated = $false
    $lines = $lines | ForEach-Object {
        if ($_ -match '^CORS_ALLOW_ORIGINS=') {
            $updated = $true
            "CORS_ALLOW_ORIGINS=$normalizedOrigins"
        } else { $_ }
    }
    if (-not $updated) { $lines += "CORS_ALLOW_ORIGINS=$normalizedOrigins" }
    Set-Content -LiteralPath $envPath -Value $lines -Encoding UTF8

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Cần Docker CLI để tạo Mosquitto password file an toàn."
    }
    $secretDir = Join-Path $projectRoot ".secrets"
    New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
    $passwordFile = Join-Path $secretDir "mosquitto.passwords"
    if (Test-Path -LiteralPath $passwordFile) { Remove-Item -LiteralPath $passwordFile -Force }

    & docker run --rm --entrypoint mosquitto_passwd -v "${secretDir}:/work" eclipse-mosquitto:2.0 `
        -b -c /work/mosquitto.passwords nextfarm_ingest $values['MQTT_INGEST_PASSWORD']
    if ($LASTEXITCODE -ne 0) { throw "Không tạo được tài khoản MQTT ingest." }
    & docker run --rm --entrypoint mosquitto_passwd -v "${secretDir}:/work" eclipse-mosquitto:2.0 `
        -b /work/mosquitto.passwords nextfarm_simulator $values['MQTT_SIMULATOR_PASSWORD']
    if ($LASTEXITCODE -ne 0) { throw "Không tạo được tài khoản MQTT simulator." }

    Write-Host "[OK] Production secrets đã sẵn sàng." -ForegroundColor Green
    Write-Host "Khởi động bằng: docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build"
}
finally {
    Pop-Location
}
