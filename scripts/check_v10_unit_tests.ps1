$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath ".env")) {
        & cmd /c "scripts\setup_v10_env.cmd"
        if ($LASTEXITCODE -ne 0) { throw "Khong tao duoc .env." }
    }

    $services = @(
        "crop-router-service",
        "llm-gateway-service",
        "truth-guard-service",
        "knowledge-service",
        "chatbot-service",
        "ai-analytics-service"
    )
    foreach ($service in $services) {
        Write-Host "[TEST] $service"
        & docker compose --env-file .env exec -T $service python -m pytest tests -q
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    Write-Host "[TEST] ai-analytics artifact smoke"
    & docker compose --env-file .env exec -T ai-analytics-service python artifact_smoke_test.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "[TEST] device contract suite"
    & docker compose --env-file .env exec -T ai-analytics-service python -m pytest tests_device -q
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
