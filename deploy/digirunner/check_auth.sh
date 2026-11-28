#!/usr/bin/env bash
# 檢查 digiRunner 的身分驗證、權限與限流設定（docs/digirunner_setup.md 的第 6 步）。Mac / Linux 用，規則和 check_auth.ps1 相同。
# 用法（在專案資料夾）：bash deploy/digirunner/check_auth.sh [digiRunner 網址，預設 http://localhost:31080]
# 需要：digiRunner 開著、world-api 剛啟動（run 還沒跑完）、.env 裡有兩個 client 的帳密。密碼和 token 都不會印出來。
set -u
BASE_URL="${1:-http://localhost:31080}"
ENV_FILE="$(cd "$(dirname "$0")/../.." && pwd)/.env"

trim() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

# 讀設定的順序和 civsim 的 load_dotenv 相同：
#   1. 終端機裡已經設定的環境變數優先
#   2. 沒有的話才讀 .env：同一個名稱出現多次時取「第一個」，去掉前後空白，再去掉兩端的 " 和 '
#      （和 Python 的 strip('"').strip("'") 一樣，單邊的引號也會去掉）
env_get() {
  local v from
  if v=$(printenv "$1"); then
    from="環境變數"
  else
    from=".env"
    v=""
    if [ -f "$ENV_FILE" ]; then
      v=$(grep -m1 -E "^[[:space:]]*$1[[:space:]]*=" "$ENV_FILE" | cut -d= -f2- | tr -d '\r' | trim |
          sed -e 's/^"*//' -e 's/"*$//' -e "s/^'*//" -e "s/'*\$//")
    fi
  fi
  v=$(printf '%s' "$v" | trim)
  if [ -z "$v" ]; then
    echo "找不到 $1，或它是空的（目前讀的是$from；.env 裡同名的設定只會讀第一個）" >&2
    return 1
  fi
  printf '%s' "$v"
}

b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

# 回傳 HTTP 狀態碼；連不上、逾時這類沒有 HTTP 回應的情況回傳 000
status_of() {
  local auth=()
  [ -n "${2:-}" ] && auth=(-H "Authorization: Bearer $2")
  curl -s -o /dev/null -m 10 -w '%{http_code}' ${auth[@]+"${auth[@]}"} "$1"
}

# digiRunner 的 Client Credentials：Basic Base64(帳號 + ":" + Base64(密碼))
get_token() {
  local basic resp code body token
  basic=$(b64 "$1:$(b64 "$2")")
  resp=$(curl -s -m 10 -w $'\n%{http_code}' -X POST "$BASE_URL/oauth/token" \
    -H "Authorization: Basic $basic" -H "Content-Type: application/x-www-form-urlencoded" \
    -d grant_type=client_credentials)
  code=${resp##*$'\n'}
  body=${resp%$'\n'*}
  if [ "$code" = "000" ]; then echo "連不到 digiRunner（$BASE_URL）：Docker 和 digiRunner 有開嗎？" >&2; return 1; fi
  if [ "$code" != "200" ]; then
    echo "client $1 換 token 失敗（$code）：檢查 .env 的帳密，以及 Token 設定是否勾了 Client Credentials" >&2
    return 1
  fi
  token=$(printf '%s' "$body" | grep -o '"access_token" *: *"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/')
  [ -n "$token" ] || { echo "client $1 的 token 回應裡沒有 access_token" >&2; return 1; }
  printf '%s' "$token"
}

# 2xx = 放行；401 / 403 = digiRunner 擋下；其他（沒有回應、404、409、5xx…）= 失敗，代表沒測到權限
failed=0
test_call() {
  local code result mark detail
  code=$(status_of "$2" "${3:-}")
  case "$code" in
    2??) result="放行" ;;
    401|403) result="擋下" ;;
    *) result="失敗" ;;
  esac
  if [ "$result" = "$4" ]; then mark="OK "; else mark="NG!"; failed=$((failed + 1)); fi
  if [ "$code" = "000" ]; then detail="沒有回應"; else detail="$code"; fi
  echo "$mark  $1：$result（$detail），預期$4"
}

GOV_ID=$(env_get DIGIRUNNER_CLIENT_ID) || exit 1
GOV_SECRET=$(env_get DIGIRUNNER_CLIENT_SECRET) || exit 1
FE_ID=$(env_get DIGIRUNNER_FRONTEND_CLIENT_ID) || exit 1
FE_SECRET=$(env_get DIGIRUNNER_FRONTEND_CLIENT_SECRET) || exit 1
GOV=$(get_token "$GOV_ID" "$GOV_SECRET") || exit 1
FE=$(get_token "$FE_ID" "$FE_SECRET") || exit 1

# 先確認 world-api 上有一個還在等決策的 run，否則政府路徑的權限測不到
resp=$(curl -s -m 10 -w $'\n%{http_code}' -H "Authorization: Bearer $GOV" "$BASE_URL/runs")
code=${resp##*$'\n'}
runs=${resp%$'\n'*}
if [ "$code" != "200" ]; then
  echo "政府 client 讀不到 /runs（$code）：world-api 有開嗎？gov-group 有包含 /runs 嗎？"
  exit 1
fi
RID=$(printf '%s' "$runs" | grep -o '"run_id" *: *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
STATUS=$(printf '%s' "$runs" | grep -o '"status" *: *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
if [ -z "$RID" ]; then echo "world-api 上沒有 run，請先用 civsim serve 建立"; exit 1; fi
if [ "$STATUS" != "awaiting_decision" ]; then
  echo "run $RID 的狀態是 $STATUS，政府的路徑測不到。請重開 civsim serve，拿一個新的 run 再檢查"
  exit 1
fi
echo "兩個 client 都換到 token 了，目前的 run_id：$RID"
echo
test_call "1. 不帶 token 呼叫 /runs" "$BASE_URL/runs" "" "擋下"
test_call "2. 政府呼叫政府的路徑" "$BASE_URL/runs/$RID/government/observation" "$GOV" "放行"
test_call "3. 政府呼叫 /world/disasters" "$BASE_URL/world/disasters" "$GOV" "擋下"
test_call "4. 前端呼叫 /world/disasters" "$BASE_URL/world/disasters" "$FE" "放行"
test_call "5. 前端呼叫政府的路徑" "$BASE_URL/runs/$RID/government/observation" "$FE" "擋下"
test_call "6. 前端呼叫 /runs" "$BASE_URL/runs" "$FE" "放行"

# 7. 政府 client 不能被限流（TPS/Node 要設 0）：連續送 30 次，不能出現 429
other=0
limited=0
for _ in $(seq 1 30); do
  c=$(status_of "$BASE_URL/runs" "$GOV")
  case "$c" in 2??) ;; *) other=$((other + 1)) ;; esac
  [ "$c" = "429" ] && limited=$((limited + 1))
done
if [ "$other" -eq 0 ]; then
  echo "OK   7. 政府連續呼叫 30 次：都放行，沒有被限流"
else
  echo "NG!  7. 政府連續呼叫 30 次：有 $other 次沒有放行（其中 429 被限流 $limited 次），TPS/Node 要設 0"
  failed=$((failed + 1))
fi

echo
if [ "$failed" -gt 0 ]; then echo "有 $failed 項和預期不同，對照 docs/digirunner_setup.md 的「常見問題」"; exit 1; fi
echo "全部符合預期"
