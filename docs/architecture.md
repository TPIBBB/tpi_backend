# 架構

研究「AI 政府在多次天災中，能否靠記憶學會穩住價格、避免飢荒」。本文件記錄已經定案的專案邊界；
還沒定的數值見 README 的「待討論」。

> 目前程式仍是舊方向（資訊權限）的引擎，新方向的模組只有骨架。下面描述的是要實作的目標架構，
> 「現有程式的調整」一節列出和現有程式不同的地方。

## 範圍

| 在範圍內 | 不在範圍內 |
|---|---|
| 一個 LLM 政府、一群 rule-based 平民 | 平民改成 LLM（之後可當延伸實驗） |
| 單一機制的天災：糧食減產，強度與預警時間隨機 | 多種機制的天災（洪水毀儲備等，之後擴充） |
| 政府的封閉行動清單、社會規則、跨天災記憶 | 舊方向的資訊權限：`share_info`、`request_permission`、`grant_permission`、`read:*` |
| 政府經 digiRunner 呼叫 world-api | 制度決策同步到 digiRunner 的「政策轉換」流程 |

## 角色

| 角色 | 控制方式 | 能看到 |
|---|---|---|
| 政府 | LLM（`GovernmentController`），供應商可替換，正式實驗前鎖定模型 ID | 價格、自己的預算與儲備、天災**預報**（有誤差）、社會規則、記憶、近期決策與被拒絕的理由 |
| 平民 | rule-based（農夫、樵夫、工匠、商人） | 價格、自己的狀態；政府發布預報後才看得到預報 |

政府和平民的行動分開定義：平民用 `models.ActionType`，政府用 `GovernmentDecision` / `GovernmentActionType`。

## 一個回合

```
天災            world/disasters.py   依時間表更新預報（政府可見）與真實減產
政府決策        需要決策的回合才呼叫（見下）
                agents/government.py 提出 → world/social_rules.py 檢查規則 → world/government.py 驗證與結算
平民決策        依價格、狀態與已發布的預報行動；對政府行動有對應的反應規則
結算與 upkeep   現有流程
記錄            事件、狀態、指標
評估與反思      某次天災的評估期結束時：analysis/goals.py 產生報告 → 政府提出新版記憶 → 引擎檢查後保存
```

- **決策頻率**：平時每 N 個 tick 決策一次；從預報開始到評估期結束，每個 tick 都決策。
- **結算順序**：政府先於平民結算；平民行動的順序每回合隨機打亂。
- **一次多個決策**：`decide` 回傳的決策各自驗證，一個被拒絕不影響其他。

## 政府的行動

封閉清單，參數範圍、初始預算與儲備都放在 config（模擬引擎組訂定）。

| 類別 | 行動 |
|---|---|
| 穩定 | 釋出儲備、收購儲備、價格上限、補貼、配給 |
| 財政 | 課稅、發行貨幣 |
| 強制 | 徵收、處罰平民 |
| 資訊 | `PUBLISH_FORECAST`：把預報公開給平民（平民會沿用現有的囤積反應） |

- 刻意納入可能違反社會邏輯的行動，才觀察得到違規。
- 每個行動至少定義一條平民的反應規則（例如被徵收後下回合工作量下降），壞決策才有代價。
- 發行貨幣會影響價格：做市商的價格乘上「目前貨幣量 / 初始貨幣量」。

## 社會規則

- 規則是實驗設定的一部分，**一次 run 內固定不變**，每個規則集有版本號。
- 研究者在 run 和 run 之間滾動式調整：觀察違規 → 新增規則 → 用新版本重跑。
- 違規決策由引擎拒絕，拒絕理由放進政府下一次的觀察。

## 記憶

- 政府的記憶是一份 Markdown。每次天災評估期結束都會呼叫 `reflect`；回傳 `None` 表示不更新。
- 引擎只檢查長度上限與格式，不審查內容；每個版本都保存。
- 記憶**不跨 run**：每個 run 從同一份初始記憶開始（版本記錄在 manifest）。
- 反思報告只放實際觀測值：達標與否、判定門檻、價格最大偏離、挨餓與死亡人數、這次天災中自己的決策和被拒絕的決策。
  **不給** IDLE 基準的數字，基準只用於研究者的評分。

## 天災時間表

```
[預報][天災][評估期][恢復期] → 下一次天災
```

- 時間表只由 seed 決定，與政府決策無關，不同條件在同一個 seed 遇到相同的天災。
- 每個 run 10 次天災，評估期不重疊；恢復期讓社會回到正常狀態，避免前一次的後遺症算到下一次。
- 各段長度放在 config，總 tick 數由此推算。

## 目標判定與實驗設計

**判定（每次天災，`analysis/goals.py`）**

- 沒有飢荒：評估期內死亡人數 = 0。
- 價格穩定：價格相對天災前平均的最大偏離，要比同一個 seed 的 IDLE 基準政府低 Z%。
  價格標準差與回復時間寫進報告當輔助分析。

**比較（`experiments/disaster_runner.py`）**

- 主要對照：有記憶 vs 無記憶。無記憶組只拿掉跨天災的 Markdown 記憶（不呼叫 `reflect`），
  天災內的近期歷史與拒絕回饋照常提供。
- 一次只改一個條件；之後可加「有規則 vs 沒有規則」「不同模型」。
- 每個條件跑多個 seed（暫定 5 個）。temperature 用小的固定值，靠重複次數處理變異。
- IDLE 基準政府沒有 LLM，走本機模式。
- 主要結果：「第 k 次天災的達標比例」曲線（跨 seed），每個條件一條。
  補充數字：每個 run「從第幾次開始之後都達標」（`first_sustained`）的中位數與從未達標的比例。

## 執行模式與 digiRunner

實驗也走 digiRunner；本機模式用於 IDLE 基準與開發。

```
政府 client (gateway/)
    │  HTTP + 身分憑證 + run_id header
    ▼
digiRunner API Gateway  ── 路由、身分驗證、存取紀錄（實驗用的政策不限流）
    │
    ▼
world-api (api/server.py + api/government.py) ── 模擬引擎；平民在這裡直接計算
```

- **只有政府走 API**，平民在 world-api 內部計算。
- **world-api 自己跑回合迴圈**，輪到政府決策時暫停，等 `POST /government/decisions` 送來才繼續；
  政府 client 輪詢 `GET /government/observation`。不需要政府決策的回合由 world-api 直接跑完。
- **基礎設施錯誤**（限流、逾時、驗證失敗）有上限地重試；仍然失敗就把整個 run 標記為無效，
  不會默默變成 IDLE。
- 第一版一次只跑一個 run，但路徑預留 `run_id`（`/runs/{run_id}/government/...`），之後平行執行不必改路由。
- 本機和遠端的政府都實作同一個 `GovernmentController` Protocol。

兩層存取控制的區分：社會規則是**研究模型**的一部分，由引擎檢查；digiRunner 的政策是**現實系統**的 API 安全，
決定誰能呼叫 `/government/*`。兩者不同步。

## 紀錄

- 每個 run 一份 manifest：`run_id`、條件名稱、seed、config 雜湊值、規則集版本、初始記憶版本、
  模型 ID 與 temperature、git commit。
- 天災報告、記憶版本、LLM 呼叫（prompt、回應、模型版本）都帶 `run_id`。
- 政府 client 的請求在 header 帶 `run_id`，讓 digiRunner 的存取紀錄能和模擬紀錄對應。
- 先寫 JSONL（`JsonlRecorder`），資料庫組另寫匯入 `db/schema.sql` 的流程；實驗執行不依賴資料庫服務。

## 模組與組別

| 模組 | 組別 | 內容 |
|---|---|---|
| `world/disasters.py` | 模擬引擎組 | 天災時間表與觸發 |
| `world/government.py` | 模擬引擎組 | 政府的狀態、行動、驗證與結算 |
| `world/social_rules.py` | 模擬引擎組 | 社會規則與違規判定 |
| `agents/government.py` | Agent 決策組 | 政府的決策與反思（`GovernmentController`） |
| `analysis/goals.py` | 分析組 | 每次天災的目標判定 |
| `experiments/disaster_runner.py` | 分析組 | 比較不同實驗條件 |
| `storage/research_records.py` | 資料庫組 | manifest、天災報告、記憶版本、LLM 呼叫的紀錄 |
| `api/government.py` | digiRunner 整合組、前端組 | 政府與研究資料的 HTTP 路徑 |

## 現有程式的調整

會改到共用介面，請先在群組討論分工與順序：

- **移除舊的資訊權限**：`policy/`、`models.py` 的權限行動、`world/engine.py` 與 `world/rules.py` 的權限檢查、
  `agents/rule_based.py` 的申請與授權邏輯、`agents/llm.py`、`analysis/metrics.py` 的權限指標、
  `gateway/`、`api/server.py`，以及相關測試與 `configs/`。前端的 `/world/state` 會少掉權限欄位，需同步通知前端組。
- **預報**：平民改為預設看不到預報，只有政府發布後才看得到。
- **市場**：做市商的價格加入貨幣量倍率。
- **`world/engine.py`**：加入上面的回合流程，並支援 API 模式下等待政府決策。
- **`config.py`**：新增天災、政府、社會規則、判定標準、決策頻率、模型的設定。
- **`api/server.py`**：掛上 `api/government.py` 的 router。
