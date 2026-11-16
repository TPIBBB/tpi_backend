# world-api 格式（草案）

> **狀態：草案，等各組確認。** 標 🟡 的地方是還沒定案的決定，每一項都附上建議方案和要找誰確認。
> 沒有異議就照建議方案實作。負責人：API 組。

本文件定義政府 client、前端與 world-api 之間的 HTTP 格式。
實作在 `src/civsim/api/`，啟動後打開 `http://localhost:8000/docs` 可以看到自動產生的互動式文件，並直接測試。

## ⚠️ 和 architecture.md 不同：改用 lockstep，不使用原本的「暫停等待」設計

[architecture.md](architecture.md) 的「執行模式與 digiRunner」原本寫的是：

> world-api 自己跑回合迴圈，輪到政府決策時暫停，等 `POST /government/decisions` 送來才繼續；
> 政府 client 輪詢 `GET /government/observation`。不需要政府決策的回合由 world-api 直接跑完。

**本文件改用 lockstep（輪流制）：world-api 不自己跑迴圈，政府每送一次決策，世界就前進一天。政府沒送，世界就停著等。**

```
原本的設計（不採用）：世界在背景自己跑 → 輪到政府時停住 → 收到決策 → 繼續跑
lockstep（採用）：   政府 GET 觀察 → 政府 POST 決策 → 世界跑完這一天 → 政府 GET 下一天的觀察 → …
```

**為什麼改：**

1. **原本設計的前提已經改了。** 原本政府只在天災前後決策，平常的日子 world-api 要自己跑完，所以需要背景迴圈。
   11/10 確認政府每天都決策，世界每天都要停下來等政府，背景迴圈就沒有用了。
2. **少掉最難的部分。** 背景迴圈要處理執行緒、等待、逾時、競態條件；lockstep 下 world-api 只是收到請求就跑一天，沒有任何背景工作。
3. **對政府 client 幾乎沒有影響。** 兩種設計的用法都是「GET 觀察 → POST 決策」，差別在 world-api 內部。
4. **原本的設計還沒有實作** 

不變的部分：只有政府走 API，平民仍在 world-api 內部計算；路徑仍預留 `run_id`；基礎設施錯誤的處理方式照 architecture.md（見「政府 client 的規則」）。

architecture.md 的那一段要同步改成指向本文件。

## 決定總覽

| # | 決定 | 建議方案 | 要找誰確認 | 狀態 |
|---|---|---|---|---|
| D1 | 執行模式 | lockstep（見上方） | 全組 | 🟡 |
| D2 | 怎麼知道現在該做什麼 | 每個回應都帶 `status` 欄位 | Agent組  | 🟡 |
| D3 | 避免重送決策讓世界多跑一天 | 送決策時要帶 `tick`，對不上就拒絕 | Agent 組 | 🟡 |
| D4 | 決策被引擎拒絕時的回應 | HTTP 200，拒絕理由放在回應裡 | Agent 組 | 🟡 |
| D5 | 送出決策後回傳什麼 | 當天的結算摘要，不回下一天的觀察 | Agent 組 | 🟡 |
| D6 | 反思流程 | 評估期最後一天後進入 `awaiting_reflection`，等記憶送來才重置 | **社會規則組（已改 engine.py）** | 🟡 已實作 |
| D7 | run 怎麼建立 | 第一版一個 world-api 只跑一個 run，啟動時產生 `run_id` | 實驗分析組 | 🟡 |
| D8 | 身分驗證 | 交給 digiRunner，world-api 本身不檢查 | 全組 | 🟡 |
| D9 | `/admin/step` 在 API 模式下 | 停用，回 409 | 前端組 | 🟡 |
| D10 | `/world/*` 的欄位 | 由前端組決定 | 前端組 | 🟡 |

## 基本約定

- 格式一律是 JSON，編碼 UTF-8。
- 數字都是一般的 JSON 數字（不是字串）。
- 時間單位是 **tick（天）**，從 0 開始。
- base URL：
  - 直連（開發用）：`http://localhost:8000`
  - 經過 digiRunner：依 digiRunner 的設定，政府 client 用環境變數 `DIGIRUNNER_BASE_URL` 切換，程式不用改
- 每個請求都建議帶 header `X-Run-Id: <run_id>`，讓 digiRunner 的存取紀錄能和模擬紀錄對應。

## 狀態（D2）

🟡 **建議：world-api 隨時處在三種狀態之一，政府相關的回應都帶 `status` 欄位。** 政府 client 看 `status` 就知道下一步要做什麼，不用自己數天數。

| `status` | 意思 | 政府 client 下一步 |
|---|---|---|
| `awaiting_decision` | 等政府送今天的決策 | `GET observation` → `POST decisions` |
| `awaiting_reflection` | 一次天災的評估期剛結束，等政府送新版記憶 | `GET reflections` → `POST memory` |
| `finished` | 整個 run 跑完了 | 停止 |

```
                 POST decisions（不是評估期最後一天）
                ┌──────────────┐
                ▼              │
        ┌───────────────────────┐   POST decisions（評估期最後一天）  ┌───────────────────────┐
開始 ──→│  awaiting_decision    │ ──────────────────────────────────→│  awaiting_reflection  │
        └───────────────────────┘ ←──────────────────────────────────└───────────────────────┘
                │                     POST memory（世界調回均衡狀態）
                │ 最後一天跑完
                ▼
        ┌───────────────────────┐
        │       finished        │
        └───────────────────────┘
```

無記憶組（`government.memory: false`，A 組）不會進入 `awaiting_reflection`，評估期結束後直接重置，繼續 `awaiting_decision`。

## 政府路徑

只有政府的身分可以呼叫（由 digiRunner 控管，見 D8）。

### `GET /runs/{run_id}/government/observation`

取得政府今天看得到的內容。**可以重複呼叫**，同一天呼叫幾次都回一樣的內容，世界不會因此前進。

只有 `status = awaiting_decision` 時可以呼叫，其他狀態回 409。

**回應 200：**

```json
{
  "run_id": "20261111-a3f9",
  "status": "awaiting_decision",
  "observation": {
    "tick": 37,
    "prices": {"food": 9.84},
    "memory": "# 經驗\n- 天災時拋售儲備能壓住價格（天災 1、2）\n",
    "rules": ["[禁止] 不能亂殺平民", "[禁止] 不能發行貨幣"],
    "budget": 1000.0,
    "food_reserve": 100.0,
    "population": 40,
    "deaths": 0,
    "hungry": 5,
    "price_cap": null,
    "citizens": [
      {"id": "c00", "type": "producer_trader"},
      {"id": "c01", "type": "consumer"}
    ],
    "recent_decisions": [
      {
        "tick": 36, "type": "release_reserve", "params": {"qty": 30}, "reason": "壓低糧價",
        "accepted": true, "result": {"qty": 30.0, "limit": 0.0}
      },
      {
        "tick": 35, "type": "issue_currency", "params": {"amount": 500}, "reason": "補預算",
        "accepted": false, "rejected_reason": "違反社會規則：不能發行貨幣"
      }
    ]
  }
}
```

`observation` 的欄位就是引擎的 `GovernmentObservation`（[src/civsim/world/government.py](../src/civsim/world/government.py)），欄位意義：

| 欄位 | 意義 |
|---|---|
| `tick` | 今天是第幾天。**送決策時要原樣帶回去**（D3） |
| `prices` | 昨天的成交價，目前只有 `food` |
| `memory` | 政府的記憶（Markdown）；無記憶組是 `null` |
| `rules` | 社會規則；B 組（`record` 模式）是空陣列，政府看不到規則 |
| `budget`、`food_reserve` | 政府的預算與糧食儲備 |
| `population`、`deaths` | 活著的人數、這次天災週期內的死亡人數 |
| `hungry` | 昨天沒得吃的人數 |
| `price_cap` | 目前生效的價格上限 `{"price": 12.0, "until": 40}`，沒有就是 `null` |
| `citizens` | 平民的 id 與類型（**不含**存糧與存款） |
| `recent_decisions` | 這次天災週期內最近 20 筆決策與結果，被拒絕的有 `rejected_reason` |

政府**看不到**：平民的存糧與存款、天災時間表、這個週期的第幾天（11/9 會議決定，不提供預報）。

### `POST /runs/{run_id}/government/decisions`

送出今天的決策，**世界會跑完這一天**。

**請求：**

```json
{
  "tick": 37,
  "actions": [
    {"type": "release_reserve", "params": {"qty": 30}, "reason": "天災後價格偏高，拋售儲備"}
  ]
}
```

- `tick`：必填，必須等於目前的 tick（D3）。
- `actions`：決策清單。**不想行動就送空陣列 `[]`** 或 `[{"type": "idle"}]`。
- 一天只能有一個決策（`max_decisions_per_day: 1`）。送超過一個**不會**被 API 擋下，會交給引擎處理：第一個照常執行，其餘記成「超過每天的決策上限」被拒絕，政府隔天在 `recent_decisions` 看得到。這是研究資料的一部分，所以不在 HTTP 層擋。
- 可用的 `type` 和 `params` 見 [society.md 的「政府的行動」](society.md#政府的行動worldgovernmentpy)。參數合不合法由引擎檢查，不在 HTTP 層檢查。

**回應 200（D5）：**

```json
{
  "run_id": "20261111-a3f9",
  "tick": 37,
  "decisions": [
    {
      "type": "release_reserve", "params": {"qty": 30}, "reason": "天災後價格偏高，拋售儲備",
      "accepted": true, "result": {"qty": 30.0, "limit": 0.0}
    }
  ],
  "price": 9.12,
  "status": "awaiting_decision",
  "next_tick": 38
}
```

| 欄位 | 意義 |
|---|---|
| `tick` | 剛跑完的是哪一天 |
| `decisions` | 每個決策的結果，格式和 `recent_decisions` 相同 |
| `price` | 今天的成交價 |
| `status` | 跑完這一天後的狀態。評估期最後一天會是 `awaiting_reflection` |
| `next_tick` | 下一個要決策的 tick；`status` 不是 `awaiting_decision` 時是 `null` |

🟡 **D5 建議：只回當天的結算摘要，不順便回下一天的觀察。** 觀察只有 `GET observation` 一個來源，格式只要維護一份。代價是每天多一次請求，本機開發可以忽略不計。

### 🟡 D3：為什麼送決策要帶 `tick`

lockstep 下，**每次 POST 都會讓世界前進一天**。如果政府 client 送出後逾時，自動重試，就可能同一個決策被執行兩次，世界多跑一天，而且沒人發現。

帶上 `tick` 後，world-api 會檢查它是不是今天：

- 等於目前的 tick → 執行
- 不等於 → 回 **409**，世界不動

重試時 client 會收到 409，這時重新 `GET observation`，就能知道世界現在在哪一天。

### 🟡 D4：決策被引擎拒絕，不是 HTTP 錯誤

要分清楚兩種「失敗」：

| | 例子 | 回應 |
|---|---|---|
| **請求本身有問題** | JSON 格式錯、少了 `tick`、run 不存在、狀態不對 | HTTP 4xx，**世界不動** |
| **決策被引擎拒絕** | 預算不足、違反社會規則、參數超出範圍、未知的決策類型 | **HTTP 200**，世界照常跑完這一天，拒絕理由放在 `decisions[].rejected_reason` |

決策被拒絕是**實驗的一部分**：政府隔天會在 `recent_decisions` 看到理由，研究也要記錄政府做了什麼被拒絕的事。如果在 HTTP 層就擋掉，這些資料就不見了。

**例外：** `type` 不在決策清單裡（例如 LLM 打錯字送了 `"distribut_food"`）也是 200，那筆決策在回應裡標為被拒絕。理由同上：這是政府的行為，不是 client 的程式錯誤。
它不會交給引擎，所以**隔天的 `recent_decisions` 看不到**，這和本機模式（`agents/government.py` 的 `parse_decisions` 直接略過未知類型）一致。

## 反思路徑（D6）

> 🟡 **已實作，但改到了社會規則負責的 `world/engine.py`（模擬引擎），請社會規則確認。**
> 反思與記憶由 Agent 負責，這裡沒有改到 `agents/`，但政府經 API 反思的流程是新的，請 Agent 知悉。
>
> 本機模式下，引擎在評估期最後一天產生天災報告後，馬上呼叫本機政府的 `reflect()`，接著把世界調回均衡狀態。
> API 模式下政府在 HTTP 的另一端，沒辦法這樣直接呼叫，所以引擎新增了**遠端反思模式**（`engine.remote_reflection`，world-api 啟動時自動打開）：
>
> 1. 評估期最後一天跑完，產生天災報告後**先不重置世界**，狀態變成 `awaiting_reflection`。這時世界停在評估期最後一天（`GET /runs` 的 `tick` 是 `window_end`）。
> 2. 政府 `GET reflections` 拿報告，`POST memory` 送記憶。
> 3. 引擎用 `engine.submit_memory()` 套用記憶（沿用本機模式的長度與格式檢查），接著重置世界，進入下一天。
>
> 本機模式（`civsim run`、`civsim experiment`）的行為完全不變。`tests/test_remote_reflection.py` 驗證了：
> 同樣的決策和記憶，兩種模式跑出的指標、天災報告、記憶版本和紀錄檔內容**完全相同**。
>
> 無記憶組（`government.memory: false`）不會進入 `awaiting_reflection`。

### `GET /runs/{run_id}/government/reflections`

只有 `status = awaiting_reflection` 時可以呼叫，其他狀態回 409。

**回應 200：**

```json
{
  "run_id": "20261111-a3f9",
  "status": "awaiting_reflection",
  "report": {
    "disaster_id": 1,
    "kind": "drought",
    "window_start": 26,
    "window_end": 40,
    "band": {"mean": 8.85, "std": 0.68, "low": 7.5, "high": 10.2, "k": 2.0, "samples": 60},
    "success": false,
    "recovered_day": 3,
    "left_band_after_recovery": true,
    "window_prices": [11.2, 10.6, 9.9],
    "capped_days": 0,
    "peak_price": 14.2,
    "hungry_person_days": 63,
    "deaths": 0,
    "decisions": []
  },
  "memory": "# 經驗\n..."
}
```

`report` 的欄位由 `analysis/goals.py` 的 `evaluate_disaster` 產生，欄位以分析組為準。

### `POST /runs/{run_id}/government/memory`

**請求：**

```json
{"memory": "# 經驗\n- ...", "reason": "第 1 次天災限價後價格又跌破下限，記下來"}
```

- `memory`：**必填**。填 `null` 表示不更新；整個欄位沒送會回 422，避免 client 的程式錯誤被當成「政府決定不更新」。
- `reason`：選填。目前只是收下，沒有保存（和本機模式一樣，`parse_memory` 也沒有保存理由）。

**回應 200：**

```json
{
  "run_id": "20261111-a3f9",
  "memory_result": "updated",
  "memory_version": 2,
  "status": "awaiting_decision",
  "next_tick": 41
}
```

`memory_result` 是 `updated`、`unchanged`（送了 `null`）或 `rejected`（超過 4000 字或格式錯誤，維持舊版）。
記憶被拒絕**不是 HTTP 錯誤**，理由同 D4。不管哪一種結果，世界都會調回均衡狀態，進入下一個天災週期。
最後一次天災的反思結束後，`status` 是 `finished`，`next_tick` 是 `null`。

## 錯誤格式

請求本身有問題時（世界不會前進）：

```json
{"error": "tick_mismatch", "message": "目前是 tick 38，請求的是 tick 37"}
```

| HTTP | `error` | 什麼時候 |
|---|---|---|
| 404 | `run_not_found` | `run_id` 不存在 |
| 409 | `wrong_status` | 狀態不對，例如 `awaiting_reflection` 時送決策、`finished` 後還在送 |
| 409 | `tick_mismatch` | 送決策時 `tick` 不是今天（D3） |
| 422 | （FastAPI 預設格式） | JSON 格式錯誤、少了必填欄位、欄位型別不對 |

422 用 FastAPI 預設的格式，不另外包裝。

## run（D7）

🟡 **建議：第一版一個 world-api 只跑一個 run**（architecture.md 本來就寫「第一版一次只跑一個 run」）。

- `python -m civsim serve --config configs/xxx.yaml` 啟動時產生一個 `run_id`，印在終端機上。
- 要跑下一個 run（換 config 或換 seed），就把 world-api 關掉，用新的設定重新啟動。
- 路徑裡的 `run_id` 不是目前這一個，就回 404。

### `GET /runs`

讓 client 知道目前的 `run_id`，不用從終端機複製。

```json
[{"run_id": "20261111-a3f9", "config": "baseline", "seed": 42, "status": "awaiting_decision", "tick": 37}]
```

之後實驗組需要「不重新啟動就跑新的 run」或多個 run 平行，再加 `POST /runs`。路徑已經預留 `run_id`，到時候不用改既有的路徑。

## 身分驗證與存取控制（D8）

🟡 **建議：world-api 本身不檢查身分，全部交給 digiRunner。**

| client | 可以呼叫 |
|---|---|
| 政府 | `/runs/*/government/*`、`GET /runs` |
| 前端 | `GET /world/*`、`GET /runs` |

- 直連模式（開發用）沒有任何驗證，只能在自己的電腦上用。
- 正式實驗時，world-api 只能經由 digiRunner 呼叫，不對外開放 8000 port。
- 實驗用的政府 client **不設流量限制**（architecture.md），否則實驗會跑到一半被擋。
- token 放在 `Authorization: Bearer <token>`，取得方式依 digiRunner 的設定，之後補在本文件。

## 前端路徑

### 已經有的

| 路徑 | 內容 |
|---|---|
| `GET /world/state` | 目前的 tick、階段、市場、政府、均衡區間、每位平民的狀態 |
| `GET /world/metrics` | 每天的指標 |
| `GET /world/events?since_tick=0` | 事件紀錄 |

### 🟡 D10：還沒做的（欄位由前端組決定）

| 路徑 | 內容 |
|---|---|
| `GET /world/disasters` | 天災時間表與每次的報告 |
| `GET /world/memory` | 政府記憶的所有版本 |
| `GET /world/rules` | 社會規則 |

注意：前端看得到天災時間表，政府看不到。這些路徑**不能**開放給政府的 client，否則等於變相提供預報。

### 🟡 D9：`POST /admin/step`

現在的 `/admin/step` 會用本機的政府（或沒有政府）直接推進一天。在 lockstep 下，如果前端或別人呼叫它，世界會**在政府不知道的情況下多跑一天**。

**建議：API 模式下停用，回 409。** 沒有政府的基準模擬（`controller: none`）仍可以用。需要確認前端有沒有在用這條路徑。

目前的實作：還沒停用，但和政府路徑共用同一把鎖，不會同時推進世界；`awaiting_reflection` 時呼叫會回 409。
有人用它多推了一天的話，政府下次送決策會收到 `409 tick_mismatch`，政府 client 會把 run 作廢，所以會被發現。

## 政府 client 的規則

給 Agent 組參考，實作在 `src/civsim/gateway/client.py`。

```python
while True:
    run = GET /runs/{run_id}...                    # 或直接看上一個回應的 status
    if status == "awaiting_decision":
        obs = GET  /runs/{run_id}/government/observation
        decisions = 政府決策(obs)
        r = POST /runs/{run_id}/government/decisions  {"tick": obs.tick, "actions": decisions}
    elif status == "awaiting_reflection":
        data = GET  /runs/{run_id}/government/reflections
        memory = 政府反思(data.report, data.memory)
        r = POST /runs/{run_id}/government/memory  {"memory": memory}
    elif status == "finished":
        break
    status = r.status
```

**基礎設施錯誤**（照 architecture.md）：

- 連線失敗、逾時、digiRunner 回 429 / 5xx → 有上限地重試（預設 3 次，間隔 1、2、4 秒）。
- 重送決策時收到 `409 tick_mismatch`，而 `GET /runs` 顯示世界剛好前進了一天 → 代表第一次其實已經送到，只是回應在路上逾時。
  不算錯誤，繼續下一天；當天的結算結果拿不到，但隔天的 `recent_decisions` 看得到。
  評估期最後一天比較特別：送到之後世界會停在同一天等反思，所以「`status` 是 `awaiting_reflection`、`tick` 沒變」也算已送到。
- 重送記憶時收到 409，而世界已經離開反思、前進到 `window_end + 1` → 同樣代表第一次已經送到。
- 重試仍然失敗，或收到不該出現的錯誤（404、422、沒有重送卻收到 409）→ **整個 run 作廢並停止**，
  不可以默默改成 `idle` 繼續跑，否則實驗結果會被誤認成政府的決策。

實作：`HttpWorldClient` 與 `run_government()`。要測試連線，可以在另一個終端機執行
`python -m civsim govern --base-url <world-api 或 digiRunner 的網址>`，它會扮演一個每天都不行動的政府，把整個 run 跑完。

**LLM 的錯誤不是基礎設施錯誤**：LLM 回應格式錯誤、額度用完時，由 `agents/government.py` 的 fallback 處理（預設不行動），並記錄在 LLM 呼叫紀錄裡。

## 待補

- digiRunner 的 token 取得方式與 base URL（部署完成後補）
- `/world/*` 新路徑的欄位（等前端組，見 D10）
