[CmdletBinding()]
param(
    [string]$BackupDirectory = "",
    [ValidateRange(0, 3650)][int]$RetentionDays = 0,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
    $BackupDirectory = Join-Path $projectRoot "backups"
}
$backupRoot = [System.IO.Path]::GetFullPath($BackupDirectory)
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupId = "backup_$stamp"
$fileName = "nextfarm-$stamp.dump"
$containerFile = "/tmp/$fileName"
$localFile = Join-Path $backupRoot $fileName

Push-Location $projectRoot
try {
    $containerId = (docker compose ps -q postgres).Trim()
    if (-not $containerId) {
        throw "PostgreSQL chưa chạy. Hãy chạy docker compose up -d trước khi backup."
    }

    docker compose exec -T postgres pg_dump -Fc -U nextfarm -d nextfarm_support -f $containerFile
    if ($LASTEXITCODE -ne 0) { throw "pg_dump thất bại." }

    docker compose cp "postgres:$containerFile" $localFile
    if ($LASTEXITCODE -ne 0) { throw "Không sao chép được file backup khỏi container." }

    $verifiedAt = "NULL"
    if ($Verify) {
        docker compose exec -T postgres pg_restore -l $containerFile | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "pg_restore không đọc được catalog backup." }
        $verifiedAt = "now()"
    }

    $item = Get-Item -LiteralPath $localFile
    $checksum = (Get-FileHash -LiteralPath $localFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $safePath = $item.FullName.Replace("'", "''")
    $sql = "INSERT INTO ops_db.backup_runs(backup_id,backup_type,status,artifact_path,size_bytes,checksum_sha256,completed_at,verified_at) VALUES ('$backupId','manual','completed','$safePath',$($item.Length),'$checksum',now(),$verifiedAt) ON CONFLICT (backup_id) DO NOTHING;"
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U nextfarm -d nextfarm_support -c $sql | Out-Null

    if ($RetentionDays -gt 0) {
        $cutoff = (Get-Date).AddDays(-$RetentionDays)
        Get-ChildItem -LiteralPath $backupRoot -Filter "nextfarm-*.dump" -File |
            Where-Object { $_.LastWriteTime -lt $cutoff -and $_.FullName -ne $item.FullName } |
            Remove-Item -Force
    }

    [PSCustomObject]@{
        BackupId = $backupId
        File = $item.FullName
        SizeBytes = $item.Length
        Sha256 = $checksum
        Verified = [bool]$Verify
    } | Format-List
}
finally {
    docker compose exec -T postgres rm -f $containerFile 2>$null
    Pop-Location
}
