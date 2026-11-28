# digiRunner 設定：讓政府經過 digiRunner 呼叫 world-api

照這份文件做完，政府 client 會經過 digiRunner（API Gateway）呼叫 world-api，而且 digiRunner 會檢查身分：
政府只能用政府的路徑，**讀不到天災時間表**；前端只能讀 `/world/*`。
digiRunner 也會記下每一次呼叫，實驗跑完可以匯出成這個 run 的存取紀錄（見「匯出存取紀錄」）。

```
政府 client ──（用帳密換 token）──→ digiRunner :31080 ──→ world-api :8000 ──→ 模擬引擎
                                     檢查 token 和權限
```

**誰需要做：** 要測試「經過 digiRunner」的人，例如 API 組、前端要改成經過 digiRunner 時、跑正式實驗時。
平常寫程式、跑 pytest、`civsim run`、直連 world-api 都**不需要**。第一次大約 20 分鐘。

**每個人的 digiRunner 都是各自獨立的**：跑在自己電腦的 Docker 裡，只有自己的電腦連得到，帳號密碼也要自己設。

## 0. 準備

- 安裝並打開 **Docker Desktop**
- 專案更新到最新的 main
- 專案資料夾有 `.env`（從 `.env.example` 複製）
- 照平常的方式開 world-api，**不要**加 `--host 0.0.0.0`：

  ```powershell
  python -m civsim serve --config configs/baseline.yaml
  ```

  digiRunner 在 Docker 容器裡，用 `http://host.docker.internal:8000` 連 world-api。Docker Desktop 會把它轉到你電腦的本機，
  所以 world-api 只聽本機（預設）也連得到，不用對外開放。

設定和測試的過程中，**world-api 的終端機要一直開著**。

**Linux（沒有 Docker Desktop）**：`docker-compose.yml` 已經用 `extra_hosts` 把 `host.docker.internal` 指到主機，
但容器連過來的是 Docker 網橋的位址（通常是 `172.17.0.1`），不是本機的 `127.0.0.1`，所以 world-api 要聽那個位址：
`python -m civsim serve --config configs/baseline.yaml --host 172.17.0.1`（用 `ip addr show docker0` 查實際位址）。
不要用 `--host 0.0.0.0`，那會讓同一個網路的人都連得到 world-api。這段還沒有在 Linux 上實測過，遇到問題請回報。

## 1. 啟動 digiRunner

在專案資料夾：

```powershell
docker compose up -d dgr
```

等 1～2 分鐘（Java 程式啟動比較慢），打開管理後台：

**`http://localhost:31080/dgrv4/ac4/login`**（GitHub README 寫的 `/dgrv4/login` 少了 `ac4`，會 404）

預設帳號是官方 README 寫的 `manager` / `manager123`。

- `manager` 的密碼在「個人資料」改不了。想要自己的帳號，到「AC 權限管理」新增一個角色是 Administrator 的使用者
- **不要**對 `manager` 按「重設密碼」：新密碼會寄到 `manager` 的 email，那是 digiRunner 廠商的信箱

**設定會保存在哪：** `docker-compose.yml` 用的是官方的「永久資料庫」模式，設定存在 Docker 的 volume `dgrdb`，
關機、`docker compose stop`、`docker compose down` 都不會消失。**只有 `docker compose down -v` 會全部清空。**

`docker-compose.yml` 把 31080 只開放給本機（`127.0.0.1`），同一個網路的其他人連不到你的 digiRunner。

## 2. 匯入 world-api 的 9 條路徑

路徑已經做成匯入檔，不用一條一條手動註冊。

1. 左邊選單「**API管理**」→「**API列表**」→「**匯入API**」
2. 選 `deploy/digirunner/world-api-apis.json` → 上傳
3. 全選列出來的 9 條 → 按「**匯入**」
4. 「**API管理**」→「**API批量修改**」→ 全選 → 按「**啟動**」（匯入的路徑預設是停用的）

確認 9 條的狀態都是綠燈，而且 **No Auth 那一欄是空的**（不能不驗證就呼叫）。

| 路徑 | 給誰用 |
|---|---|
| `GET /runs` | 政府、前端 |
| `GET /runs/{p}/government/observation` | 政府 |
| `POST /runs/{p}/government/decisions` | 政府 |
| `GET /runs/{p}/government/reflections` | 政府 |
| `POST /runs/{p}/government/memory` | 政府 |
| `GET /world/state`、`/world/metrics`、`/world/events`、`/world/disasters` | 前端 |

路徑都用「預設模式（dgrc）」註冊，digiRunner 的路徑和 world-api 的路徑一模一樣，所以 client 只要把網址從
`localhost:8000` 換成 `localhost:31080`，其他都不用改。

## 3. 建立兩個群組

群組決定「可以用哪些路徑」。

「**用戶端管理**」→「**群組維護**」→「**建立**」

| 欄位 | 政府群組 | 前端群組 |
|---|---|---|
| 群組代碼 | `gov-group` | `frontend-group` |
| 允許使用時間 | `0`（不限制） | `0` |
| 授權次數上限 | `0`（不限制） | `0` |
| 安全等級 | System Security (default) | System Security (default) |
| 群組描述 | 政府 client 可用的路徑 | 前端 client 可用的路徑 |

選路徑分兩步：

1. 「**選擇 Module**」勾選模組（每條路徑自己就是一個模組，模組名稱就是路徑）
2. 每一列按「**選擇 API**」，勾選裡面那一條 API

| 群組 | 要選的 5 個模組 |
|---|---|
| `gov-group` | `/runs`，以及 4 條 `/runs/{p}/government/...` |
| `frontend-group` | `/runs`，以及 4 條 `/world/...` |

⚠️ **`gov-group` 不能有任何 `/world/*`**。`/world/disasters` 是天災時間表，政府讀得到就等於事先知道天災何時發生，
違反「不提供預報」的研究設計。

## 4. 建立兩個 client（帳號）

先產生密碼，同時寫進 `.env`（在專案資料夾執行，最後一行會印出密碼，填表單時複製它）。
兩個版本產生的密碼格式一樣：32 個字，只有英文字母、數字、`-`、`_`。

**Windows（PowerShell）**

```powershell
# 政府
$b = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $pw = [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_').TrimEnd('=')
Add-Content .env "`nDIGIRUNNER_CLIENT_ID=civsim-gov`nDIGIRUNNER_CLIENT_SECRET=$pw"
$pw
```

```powershell
# 前端（只在測試權限時用到）
$b = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $pw = [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_').TrimEnd('=')
Add-Content .env "`nDIGIRUNNER_FRONTEND_CLIENT_ID=civsim-frontend`nDIGIRUNNER_FRONTEND_CLIENT_SECRET=$pw"
$pw
```

**Mac / Linux（bash、zsh）**

```bash
# 政府
pw=$(head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')
printf '\nDIGIRUNNER_CLIENT_ID=civsim-gov\nDIGIRUNNER_CLIENT_SECRET=%s\n' "$pw" >> .env
echo "$pw"
```

```bash
# 前端（只在測試權限時用到）
pw=$(head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n')
printf '\nDIGIRUNNER_FRONTEND_CLIENT_ID=civsim-frontend\nDIGIRUNNER_FRONTEND_CLIENT_SECRET=%s\n' "$pw" >> .env
echo "$pw"
```

也可以不用指令，自己想一組密碼，手動在 `.env` 加上這兩行。用指令的好處是密碼夠隨機，而且直接寫進 `.env`，不會在複製時打錯字。

`.env` 不會被推上 GitHub。密碼不要貼到群組，截圖時也不要讓密碼入鏡。

上面的指令把帳密**加在 `.env` 的最後面**。`.env` 裡同一個名稱出現兩次時，civsim 和檢查腳本都**只讀第一個**，
所以如果你的 `.env` 前面已經有空白的 `DIGIRUNNER_CLIENT_ID=` 這類行（從舊版 `.env.example` 複製來的），要先刪掉，
否則讀到的會是空值。新版 `.env.example` 已經把這幾行註解掉了。

「**用戶端管理**」→「**用戶端維護**」→「**建立**」

| 欄位 | 政府 | 前端 |
|---|---|---|
| 用戶端帳號、用戶端代號 | `civsim-gov` | `civsim-frontend` |
| 用戶端名稱 | `civsim-gov` | `civsim-frontend` |
| 密碼、再次確認密碼 | 剛印出來的那組 | 剛印出來的那組 |
| 主機清單、開始日期、到期日期、服務時間 | **空白** | **空白** |
| API 配額 | `0`（不限制） | `0` |
| **TPS/Node** | **`0`（不限制）** | **`0`** |
| 擁有者、用戶優先權 | 預設 | 預設 |
| 狀態 | 啟用 | 啟用 |
| 開放狀態 | 對內 | 對內 |

- 帳號要和 `.env` 的 `DIGIRUNNER_CLIENT_ID` **一字不差**（連字號 `-`，不是底線 `_`）
- **TPS/Node 預設是 10**（每秒最多 10 次），`civsim govern` 會超過，一定要改成 0
- 主機清單要空白，填了的話只有那台主機能呼叫

## 5. 授權與 Token 設定

在「用戶端維護」的列表，按 client 那一列的「**安全性**」，對兩個 client 各做一次：

**授權設定** 分頁：按「**設定群組**」→ 在搜尋框輸入**群組代碼**（`gov` 或 `frontend`）→ 勾選 → 按「**更新**」

| client | 只加這一個群組 |
|---|---|
| `civsim-gov` | `gov-group` |
| `civsim-frontend` | `frontend-group` |

**Token 設定** 分頁：

| 欄位 | 設定 |
|---|---|
| OAuth Grant Type | **只留 Client Credentials**（取消 Refresh Token、Password、Authorization Code） |
| Access token expire | `1` 天 |
| 授權次數 | **`0`（不限制）**，有數字的話 token 用到那個次數就失效，run 會跑到一半中斷 |

按「**更新**」。「安全等級」維持 System Security，其他分頁不用動。

**打開存取紀錄**（整個 digiRunner 只要做一次）：「系統設定」→「Setting」→ 搜尋 `TSMP_APILOG_FORCE_WRITE_RDB`
→ 改成 **`true`** → 更新，不用重開 digiRunner。沒打開的話，digiRunner 不會保存任何呼叫紀錄，
跑完實驗也就沒辦法匯出（見「匯出存取紀錄」）。**打開之前的呼叫找不回來。**

## 6. 驗證

**檢查身分、權限與限流**（在專案資料夾，world-api 要**剛啟動**，run 還沒跑完）：

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File deploy/digirunner/check_auth.ps1
```

```bash
# Mac / Linux
bash deploy/digirunner/check_auth.sh
```

```
OK   1. 不帶 token 呼叫 /runs           擋下（401），預期擋下
OK   2. 政府呼叫政府的路徑               放行（200），預期放行
OK   3. 政府呼叫 /world/disasters       擋下（403），預期擋下
OK   4. 前端呼叫 /world/disasters       放行（200），預期放行
OK   5. 前端呼叫政府的路徑               擋下（403），預期擋下
OK   6. 政府連續呼叫 30 次             都放行，沒有被限流

全部符合預期
```

判斷規則：2xx 算「放行」，401／403 算「擋下」（digiRunner 擋的），**其他一律算「失敗」**，包括連不上、404、409。
腳本開始前會先確認 world-api 上有一個「還在等決策」的 run，沒有的話會直接停下來，請你重開 `civsim serve`，
因為 run 跑完之後政府的路徑會回 409，權限就測不到了。第 6 項是在確認 TPS/Node 有改成 0：預設的每秒 10 次會讓連續呼叫出現 429。

**經過 digiRunner 跑完整個 run**（world-api 剛啟動、還沒跑過的 run）：

```powershell
python -m civsim govern --base-url http://localhost:31080
```

最後兩行：

```
完成：共 214 天、反思 5 次，逾時後確認已送達 0 次
經過 digiRunner：以 client civsim-gov 申請 token 1 次
```

天數和天災次數依 `configs/baseline.yaml` 而定。

## 匯出存取紀錄

digiRunner 會記下每一次經過它的呼叫（要先做第 5 步的「打開存取紀錄」）。實驗跑完後，把這個 run 的紀錄匯出：

```powershell
python -m civsim export-access-log <run_id> --out runs/api/<run_id>
```

`run_id` 是 `civsim serve` 啟動時印出的那個；`--out` 是這個 run 的紀錄資料夾，會寫入裡面的 `digirunner_access.jsonl`。
（`civsim serve` 目前還不會自己存世界的紀錄，這部分還在做，先自己指定一個資料夾。）輸出範例：

```
run 20261129-a572：2 次經過 digiRunner 的呼叫（2026-11-29 01:41:02 ~ 2026-11-29 01:41:02）
  200     1 次  civsim-gov
  403     1 次  （被擋下）：Token Violates Scope Authorization Access Settings
已寫入 runs\api\20261129-a572\digirunner_access.jsonl
```

`digirunner_access.jsonl` 一行是一次呼叫：

| 欄位 | 意思 |
|---|---|
| `time` | digiRunner 收到請求的時間（台灣時間，只到秒） |
| `client_id` | 哪個 client 呼叫的；被 digiRunner 擋下的呼叫是 `null`（digiRunner 不記） |
| `api` | 註冊在 digiRunner 的路徑，例如 `/runs/{p}/government/observation` |
| `url` | 實際呼叫的網址，裡面有 run_id |
| `http_status` | 狀態碼 |
| `success` | digiRunner 判斷這次有沒有成功 |
| `elapsed_ms` | 花了多久（毫秒） |
| `error` | 被擋下或失敗的原因 |
| `log_id` | digiRunner 裡這筆紀錄的 ID |

- 只收網址裡有 `/runs/<run_id>/` 的呼叫，也就是政府的路徑。`GET /runs` 和換 token 的網址裡沒有 run_id，分不出是哪個 run，不收
- 紀錄只存在自己電腦 Docker 裡的 digiRunner，`docker compose down -v` 會清掉，所以**每次實驗跑完就匯出**
- 可以重複匯出，會用最新的結果覆蓋；但這次查到的筆數比檔案裡少時（digiRunner 的紀錄被刪過）不會覆蓋
- 怎麼讀到的：digiRunner 容器裡有它自己的資料庫服務（只有容器內部連得到），指令用 `docker exec` 在容器裡查詢，只讀不寫。
  digiRunner 會定時把紀錄從暫存表（`TSMP_REQ_LOG`、`TSMP_RES_LOG`）複製到歷史表（`TSMP_REQ_RES_LOG_HISTORY`），兩邊都會查
- 想**即時**看每次呼叫（除錯用）：「系統設定」→「Setting」把 `TSMP_ONLINE_CONSOLE` 改成 `true`，再到「系統設定」→「Online Console」，
  等級選 **DEBUG** 才看得到轉送的呼叫（`Src Url:` 開頭的行）。這頁只即時顯示、不會保存，也看不到是哪個 client，看完記得切回 INFO

## 政府 client 怎麼換 token

給要改 `src/civsim/gateway/client.py` 的人：

- 經過 digiRunner 時，第一個請求會收到 401，client 用 `.env` 的 `DIGIRUNNER_CLIENT_ID` / `DIGIRUNNER_CLIENT_SECRET`
  呼叫 `POST /oauth/token` 換 token，之後每個請求帶 `Authorization: Bearer <token>`
- 換 token 的 Basic 值是 **`Base64(帳號 + ":" + Base64(密碼))`**，密碼要先自己 Base64 一次，和一般的 HTTP Basic 不同
- token 預設 1 天過期，過期後收到 401 會自動重新申請
- 收到 403（這個 client 沒有權限）、帳密錯誤、換到的 token 仍被拒絕、token 回應不是 JSON → run 作廢。
  403 不重試，因為那是 digiRunner 的權限設定問題，重試也不會變；這點也寫進了 architecture.md
- 直連 world-api 時永遠不會收到 401，所以不會去申請 token
- 帳密用 `ClientCredentials` 包起來，密碼不會出現在 `repr()` 和錯誤訊息裡

## 已確認與還沒驗證的事

| 項目 | 狀態 |
|---|---|
| 9 條路徑的 `apiCacheFlag` 是 `"1"` | ✅ 已確認是**不快取**（digiRunner 原始碼：`"2"` 是自動快取、`"3"` 是固定快取），所以政府每天拿到的觀察都是最新的 |
| 政府 client 不被限流 | ✅ 檢查腳本第 6 項 |
| `X-Run-Id` 有沒有被 digiRunner 轉送給 world-api、有沒有寫進 digiRunner 的存取紀錄 | ⬜ **還沒驗證**，是第 3 週「存取紀錄對應到每個 run」的工作 |
| Linux 上的連線設定（第 0 步） | ⬜ 還沒在 Linux 上實測 |

## 常見問題

| 狀況 | 原因與解法 |
|---|---|
| 後台網址 404（Whitelabel Error Page） | 網址少了 `ac4`，用 `/dgrv4/ac4/login` |
| 註冊頁按「測試外部URL」回 500 | world-api 沒開，先 `civsim serve` |
| `Illegal character in path ... {rid}` | 目標 URL 的路徑參數寫錯。**目標 URL 和 Proxy Path 都要寫 `{p}`**，digiRunner 只會代換 `{p}`（官方文件範例寫 `{id}` 是錯的） |
| 列表或選擇頁面顯示「尚無資料」 | 很多頁面要先搜尋才會列出來；選群組時搜尋的是**群組代碼**，不是 client 名稱 |
| 「以 URL 上傳 OpenAPI 文件」按了沒反應 | 不支援，請用第 2 步的匯入檔 |
| 回應 401 | 沒帶 token 或 token 無效（digiRunner 擋的） |
| 回應 403 | token 有效，但這條路徑不在這個 client 的群組裡（digiRunner 擋的） |
| 回應 409、422、404 | 已經到 world-api 了，是 world-api 的規則，例如 run 已經跑完（重開 `civsim serve`） |
| 檢查腳本說「讀不到 /runs（500）」 | digiRunner 連不到 world-api：world-api 沒開，或 Linux 上 world-api 沒聽 Docker 網橋的位址 |
| 檢查腳本說「run 的狀態是 finished」 | 這個 run 已經跑完，重開 `civsim serve` 再檢查 |
| 檢查腳本說「第一個 … 是空的」 | `.env` 前面有空白的同名設定，刪掉它（見第 4 步） |
| `civsim govern` 不加 `--base-url` 卻連到 18080 | 舊版 `.env.example` 留下的 `DIGIRUNNER_BASE_URL=http://localhost:18080`，刪掉或改成 31080 |
| 換 token 失敗、帳密錯誤 | 檢查 `.env` 和後台的帳號是否一字不差；Token 設定是否勾了 Client Credentials |
| 忘記 client 密碼 | 打開 `.env` 看；或到「安全性 → 密碼管理」設新的，再改 `.env` |
| VS Code 裡按 Ctrl+C 停不掉 world-api | 按終端機的垃圾桶圖示，或 `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess` |
| 自己寫的 `.ps1` 中文變亂碼、怪錯誤 | Windows PowerShell 5.1 要用**帶 BOM 的 UTF-8** 存檔 |
| 匯出說「沒有 run … 的紀錄」 | run_id 打錯；`civsim govern` 沒加 `--base-url http://localhost:31080`（沒經過 digiRunner）；或跑的時候還沒打開存取紀錄（第 5 步） |
| 匯出說「找不到正在跑的 digiRunner」 | Docker Desktop 沒開，或 digiRunner 沒啟動（`docker compose up -d dgr`） |

## world-api 新增或修改路徑時

1. 在 digiRunner 註冊新路徑：「API管理」→「API註冊」，模式選「預設模式（dgrc）」，路徑參數兩邊都用 `{p}`；
   或在匯入檔複製一筆，改 `apiKey`、`moduleName`、`apiName`、`srcURL`、`enpoint`、`httpMethod`、`urlRID`（有 `{p}` 時為 `"1"`）
2. 把新路徑加進對應的群組
3. 更新 `deploy/digirunner/world-api-apis.json`：「API列表」選好路徑後「匯出」，確認 `no_oauth` 都是 `"0"` 再 commit

## 安全注意事項

- `.env` 有 LLM 金鑰和 client 密碼，**不能推上 GitHub**（這個 repo 是公開的）
- 所有路徑的 No Auth 都要關著，否則任何程式不帶 token 就能呼叫，包括讀天災時間表
- `civsim-gov` 永遠不能被授權 `frontend-group`
- digiRunner 和 world-api 都只開放給本機
- 前端在瀏覽器裡跑，如果要經過 digiRunner，帳密不能寫在前端程式碼裡，做法還在討論

## 參考

- [digiRunner 開源版](https://github.com/TPIsoftwareOSPO/digiRunner-Open-Source)
- [永久資料庫的 Docker Compose 設定](https://docs.tpi.dev/get-started/installation/docker-compose.md)
- [API Registry（dgrc 模式、`{p}`）](https://docs.tpi.dev/digirunner-open-source/guide/api-management/api-registry.md)
- [API Client（TPS、API 配額、Token 設定）](https://docs.tpi.dev/digirunner-open-source/guide/client-management/api-client.md)
- [Client Credentials Mode（換 token）](https://docs.tpi.dev/digirunner-open-source/api-integration-guide/using-token-for-authentication-and-authorization/client-credentials-mode.md)
