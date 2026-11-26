# 檢查 digiRunner 的身分驗證、權限與限流設定（docs/digirunner_setup.md 的第 6 步）。
# 用法（在專案資料夾）：powershell -ExecutionPolicy Bypass -File deploy/digirunner/check_auth.ps1
# 需要：digiRunner 開著、world-api 剛啟動（run 還沒跑完）、.env 裡有兩個 client 的帳密。
# 密碼和 token 都不會印出來。Mac / Linux 用同一個資料夾的 check_auth.sh。
param([string]$BaseUrl = "http://localhost:31080")

$envFile = Join-Path $PSScriptRoot "..\..\.env"

# 讀設定的順序和 civsim 的 load_dotenv 相同：
#   1. 終端機裡已經設定的環境變數優先（例如 VS Code 開終端機時自動讀入的 .env，或自己用 $env: 設的）
#   2. 沒有的話才讀 .env：同一個名稱出現多次時取「第一個」，去掉前後空白，再去掉兩端的 " 和 '
function EnvGet($name) {
    $value = [Environment]::GetEnvironmentVariable($name)
    $from = "環境變數"
    if ($null -eq $value) {
        $from = ".env"
        $line = if (Test-Path $envFile) {
            Get-Content $envFile | Where-Object { $_ -match "^\s*$name\s*=" } | Select-Object -First 1
        }
        $value = if ($line) { $line.Split('=', 2)[1].Trim().Trim('"').Trim("'") } else { "" }
    }
    $value = $value.Trim()
    if (-not $value) {
        Write-Host "找不到 $name，或它是空的（目前讀的是$from；.env 裡同名的設定只會讀第一個）"
        exit 1
    }
    $value
}

# 回傳 HTTP 狀態碼；連不上、逾時這類沒有 HTTP 回應的情況回傳 0
function Get-Status($url, $token) {
    $headers = @{}
    if ($token) { $headers.Authorization = "Bearer $token" }
    try {
        (Invoke-WebRequest $url -Headers $headers -UseBasicParsing -TimeoutSec 10).StatusCode
    } catch {
        $r = $_.Exception.Response
        if ($r) { [int]$r.StatusCode } else { 0 }
    }
}

# digiRunner 的 Client Credentials：Basic Base64(帳號 + ":" + Base64(密碼))
function Get-Token($id, $secret) {
    $inner = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($secret))
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${id}:$inner"))
    try {
        $resp = Invoke-RestMethod -Method Post "$BaseUrl/oauth/token" -Headers @{ Authorization = "Basic $basic" } `
            -ContentType "application/x-www-form-urlencoded" -Body "grant_type=client_credentials" -TimeoutSec 10
    } catch {
        $r = $_.Exception.Response
        if (-not $r) { Write-Host "連不到 digiRunner（$BaseUrl）：Docker 和 digiRunner 有開嗎？"; exit 1 }
        Write-Host "client $id 換 token 失敗（$([int]$r.StatusCode)）：檢查 .env 的帳密，以及 Token 設定是否勾了 Client Credentials"
        exit 1
    }
    if (-not $resp.access_token) { Write-Host "client $id 的 token 回應裡沒有 access_token"; exit 1 }
    $resp.access_token
}

# 2xx = 放行；401 / 403 = digiRunner 擋下；其他（沒有回應、404、409、5xx…）= 失敗，代表沒測到權限
$script:failed = 0
function Test-Call($label, $url, $token, $expect) {
    $code = Get-Status $url $token
    if ($code -ge 200 -and $code -lt 300) { $result = "放行" }
    elseif ($code -eq 401 -or $code -eq 403) { $result = "擋下" }
    else { $result = "失敗" }
    $mark = if ($result -eq $expect) { "OK " } else { "NG!"; $script:failed++ }
    $detail = if ($code -eq 0) { "沒有回應" } else { $code }
    "{0}  {1,-30} {2}（{3}），預期{4}" -f $mark, $label, $result, $detail, $expect
}

$gov = Get-Token (EnvGet "DIGIRUNNER_CLIENT_ID") (EnvGet "DIGIRUNNER_CLIENT_SECRET")
$fe = Get-Token (EnvGet "DIGIRUNNER_FRONTEND_CLIENT_ID") (EnvGet "DIGIRUNNER_FRONTEND_CLIENT_SECRET")

# 先確認 world-api 上有一個還在等決策的 run，否則政府路徑的權限測不到
try {
    # 先存進變數再取第一個：Windows PowerShell 5.1 的 Invoke-RestMethod 會把整個 JSON 陣列當成一個東西輸出，
    # 直接用 @(Invoke-RestMethod ...) 包起來，有 2 個以上 run 時 [0] 會拿到整個陣列
    $runs = Invoke-RestMethod "$BaseUrl/runs" -Headers @{ Authorization = "Bearer $gov" } -TimeoutSec 10
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "沒有回應" }
    Write-Host "政府 client 讀不到 /runs（$code）：world-api 有開嗎？gov-group 有包含 /runs 嗎？"
    exit 1
}
$run = @($runs)[0]
if (-not $run -or -not $run.run_id) { Write-Host "world-api 上沒有 run，請先用 civsim serve 建立"; exit 1 }
$rid = $run.run_id
if ($run.status -ne "awaiting_decision") {
    Write-Host "run $rid 的狀態是 $($run.status)，政府的路徑測不到。請重開 civsim serve，拿一個新的 run 再檢查"
    exit 1
}
"兩個 client 都換到 token 了，目前的 run_id：$rid"
""
Test-Call "1. 不帶 token 呼叫 /runs" "$BaseUrl/runs" $null "擋下"
Test-Call "2. 政府呼叫政府的路徑" "$BaseUrl/runs/$rid/government/observation" $gov "放行"
Test-Call "3. 政府呼叫 /world/disasters" "$BaseUrl/world/disasters" $gov "擋下"
Test-Call "4. 前端呼叫 /world/disasters" "$BaseUrl/world/disasters" $fe "放行"
Test-Call "5. 前端呼叫政府的路徑" "$BaseUrl/runs/$rid/government/observation" $fe "擋下"
Test-Call "6. 前端呼叫 /runs" "$BaseUrl/runs" $fe "放行"

# 7. 政府 client 不能被限流（TPS/Node 要設 0）：連續送 30 次，不能出現 429
$codes = 1..30 | ForEach-Object { Get-Status "$BaseUrl/runs" $gov }
$limited = @($codes | Where-Object { $_ -eq 429 }).Count
$other = @($codes | Where-Object { $_ -lt 200 -or $_ -ge 300 }).Count
if ($other -eq 0) { "OK   7. 政府連續呼叫 30 次             都放行，沒有被限流" }
else { "NG!  7. 政府連續呼叫 30 次             有 $other 次沒有放行（其中 429 被限流 $limited 次）：TPS/Node 要設 0"; $script:failed++ }

""
if ($script:failed) { "有 $($script:failed) 項和預期不同，對照 docs/digirunner_setup.md 的「常見問題」"; exit 1 }
"全部符合預期"
