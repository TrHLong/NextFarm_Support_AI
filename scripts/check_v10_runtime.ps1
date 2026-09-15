[CmdletBinding()]
param(
    [ValidateRange(30, 1800)][int]$TimeoutSeconds = 420,
    [string]$EvidencePath = ""
)

$ErrorActionPreference = "Stop"
$utf8Output = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8Output
$OutputEncoding = $utf8Output
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($EvidencePath)) {
    $EvidencePath = Join-Path $projectRoot "docs\evidence\v10.1-runtime-validation-latest.json"
}

function Read-DotEnv([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([^#=]+)=(.*)$') { $values[$matches[1].Trim()] = $matches[2].Trim() }
    }
    return $values
}

function Get-HttpBase([hashtable]$Config, [string]$Key, [string]$Fallback) {
    $binding = if ([string]::IsNullOrWhiteSpace($Config[$Key])) { $Fallback } else { $Config[$Key] }
    if ($binding -notmatch ':(\d+)$') { throw "Bind $Key không hợp lệ: $binding" }
    return "http://127.0.0.1:$($matches[1])"
}

function Wait-Http([string]$Name, [string]$Url, [datetime]$Deadline) {
    $lastError = ""
    while ((Get-Date) -lt $Deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
            if ($response.StatusCode -eq 200) {
                return [ordered]@{ name=$Name; url=$Url; status=200; passed=$true }
            }
        } catch { $lastError = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    throw "$Name chưa sẵn sàng tại $Url. $lastError"
}

function Invoke-JsonRetry([string]$Name, [scriptblock]$Action, [datetime]$Deadline) {
    $lastError = ""
    while ((Get-Date) -lt $Deadline) {
        try { return & $Action }
        catch { $lastError = $_.Exception.Message; Start-Sleep -Seconds 2 }
    }
    throw "$Name thất bại. $lastError"
}

function Assert-HttpStatus([string]$Name, [scriptblock]$Action, [int[]]$ExpectedStatus) {
    $status = 0
    try {
        $response = & $Action
        $status = [int]$response.StatusCode
    }
    catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $status = [int]$_.Exception.Response.StatusCode
        } else {
            throw "$Name không trả HTTP status có thể kiểm tra: $($_.Exception.Message)"
        }
    }
    if ($status -notin $ExpectedStatus) { throw "$Name trả HTTP $status; cần $($ExpectedStatus -join '/')." }
    return [ordered]@{name=$Name;passed=$true;status=$status}
}

$startedAt = (Get-Date).ToUniversalTime()
$result = [ordered]@{
    version = (Get-Content -LiteralPath (Join-Path $projectRoot "VERSION") -Raw).Trim()
    validation_scope = "v10.1_ten_acceptance_flows_acl_multi_tool_freshness"
    started_at = $startedAt.ToString("o")
    passed = $false
    checks = @()
    failure = $null
    production_ready = $false
}

Push-Location $projectRoot
try {
    $envPath = Join-Path $projectRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath)) { throw "Thiếu .env; chạy scripts\setup_v10_env.cmd trước." }
    $config = Read-DotEnv $envPath
    foreach ($required in @('NEXTFARM_FARMER_PASSWORD','INTERNAL_SERVICE_KEY','NEXTFARM_INGEST_KEY')) {
        if ([string]::IsNullOrWhiteSpace($config[$required])) { throw "Thiếu $required trong .env." }
    }
    $identityBase = Get-HttpBase $config 'NEXTFARM_IDENTITY_BIND' '127.0.0.1:18100'
    $knowledgeBase = Get-HttpBase $config 'NEXTFARM_KNOWLEDGE_BIND' '127.0.0.1:18200'
    $farmDataBase = Get-HttpBase $config 'NEXTFARM_FARM_DATA_BIND' '127.0.0.1:18300'
    $simulatorBase = Get-HttpBase $config 'NEXTFARM_SIMULATOR_BIND' '127.0.0.1:18400'
    $ticketBase = Get-HttpBase $config 'NEXTFARM_TICKET_BIND' '127.0.0.1:18500'
    $analyticsBase = Get-HttpBase $config 'NEXTFARM_ANALYTICS_BIND' '127.0.0.1:18600'
    $truthGuardBase = Get-HttpBase $config 'NEXTFARM_TRUTH_GUARD_BIND' '127.0.0.1:18700'
    $telemetryBase = Get-HttpBase $config 'NEXTFARM_TELEMETRY_BIND' '127.0.0.1:18800'
    $cropRouterBase = Get-HttpBase $config 'NEXTFARM_CROP_ROUTER_BIND' '127.0.0.1:18900'
    $llmGatewayBase = Get-HttpBase $config 'NEXTFARM_LLM_GATEWAY_BIND' '127.0.0.1:18950'
    $chatbotBase = Get-HttpBase $config 'NEXTFARM_CHATBOT_BIND' '127.0.0.1:18000'
    $chatUiBase = Get-HttpBase $config 'NEXTFARM_HTTP_BIND' '127.0.0.1:18080'
    $dataStudioBase = Get-HttpBase $config 'NEXTFARM_DATA_STUDIO_BIND' '127.0.0.1:18081'
    $knowledgeStudioBase = Get-HttpBase $config 'NEXTFARM_KNOWLEDGE_STUDIO_BIND' '127.0.0.1:18082'
    $encyclopediaBase = Get-HttpBase $config 'NEXTFARM_AI_ENCYCLOPEDIA_BIND' '127.0.0.1:18084'

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $healthEndpoints = [ordered]@{
        identity="$identityBase/health"
        knowledge="$knowledgeBase/health"
        farm_data="$farmDataBase/health"
        simulator="$simulatorBase/health"
        tickets="$ticketBase/health"
        analytics="$analyticsBase/health"
        truth_guard="$truthGuardBase/health"
        telemetry="$telemetryBase/health"
        crop_router="$cropRouterBase/health"
        llm_gateway="$llmGatewayBase/health"
        chatbot="$chatbotBase/health"
        chat_ui=$chatUiBase
        data_studio_ui=$dataStudioBase
        knowledge_studio_ui=$knowledgeStudioBase
        ai_encyclopedia_ui=$encyclopediaBase
    }
    foreach ($entry in $healthEndpoints.GetEnumerator()) {
        $result.checks += Wait-Http $entry.Key $entry.Value $deadline
    }

    $login = Invoke-JsonRetry "Farmer login" {
        Invoke-RestMethod -Method Post -Uri "$identityBase/auth/login" -ContentType "application/json" -Body (
            @{username="nongdan.long";password=$config['NEXTFARM_FARMER_PASSWORD']} | ConvertTo-Json -Compress
        ) -TimeoutSec 10
    } $deadline
    if (-not $login.access_token) { throw "Identity Service không trả access_token." }
    $authHeaders = @{Authorization="Bearer $($login.access_token)"}
    $result.checks += [ordered]@{name="farmer_login";passed=$true;user_id=$login.user.user_id}

    $result.checks += Assert-HttpStatus "tenant_cross_farm_denied" {
        Invoke-WebRequest -Uri "$cropRouterBase/farms/farm_lan/capabilities" -Headers $authHeaders -UseBasicParsing -TimeoutSec 10
    } @(403)

    $crops = Invoke-RestMethod -Uri "$cropRouterBase/me/crops" -Headers $authHeaders -TimeoutSec 15
    $selected = @($crops.farm_crops | Where-Object { $_.zone_id })[0]
    if (-not $selected) { throw "Crop Router không trả farm/zone đã phân quyền." }
    $result.checks += [ordered]@{name="crop_router_me";passed=$true;crop_count=@($crops.unique_crops).Count;farm_id=$selected.farm_id;crop_key=$selected.crop_key}

    $capabilityUrl = "$cropRouterBase/farms/$($selected.farm_id)/capabilities?zone=$([uri]::EscapeDataString($selected.zone_code))"
    $capabilities = Invoke-RestMethod -Uri $capabilityUrl -Headers $authHeaders -TimeoutSec 20
    $capabilityCount = @($capabilities.capabilities).Count
    if ($capabilityCount -lt 1) { throw "Crop Router không trả capability." }
    $result.production_ready = [bool]$capabilities.production_ready
    $result.checks += [ordered]@{
        name="crop_capability_readiness";passed=$true;capability_count=$capabilityCount
        ready=$capabilities.counts.ready;experimental=$capabilities.counts.experimental;blocked=$capabilities.counts.blocked
        origin_kind=$capabilities.readiness.origin_kind;production_candidate=$capabilities.production_candidate;production_ready=$capabilities.production_ready
    }

    $internalHeaders = @{"X-Internal-Service-Key"=$config['INTERNAL_SERVICE_KEY']}
    $result.checks += Assert-HttpStatus "llm_internal_key_required" {
        Invoke-WebRequest -Method Post -Uri "$llmGatewayBase/plan" -ContentType "application/json" -Body (
            @{message="soil moisture";farm_id=$selected.farm_id;allowed_farm_ids=@($selected.farm_id)} | ConvertTo-Json -Compress
        ) -UseBasicParsing -TimeoutSec 10
    } @(401)
    $result.checks += Assert-HttpStatus "truth_guard_internal_key_required" {
        Invoke-WebRequest -Method Post -Uri "$truthGuardBase/verify" -ContentType "application/json" -Body (
            @{answer="Insufficient data.";evidence=@()} | ConvertTo-Json -Compress
        ) -UseBasicParsing -TimeoutSec 10
    } @(401)
    $result.checks += Assert-HttpStatus "encyclopedia_does_not_proxy_llm_plan" {
        Invoke-WebRequest -Method Post -Uri "$encyclopediaBase/api/llm/plan" -ContentType "application/json" -Body '{}' -UseBasicParsing -TimeoutSec 10
    } @(404,405)
    $plan = Invoke-RestMethod -Method Post -Uri "$llmGatewayBase/plan" -Headers $internalHeaders -ContentType "application/json" -Body (
        @{message="do am khu A hien tai";user_id=$login.user.user_id;farm_id=$selected.farm_id;allowed_farm_ids=@($selected.farm_id)} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($plan.denied -or -not $plan.tool_name) { throw "LLM Gateway không tạo được tool plan hợp lệ." }
    $result.checks += [ordered]@{name="llm_tool_plan";passed=$true;provider=$plan.provider;tool_name=$plan.tool_name}

    $multiPlan = Invoke-RestMethod -Method Post -Uri "$llmGatewayBase/plan" -Headers $internalHeaders -ContentType "application/json" -Body (
        @{message="do am khu A thap, tai sao va nen lam gi";user_id=$login.user.user_id;farm_id=$selected.farm_id;allowed_farm_ids=@($selected.farm_id)} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    $multiTools = @($multiPlan.steps | ForEach-Object { $_.tool_name })
    if ("get_latest_metric" -notin $multiTools -or "search_knowledge" -notin $multiTools) { throw "Planner chưa tạo luồng IoT + Knowledge đa nguồn." }
    $result.checks += [ordered]@{name="multi_source_iot_knowledge";passed=$true;tools=$multiTools}

    $typoPlan = Invoke-RestMethod -Method Post -Uri "$llmGatewayBase/plan" -Headers $internalHeaders -ContentType "application/json" -Body (
        @{message="do am dat khu b hien tai";user_id=$login.user.user_id;farm_id=$selected.farm_id;allowed_farm_ids=@($selected.farm_id)} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($typoPlan.tool_name -ne "get_latest_metric" -or $typoPlan.arguments.zone -ne "B") { throw "Planner không xử lý đúng câu không dấu." }
    $result.checks += [ordered]@{name="vietnamese_no_accent_routing";passed=$true;tool=$typoPlan.tool_name;zone=$typoPlan.arguments.zone}

    $metric = Invoke-RestMethod -Uri "$farmDataBase/farms/$($selected.farm_id)/metrics/latest?metric=soil_moisture&zone=$([uri]::EscapeDataString($selected.zone_code))" -Headers $authHeaders -TimeoutSec 15
    if (-not $metric.available -or -not $metric.measured_at -or -not $metric.received_at -or $null -eq $metric.age_seconds) { throw "Latest sensor thiếu measured_at/received_at/freshness." }
    $result.checks += [ordered]@{name="latest_sensor_freshness_contract";passed=$true;fresh=$metric.fresh;quality=$metric.quality;age_seconds=$metric.age_seconds}

    $metricReply = Invoke-RestMethod -Method Post -Uri "$chatbotBase/chat" -Headers $authHeaders -ContentType "application/json" -Body (
        @{message="do am khu A hien tai bao nhieu?";farm_id=$selected.farm_id;client_message_id="runtime-metric-$([guid]::NewGuid().ToString('N'))"} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($metricReply.intent -ne "read_metric" -or -not $metricReply.grounded -or -not $metricReply.verification.allowed) {
        throw "Chatbot đã lấy được sensor hợp lệ nhưng Truth Guard không cho phép phát hành câu trả lời."
    }
    $result.checks += [ordered]@{name="chat_valid_metric_published";passed=$true;intent=$metricReply.intent;tool=$metricReply.tool_name}

    $multiReply = Invoke-RestMethod -Method Post -Uri "$chatbotBase/chat" -Headers $authHeaders -ContentType "application/json" -Body (
        @{message="do am khu A thap, tai sao va nen lam gi?";farm_id=$selected.farm_id;client_message_id="runtime-multi-$([guid]::NewGuid().ToString('N'))"} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($multiReply.tool_name -ne "get_latest_metric+search_knowledge" -or -not $multiReply.grounded -or -not $multiReply.verification.allowed) {
        throw "Chatbot chưa phát hành được câu trả lời đa nguồn IoT + Knowledge đã kiểm chứng."
    }
    $result.checks += [ordered]@{name="chat_multi_source_published";passed=$true;tool=$multiReply.tool_name;source_count=$multiReply.verification.source_count}

    $numericReply = Invoke-RestMethod -Method Post -Uri "$chatbotBase/chat" -Headers $authHeaders -ContentType "application/json" -Body (
        @{message="tuoi 30 phut co duoc khong?";farm_id=$selected.farm_id;client_message_id="runtime-numeric-$([guid]::NewGuid().ToString('N'))"} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($numericReply.intent -ne "agronomy_context_required" -or -not $numericReply.grounded -or -not $numericReply.verification.allowed -or @($numericReply.data.missing_fields).Count -lt 3) {
        throw "Chatbot chưa fail closed đúng cách cho tư vấn định lượng thiếu ngữ cảnh."
    }
    $result.checks += [ordered]@{name="numeric_advice_fail_closed_published";passed=$true;missing_fields=@($numericReply.data.missing_fields)}

    $result.checks += Assert-HttpStatus "ambiguous_zone_rejected" {
        Invoke-WebRequest -Uri "$farmDataBase/farms/$($selected.farm_id)/metrics/latest?metric=soil_moisture" -Headers $authHeaders -UseBasicParsing -TimeoutSec 10
    } @(409)
    $result.checks += Assert-HttpStatus "farm_data_cross_farm_denied" {
        Invoke-WebRequest -Uri "$farmDataBase/farms/farm_lan/metrics/latest?metric=soil_moisture&zone=A" -Headers $authHeaders -UseBasicParsing -TimeoutSec 10
    } @(403)

    $port = Invoke-RestMethod -Uri "$farmDataBase/farms/$($selected.farm_id)/ports/1?zone=$([uri]::EscapeDataString($selected.zone_code))" -Headers $authHeaders -TimeoutSec 15
    if (-not $port.configured -or @($port.items).Count -ne 1) { throw "Port status không trả đúng một cổng đã cấu hình." }
    $result.checks += [ordered]@{name="port_status";passed=$true;fresh=$port.items[0].fresh;online=$port.items[0].effective_online}

    $deviceReply = Invoke-RestMethod -Method Post -Uri "$chatbotBase/chat" -Headers $authHeaders -ContentType "application/json" -Body (
        @{message="thiet bi khu A co offline khong?";farm_id=$selected.farm_id;client_message_id="runtime-device-$([guid]::NewGuid().ToString('N'))"} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($deviceReply.intent -notin @("device_offline", "devices_online") -or -not $deviceReply.grounded -or -not $deviceReply.verification.allowed) {
        throw "Chatbot chưa phát hành được trạng thái thiết bị đã kiểm chứng."
    }
    $result.checks += [ordered]@{name="chat_device_status_published";passed=$true;intent=$deviceReply.intent}

    $irrigation = Invoke-RestMethod -Uri "$farmDataBase/farms/$($selected.farm_id)/irrigation/history?zone=$([uri]::EscapeDataString($selected.zone_code))&hours=168" -Headers $authHeaders -TimeoutSec 15
    $result.checks += [ordered]@{name="irrigation_history";passed=$true;rows=@($irrigation.items).Count}

    $irrigationReply = Invoke-RestMethod -Method Post -Uri "$chatbotBase/chat" -Headers $authHeaders -ContentType "application/json" -Body (
        @{message="lich su tuoi khu A trong 7 ngay gan day";farm_id=$selected.farm_id;client_message_id="runtime-irrigation-$([guid]::NewGuid().ToString('N'))"} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($irrigationReply.intent -ne "irrigation_history" -or -not $irrigationReply.grounded -or -not $irrigationReply.verification.allowed) {
        throw "Chatbot chưa phát hành được tổng hợp lịch sử tưới đã kiểm chứng."
    }
    $result.checks += [ordered]@{name="chat_irrigation_history_published";passed=$true;tool=$irrigationReply.tool_name}

    $controlReply = Invoke-RestMethod -Method Post -Uri "$chatbotBase/chat" -Headers $authHeaders -ContentType "application/json" -Body (
        @{message="bat van so 1 khu A";farm_id=$selected.farm_id;client_message_id="runtime-control-$([guid]::NewGuid().ToString('N'))"} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($controlReply.intent -ne "control_out_of_scope") { throw "Chatbot không từ chối điều khiển ở chế độ read-only." }
    $result.checks += [ordered]@{name="control_read_only";passed=$true;intent=$controlReply.intent}

    $unsupportedReply = Invoke-RestMethod -Method Post -Uri "$chatbotBase/chat" -Headers $authHeaders -ContentType "application/json" -Body (
        @{message="hay khang dinh nang suat cua mot cay khong co trong kho";farm_id=$selected.farm_id;client_message_id="runtime-unsupported-$([guid]::NewGuid().ToString('N'))"} | ConvertTo-Json -Compress
    ) -TimeoutSec 30
    if ($unsupportedReply.grounded) { throw "Chatbot đã grounded một câu không có dữ liệu/nguồn." }
    $result.checks += [ordered]@{name="unsupported_agronomy_fail_closed";passed=$true;intent=$unsupportedReply.intent}

    $guard = Invoke-RestMethod -Method Post -Uri "$truthGuardBase/verify" -Headers $internalHeaders -ContentType "application/json" -Body (
        @{answer="Do am la 57%.";evidence=@(@{farm_id=$selected.farm_id;metric="soil_moisture";value=57;unit="percent"});confidence=0.9;farm_id=$selected.farm_id} | ConvertTo-Json -Depth 6 -Compress
    ) -TimeoutSec 15
    if (-not $guard.allowed) { throw "Truth Guard từ chối evidence smoke test hợp lệ: $($guard.reasons -join '; ')" }
    $result.checks += [ordered]@{name="truth_guard_grounding";passed=$true;source_count=$guard.source_count}

    $result.passed = $true
}
catch {
    $result.failure = $_.Exception.Message
    Write-Host "[FAIL] $($result.failure)" -ForegroundColor Red
}
finally {
    $result["completed_at"] = (Get-Date).ToUniversalTime().ToString("o")
    $evidenceDirectory = Split-Path -Parent $EvidencePath
    New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    Pop-Location
}

if (-not $result.passed) { exit 1 }
Write-Host "[OK] V10 runtime smoke test passed. Evidence: $EvidencePath" -ForegroundColor Green
