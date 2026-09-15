[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [Parameter(Mandatory = $true)][switch]$ConfirmRestore,
    [switch]$SkipSafetyBackup
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "Restore sẽ ghi đè database hiện tại. Chỉ chạy lại khi có -ConfirmRestore."
}

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$resolvedBackup = (Resolve-Path -LiteralPath $BackupFile).Path
if ([System.IO.Path]::GetExtension($resolvedBackup) -ne ".dump") {
    throw "Backup phải là file .dump sinh bởi scripts/backup_v10.ps1."
}

Push-Location $projectRoot
$containerFile = "/tmp/nextfarm-restore.dump"
try {
    if (-not $SkipSafetyBackup) {
        & (Join-Path $PSScriptRoot "backup_v10.ps1") -Verify
    }

    $services = @(
        "identity-service","farm-data-service","knowledge-service","ticket-service",
        "telemetry-ingestion-service","data-simulator-service","ai-analytics-service",
        "truth-guard-service","crop-router-service","llm-gateway-service","chatbot-service",
        "frontend","data-studio","knowledge-studio","ai-encyclopedia"
    )
    docker compose cp $resolvedBackup "postgres:$containerFile"
    if ($LASTEXITCODE -ne 0) { throw "Không sao chép được backup vào PostgreSQL container." }
    docker compose exec -T postgres pg_restore -l $containerFile | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "File backup không có catalog pg_restore hợp lệ." }

    docker compose stop $services
    if ($LASTEXITCODE -ne 0) { throw "Không dừng được các service đang dùng database." }

    docker compose exec -T postgres pg_restore --clean --if-exists --no-owner --no-privileges -U nextfarm -d nextfarm_support $containerFile
    if ($LASTEXITCODE -ne 0) { throw "Restore thất bại; safety backup trước restore vẫn được giữ lại." }

    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U nextfarm -d nextfarm_support -f /docker-entrypoint-initdb.d/03_v10_ops_migration.sql
    if ($LASTEXITCODE -ne 0) { throw "Database đã restore nhưng migration vận hành V10 thất bại." }
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U nextfarm -d nextfarm_support -f /docker-entrypoint-initdb.d/04_v10_ai_encyclopedia.sql
    if ($LASTEXITCODE -ne 0) { throw "Database đã restore nhưng migration AI Encyclopedia V10 thất bại." }

    docker compose exec -T postgres rm -f $containerFile
    docker compose up -d
    Write-Host "Restore hoàn tất. Hãy chạy scripts/check_v10_completion.ps1 để nghiệm thu."
}
finally {
    docker compose exec -T postgres rm -f $containerFile 2>$null
    Pop-Location
}
