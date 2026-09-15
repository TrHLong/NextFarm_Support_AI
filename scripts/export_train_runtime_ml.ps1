$ErrorActionPreference = 'Stop'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$envFile = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    throw 'Thiếu .env; chạy scripts\setup_v10_env.cmd trước.'
}

Get-Content -LiteralPath $envFile | ForEach-Object {
    if ($_ -match '^([^#][^=]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}

$loginBody = @{username='kythuat.01';password=$env:NEXTFARM_TECH_PASSWORD} | ConvertTo-Json
$login = Invoke-RestMethod -Uri 'http://127.0.0.1:18100/auth/login' -Method Post -ContentType 'application/json' -Body $loginBody
$headers = @{Authorization="Bearer $($login.access_token)"}

Write-Host '1/3 Xuất snapshot PostgreSQL hiện tại ra data\runtime_csv ...'
$snapshot = Invoke-RestMethod -Uri 'http://127.0.0.1:18600/ml/export-runtime-csv' -Method Post -Headers $headers
Write-Host "Snapshot: $($snapshot.snapshot_id)"
Write-Host "Thư mục: $($snapshot.output_directory)"

$before = Invoke-RestMethod -Uri 'http://127.0.0.1:18600/ml/status' -Headers $headers
Write-Host '2/3 Bắt đầu xử lý dữ liệu và train 10 model từ runtime PostgreSQL ...'
$accepted = Invoke-RestMethod -Uri 'http://127.0.0.1:18600/ml/train' -Method Post -Headers $headers
if (-not $accepted.accepted) { throw 'Dịch vụ không nhận yêu cầu train.' }

$deadline = (Get-Date).AddMinutes(30)
$seenRunning = $false
do {
    Start-Sleep -Seconds 5
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:18600/ml/status' -Headers $headers
    if ($status.running) {
        $seenRunning = $true
        Write-Host "Đang train: runtime rows=$($status.runtime_reading_count)"
    }
    if ($status.last_error) { throw "Train lỗi: $($status.last_error)" }
    $finished = -not $status.running -and $status.dataset_version -and (
        $seenRunning -or $status.dataset_version -ne $before.dataset_version -or $status.last_finished_at -ne $before.last_finished_at
    )
} until ($finished -or (Get-Date) -ge $deadline)

if (-not $finished) { throw 'Quá 30 phút nhưng phiên train chưa hoàn thành.' }

Write-Host '3/3 Kết quả'
[PSCustomObject]@{
    DatasetVersion = $status.dataset_version
    DatasetSource = $status.dataset_source
    ModelCount = $status.total_model_artifacts
    Approved = $status.approved_model_count
    Experimental = $status.experimental_model_count
    ProductionReady = $status.production_ready
} | Format-List

Write-Host 'CSV runtime nằm trong data\runtime_csv; CSV train/validation/test và metric nằm trong data\ml.'
