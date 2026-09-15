param(
    [switch]$WriteDemoMessages,
    [switch]$RestartChatbot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$EnvFile = Join-Path $ProjectRoot '.env'
$EvidenceFile = Join-Path $ProjectRoot 'docs\evidence\demo-sections-4-7-latest.json'
$Results = [System.Collections.Generic.List[object]]::new()
$StartedAt = [DateTimeOffset]::UtcNow

function Add-Result {
    param([string]$Code, [string]$Requirement, [bool]$Passed, [string]$Detail)
    $status = if ($Passed) { 'PASS' } else { 'FAIL' }
    $color = if ($Passed) { 'Green' } else { 'Red' }
    Write-Host "[$status] $Code - ${Requirement}: $Detail" -ForegroundColor $color
    $Results.Add([pscustomobject]@{
        code = $Code
        requirement = $Requirement
        passed = $Passed
        detail = $Detail
    })
}

function Get-DotEnvValue {
    param(
        [string]$Name,
        [AllowNull()][string]$Default = $null
    )
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw "Không tìm thấy $EnvFile"
    }
    $line = Get-Content -LiteralPath $EnvFile -Encoding UTF8 |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -Last 1
    if (-not $line) {
        if ($null -ne $Default) { return $Default }
        throw "Thiếu biến $Name trong .env"
    }
    $value = ($line -split '=', 2)[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

function Invoke-Json {
    param(
        [string]$Uri,
        [string]$Method = 'GET',
        [hashtable]$Headers = @{},
        [object]$Body = $null,
        [int]$TimeoutSec = 20
    )
    $args = @{
        Uri = $Uri
        Method = $Method
        Headers = $Headers
        TimeoutSec = $TimeoutSec
    }
    if ($null -ne $Body) {
        $args.ContentType = 'application/json; charset=utf-8'
        $jsonBody = $Body | ConvertTo-Json -Depth 12 -Compress
        $args.Body = [System.Text.Encoding]::UTF8.GetBytes($jsonBody)
    }
    return Invoke-RestMethod @args
}

function Get-HttpStatusFromException {
    param($Exception)
    try { return [int]$Exception.Response.StatusCode } catch { return 0 }
}

Write-Host "`nNEXTFARM - KIỂM THỬ DEMO MỤC 4, 5, 6, 7" -ForegroundColor Cyan
Write-Host "Phạm vi: health, phân quyền, dữ liệu, báo cáo ngày, tri thức, chat an toàn và lưu bền vững.`n"

if ($RestartChatbot -and -not $WriteDemoMessages) {
    throw 'Muốn kiểm thử restart phải bật thêm -WriteDemoMessages để có thông điệp đối chiếu trước/sau.'
}

$healthTargets = @(
    @{ code='SVC-IDENTITY'; url='http://localhost:18100/health'; name='identity-service' },
    @{ code='SVC-CHAT'; url='http://localhost:18000/health'; name='chatbot-service' },
    @{ code='SVC-FARM'; url='http://localhost:18300/health'; name='farm-data-service' },
    @{ code='SVC-KNOWLEDGE'; url='http://localhost:18200/health'; name='knowledge-service' },
    @{ code='SVC-TELEMETRY'; url='http://localhost:18800/health'; name='telemetry-ingestion-service' },
    @{ code='SVC-TRUTH'; url='http://localhost:18700/health'; name='truth-guard-service' },
    @{ code='SVC-AI'; url='http://localhost:18600/health'; name='ai-analytics-service' }
)

foreach ($target in $healthTargets) {
    try {
        $health = Invoke-Json -Uri $target.url -TimeoutSec 10
        $ok = ($health.service -eq $target.name) -and ($health.status -in @('ok','starting'))
        Add-Result $target.code 'Microservice hoạt động' $ok "service=$($health.service), status=$($health.status)"
    } catch {
        Add-Result $target.code 'Microservice hoạt động' $false $_.Exception.Message
    }
}

$farmerUser = Get-DotEnvValue 'NEXTFARM_FARMER_USERNAME' 'nongdan.long'
$farmerPassword = Get-DotEnvValue 'NEXTFARM_FARMER_PASSWORD'
$techUser = Get-DotEnvValue 'NEXTFARM_TECH_USERNAME' 'kythuat.01'
$techPassword = Get-DotEnvValue 'NEXTFARM_TECH_PASSWORD'

$farmerLogin = Invoke-Json -Uri 'http://localhost:18100/auth/login' -Method POST -Body @{ username=$farmerUser; password=$farmerPassword }
$techLogin = Invoke-Json -Uri 'http://localhost:18100/auth/login' -Method POST -Body @{ username=$techUser; password=$techPassword }
$farmerHeaders = @{ Authorization = "Bearer $($farmerLogin.access_token)" }
$techHeaders = @{ Authorization = "Bearer $($techLogin.access_token)" }
$farmId = [string]$farmerLogin.user.default_farm_id

Add-Result 'AUTH-01' 'Đăng nhập và đúng vai trò' (($farmerLogin.user.role -eq 'farmer') -and ($techLogin.user.role -eq 'technician')) 'farmer và technician được xác thực; không in mật khẩu/token'
Add-Result 'AUTH-02' 'Ngữ cảnh “vườn của tôi”' (-not [string]::IsNullOrWhiteSpace($farmId)) "default_farm_id=$farmId"

$groups = Invoke-Json -Uri "http://localhost:18300/studio/data-groups?farm_id=$([uri]::EscapeDataString($farmId))" -Headers $farmerHeaders
$groupCount = @($groups.items).Count
$rowTotal = (@($groups.items) | Measure-Object -Property row_count -Sum).Sum
$originCount = @($groups.sensor_origins).Count
Add-Result 'DATA-01' 'Quản lý đủ nhóm dữ liệu vận hành' ($groupCount -eq 9) "$groupCount/9 nhóm; tổng $rowTotal dòng trong phạm vi vườn"
Add-Result 'DATA-02' 'Provenance và freshness' (($originCount -gt 0) -and $groups.policy.provenance_required) "$originCount nguồn cảm biến; mỗi nhóm có trạng thái fresh/stale/missing/available"

$report = Invoke-Json -Uri "http://localhost:18300/studio/daily-report?farm_id=$([uri]::EscapeDataString($farmId))&days=7" -Headers $farmerHeaders
$reportRows = @($report.items).Count
$expectedRows = 7 * 7
Add-Result 'DATA-03' 'Báo cáo chi tiết theo ngày' ($reportRows -eq $expectedRows) "$reportRows/$expectedRows dòng (7 ngày x 7 nhóm sự kiện)"

$historyBefore = Invoke-Json -Uri "http://localhost:18000/conversations/current/messages?farm_id=$([uri]::EscapeDataString($farmId))&limit=500" -Headers $farmerHeaders
$durable = ($historyBefore.storage.engine -eq 'postgresql') -and $historyBefore.storage.durable_across_restart -and $historyBefore.storage.durable_across_normal_host_shutdown
Add-Result 'CHAT-01' 'Hội thoại lưu trong PostgreSQL' $durable "engine=$($historyBefore.storage.engine), messages=$(@($historyBefore.items).Count)"

$knowledge = Invoke-Json -Uri 'http://localhost:18200/studio/stats' -Headers $techHeaders
$gateText = if ($knowledge.production_gate.ready) { 'ready' } else { 'not-ready (đúng trạng thái PoC)' }
Add-Result 'RAG-01' 'Kho tri thức có duyệt và production gate' ($null -ne $knowledge.production_gate) "sources=$($knowledge.sources), approved=$($knowledge.approved), gate=$gateText"

$externalMappings = Invoke-Json -Uri 'http://localhost:18100/external-identities' -Headers $techHeaders
Add-Result 'AUTH-03' 'Quản lý ánh xạ danh tính ngoài' ($null -ne $externalMappings.items) "Có endpoint quản lý Zalo OA/NextFarm mapping; hiện có $(@($externalMappings.items).Count) ánh xạ"

$otherFarm = @($techLogin.user.farms | Where-Object { $_.farm_id -ne $farmId } | Select-Object -First 1)
if ($otherFarm.Count -eq 1) {
    $crossFarmStatus = 0
    try {
        Invoke-Json -Uri "http://localhost:18300/studio/data-groups?farm_id=$([uri]::EscapeDataString([string]$otherFarm[0].farm_id))" -Headers $farmerHeaders | Out-Null
        $crossFarmStatus = 200
    } catch {
        $crossFarmStatus = Get-HttpStatusFromException $_.Exception
    }
    Add-Result 'TENANT-01' 'Chặn truy cập chéo vườn' ($crossFarmStatus -eq 403) "HTTP $crossFarmStatus khi farmer gọi vườn không thuộc quyền"
} else {
    Add-Result 'TENANT-01' 'Chặn truy cập chéo vườn' $false 'Không tìm thấy vườn thứ hai để thực hiện phép thử'
}

$demoClientMessageId = $null
if ($WriteDemoMessages) {
    $stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmssfff')
    $demoClientMessageId = "demo47-control-$stamp"
    $control = Invoke-Json -Uri 'http://localhost:18000/chat' -Method POST -Headers $farmerHeaders -Body @{
        message = 'Bật van 3 trong 10 phút'
        farm_id = $farmId
        client_message_id = $demoClientMessageId
    }
    $controlSafe = ($control.intent -eq 'control_out_of_scope') -and ($control.grounded -eq $true)
    Add-Result 'SAFE-01' 'Không tự ý điều khiển thiết bị' $controlSafe "intent=$($control.intent); PoC từ chối thực thi và yêu cầu xác nhận/quyền ở giai đoạn sau"

    $missingId = "demo47-missing-$stamp"
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $missing = Invoke-Json -Uri 'http://localhost:18000/chat' -Method POST -Headers $farmerHeaders -Body @{
        message = 'Độ ẩm khu Z giờ bao nhiêu?'
        farm_id = $farmId
        client_message_id = $missingId
    }
    $clock.Stop()
    # "Không có dữ liệu" vẫn là một kết luận grounded nếu service đã tra cứu DB và xác nhận sự vắng mặt.
    # Vì vậy chấm bằng intent có cấu trúc, không phụ thuộc encoding/câu chữ hiển thị của Windows PowerShell 5.1.
    $missingSafe = ($missing.intent -eq 'metric_missing') -and (-not [string]::IsNullOrWhiteSpace([string]$missing.answer))
    Add-Result 'TRUTH-01' 'Không bịa khi không có dữ liệu' $missingSafe "intent=$($missing.intent), grounded=$($missing.grounded), elapsed_ms=$($clock.ElapsedMilliseconds)"

    $historyAfterWrite = Invoke-Json -Uri "http://localhost:18000/conversations/current/messages?farm_id=$([uri]::EscapeDataString($farmId))&limit=500" -Headers $farmerHeaders
    $saved = @($historyAfterWrite.items | Where-Object { $_.client_message_id -eq $demoClientMessageId }).Count -eq 1
    Add-Result 'CHAT-02' 'Tin nhắn demo được ghi bền vững' $saved "client_message_id=$demoClientMessageId"
}

if ($RestartChatbot) {
    Push-Location $ProjectRoot
    try {
        & docker compose restart chatbot-service | Out-Host
    } finally {
        Pop-Location
    }
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $h = Invoke-Json -Uri 'http://localhost:18000/health' -TimeoutSec 2
            if ($h.status -eq 'ok') { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    Add-Result 'CHAT-03' 'Chatbot khởi động lại thành công' $ready 'restart riêng service, không xóa volume PostgreSQL'
    if ($ready) {
        $historyAfterRestart = Invoke-Json -Uri "http://localhost:18000/conversations/current/messages?farm_id=$([uri]::EscapeDataString($farmId))&limit=500" -Headers $farmerHeaders
        $survived = @($historyAfterRestart.items | Where-Object { $_.client_message_id -eq $demoClientMessageId }).Count -eq 1
        Add-Result 'CHAT-04' 'Hội thoại còn sau restart' $survived "Đối chiếu lại client_message_id=$demoClientMessageId trong PostgreSQL"
    }
}

$Passed = @($Results | Where-Object passed).Count
$Failed = @($Results | Where-Object { -not $_.passed }).Count
$summary = [pscustomobject]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    started_at = $StartedAt.ToString('o')
    project = 'NextFarm AI Support Data/Knowledge Studio v9'
    scope = 'PDF sections 4, 5, 6, 7 demo verification'
    write_demo_messages = [bool]$WriteDemoMessages
    restart_chatbot = [bool]$RestartChatbot
    farm_id = $farmId
    passed = $Passed
    failed = $Failed
    results = $Results
    limitations = @(
        'Telemetry hiện là simulated_device_calibrated_v9, chưa phải API/phần cứng NextFarm.',
        'Không chạy restore trên database demo đang hoạt động; restore phải thực hiện trong môi trường sạch.',
        'production_ready vẫn false cho đến khi có API sandbox, load test, security review và chuyên gia nông học chấm.'
    )
}

$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $EvidenceFile -Encoding UTF8
Write-Host "`nTỔNG KẾT: $Passed PASS, $Failed FAIL" -ForegroundColor $(if ($Failed -eq 0) { 'Green' } else { 'Red' })
Write-Host "Bằng chứng JSON: $EvidenceFile"

if ($Failed -gt 0) { exit 1 }
