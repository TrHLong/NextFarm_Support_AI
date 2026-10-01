param(
    [switch]$ShowDemoPasswords
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root ".env"

function New-Secret {
    param([int]$Bytes)
    $buffer = [byte[]]::new($Bytes)
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    try {
        $rng.GetBytes($buffer)
    } finally {
        $rng.Dispose()
    }
    return ([Convert]::ToBase64String($buffer).TrimEnd("=") -replace "\+", "-" -replace "/", "_")
}

function Read-EnvFile {
    $values = [ordered]@{}
    $preserved = New-Object System.Collections.Generic.List[string]
    $known = @(
        "COMPOSE_PROJECT_NAME",
        "NEXTFARM_PG_VOLUME_NAME",
        "POSTGRES_PASSWORD",
        "TOKEN_SECRET",
        "INTERNAL_SERVICE_KEY",
        "NEXTFARM_TECH_PASSWORD",
        "NEXTFARM_FARMER_PASSWORD",
        "MQTT_INGEST_PASSWORD",
        "MQTT_SIMULATOR_PASSWORD",
        "NEXTFARM_INGEST_KEY",
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "LLM_TIMEOUT_SECONDS",
        "LLM_ENABLE_VERBALIZER",
        "DEVICE_AUTO_TRAIN",
        "CORS_ALLOW_ORIGINS",
        "NEXTFARM_POSTGRES_BIND",
        "NEXTFARM_MQTT_BIND",
        "NEXTFARM_IDENTITY_BIND",
        "NEXTFARM_KNOWLEDGE_BIND",
        "NEXTFARM_FARM_DATA_BIND",
        "NEXTFARM_SIMULATOR_BIND",
        "NEXTFARM_TICKET_BIND",
        "NEXTFARM_ANALYTICS_BIND",
        "NEXTFARM_TRUTH_GUARD_BIND",
        "NEXTFARM_TELEMETRY_BIND",
        "NEXTFARM_CROP_ROUTER_BIND",
        "NEXTFARM_LLM_GATEWAY_BIND",
        "NEXTFARM_CHATBOT_BIND",
        "NEXTFARM_HTTP_BIND",
        "NEXTFARM_DATA_STUDIO_BIND",
        "NEXTFARM_KNOWLEDGE_STUDIO_BIND",
        "NEXTFARM_AI_ENCYCLOPEDIA_BIND"
    )
    $knownSet = @{}
    foreach ($key in $known) { $knownSet[$key] = $true }

    if (-not (Test-Path -LiteralPath $EnvPath)) {
        return @{ Values = $values; Preserved = $preserved }
    }

    foreach ($raw in Get-Content -LiteralPath $EnvPath -Encoding UTF8) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            if ($line) { $preserved.Add($raw) }
            continue
        }
        $parts = $line.Split("=", 2)
        if ($knownSet.ContainsKey($parts[0])) {
            $values[$parts[0]] = $parts[1].Trim()
        } else {
            $preserved.Add($raw)
        }
    }
    return @{ Values = $values; Preserved = $preserved }
}

$fixed = [ordered]@{
    COMPOSE_PROJECT_NAME = "nextfarm_v10_crop_ai"
    NEXTFARM_PG_VOLUME_NAME = "nextfarm_v10_crop_ai_pg"
}

$secrets = [ordered]@{
    POSTGRES_PASSWORD = 24
    TOKEN_SECRET = 48
    INTERNAL_SERVICE_KEY = 48
    NEXTFARM_TECH_PASSWORD = 18
    NEXTFARM_FARMER_PASSWORD = 18
    MQTT_INGEST_PASSWORD = 24
    MQTT_SIMULATOR_PASSWORD = 24
    NEXTFARM_INGEST_KEY = 48
}

$defaults = [ordered]@{
    LLM_PROVIDER = "deterministic"
    OPENAI_API_KEY = ""
    OPENAI_MODEL = "gpt-5.6-luna"
    OPENAI_BASE_URL = "https://api.openai.com/v1"
    LLM_TIMEOUT_SECONDS = "20"
    LLM_ENABLE_VERBALIZER = "true"
    DEVICE_AUTO_TRAIN = "false"
    CORS_ALLOW_ORIGINS = "http://localhost:18080,http://localhost:18081,http://localhost:18082,http://localhost:18084"
    NEXTFARM_POSTGRES_BIND = "127.0.0.1:15432"
    NEXTFARM_MQTT_BIND = "127.0.0.1:11883"
    NEXTFARM_IDENTITY_BIND = "127.0.0.1:18100"
    NEXTFARM_KNOWLEDGE_BIND = "127.0.0.1:18200"
    NEXTFARM_FARM_DATA_BIND = "127.0.0.1:18300"
    NEXTFARM_SIMULATOR_BIND = "127.0.0.1:18400"
    NEXTFARM_TICKET_BIND = "127.0.0.1:18500"
    NEXTFARM_ANALYTICS_BIND = "127.0.0.1:18600"
    NEXTFARM_TRUTH_GUARD_BIND = "127.0.0.1:18700"
    NEXTFARM_TELEMETRY_BIND = "127.0.0.1:18800"
    NEXTFARM_CROP_ROUTER_BIND = "127.0.0.1:18900"
    NEXTFARM_LLM_GATEWAY_BIND = "127.0.0.1:18950"
    NEXTFARM_CHATBOT_BIND = "127.0.0.1:18000"
    NEXTFARM_HTTP_BIND = "127.0.0.1:18080"
    NEXTFARM_DATA_STUDIO_BIND = "127.0.0.1:18081"
    NEXTFARM_KNOWLEDGE_STUDIO_BIND = "127.0.0.1:18082"
    NEXTFARM_AI_ENCYCLOPEDIA_BIND = "127.0.0.1:18084"
}

$legacyPorts = @{
    CORS_ALLOW_ORIGINS = @("http://localhost:8080,http://localhost:8081,http://localhost:8082,http://localhost:8084", "http://localhost:18080,http://localhost:18081,http://localhost:18082,http://localhost:18084")
    NEXTFARM_HTTP_BIND = @("127.0.0.1:8080", "127.0.0.1:18080")
    NEXTFARM_DATA_STUDIO_BIND = @("127.0.0.1:8081", "127.0.0.1:18081")
    NEXTFARM_KNOWLEDGE_STUDIO_BIND = @("127.0.0.1:8082", "127.0.0.1:18082")
    NEXTFARM_AI_ENCYCLOPEDIA_BIND = @("127.0.0.1:8084", "127.0.0.1:18084")
}

$loaded = Read-EnvFile
$current = $loaded.Values
$preserved = $loaded.Preserved
$added = New-Object System.Collections.Generic.List[string]
$migrated = New-Object System.Collections.Generic.List[string]

foreach ($key in $secrets.Keys) {
    if (-not $current.Contains($key) -or [string]::IsNullOrWhiteSpace($current[$key])) {
        $current[$key] = New-Secret -Bytes $secrets[$key]
        $added.Add($key)
    }
}

foreach ($key in $fixed.Keys) {
    $current[$key] = $fixed[$key]
}

foreach ($key in $legacyPorts.Keys) {
    if ($current.Contains($key) -and $current[$key] -eq $legacyPorts[$key][0]) {
        $current[$key] = $legacyPorts[$key][1]
        $migrated.Add($key)
    }
}

foreach ($key in $defaults.Keys) {
    if (-not $current.Contains($key)) {
        $current[$key] = $defaults[$key]
    }
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# NextFarm V10 local config - DO NOT COMMIT OR SHARE")
foreach ($key in $fixed.Keys) { $lines.Add("$key=$($current[$key])") }
foreach ($key in $secrets.Keys) { $lines.Add("$key=$($current[$key])") }
$lines.Add("")
$lines.Add("# LLM configuration")
foreach ($key in $defaults.Keys) { $lines.Add("$key=$($current[$key])") }
if ($preserved.Count -gt 0) {
    $lines.Add("")
    $lines.Add("# Preserved custom values")
    foreach ($line in $preserved) { $lines.Add($line) }
}

[System.IO.File]::WriteAllText($EnvPath, ($lines -join [Environment]::NewLine) + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Write-Host "[OK] NextFarm V10 .env ready."
if ($added.Count -gt 0) {
    Write-Host ("[OK] Generated secrets: " + ($added -join ", "))
}
if ($migrated.Count -gt 0) {
    Write-Host ("[OK] Migrated V10 defaults away from legacy V9 ports: " + ($migrated -join ", "))
}
Write-Host "[TAI KHOAN DEMO]"
Write-Host "  Farmer usernames: nongdan.long / nongdan.lan / nongdan.minh"
Write-Host "  Technician      : kythuat.01"
if ($ShowDemoPasswords) {
    Write-Host ("  Farmer password : " + $current["NEXTFARM_FARMER_PASSWORD"])
    Write-Host ("  Technician pass : " + $current["NEXTFARM_TECH_PASSWORD"])
} else {
    Write-Host "  Passwords are stored in .env; use --show-demo-passwords only on a private terminal."
}
Write-Host ("[LLM] provider=" + $current["LLM_PROVIDER"] + ", model=" + $current["OPENAI_MODEL"])
Write-Host "[LUU Y] .env contains credentials. Do not send or commit it."
