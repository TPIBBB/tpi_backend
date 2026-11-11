# 架構

研究「AI 政府面對天災時會如何決策」：觀察政府的決策，以及每次天災後的評估期內，價格能否恢復到市場均衡價格、
經歷多次天災後這個結果如何變化。本文件記錄已經定案的專案邊界；還沒定的內容見 README 的「待討論」。

> 11/10 更新：引擎已改成新方向（舊的資訊權限系統已移除），社會規則的部分以 [society.md](society.md) 為準。
> 和本文件不同的地方：不提供天災預報（沒有 `publish_forecast`、預警時間）、政府每天都能決策、
> 均衡區間用校準期計算、違規處理有 enforce／record／off 三種模式。政府經 digiRunner 的 HTTP 路徑仍待 API 組實作。

## 核心觀念

**政府只能提出決策與新版記憶，世界狀態只由模擬引擎改變。**

引擎對每個決策問兩個問題，分開由兩個模組回答：

| 問題 | 例子 | 模組 |
|---|---|---|
| 應不應該做 | 處決平民是否違反社會規則 | `world/social_rules.py` |
| 做不做得到 | 儲備夠不夠發糧 | `world/government.py` |

社會規則由研究者新增，政府只能讀取、不能修改。

## 範圍

| 在範圍內 | 不在範圍內 |
|---|---|
| 一個 LLM 政府、一群 rule-based 平民 | 平民改成 LLM（之後可當延伸實驗） |
| 單一機制的天災：糧食減產，每次強度固定 | 多種機制的天災（洪水毀儲備等，之後擴充） |
| 政府的封閉行動清單、社會規則、跨天災記憶 | 舊方向的資訊權限：`share_info`、`request_permission`、`grant_permission`、`read:*` |
| 政府經 digiRunner 呼叫 world-api | 制度決策同步到 digiRunner 的「政策轉換」流程 |

## 角色

| 角色 | 控制方式 | 能看到 |
|---|---|---|
| 政府 | LLM（`GovernmentController`），供應商可替換，正式實驗前鎖定模型 ID | 暫定：價格、自己的預算與儲備、天災**預報**（第一版不設誤差）、社會規則、記憶、近期決策與被拒絕的理由（完整範圍待討論） |
| 平民 | rule-based（職業、階級待定） | 價格、自己的狀態；政府發布預報後才看得到預報 |

政府和平民的行動分開定義：平民用 `models.ActionType`，政府用 `GovernmentDecision` / `GovernmentActionType`。

平民的設定：

- **特性**：有無買賣、有無產出，共 4 種；有產出的平民產量隨機。
- **persona**：會不會遵守政府政策、sloth、greed、risk tolerance、gluttony。

## 一個回合

```
天災            world/disasters.py   依時間表更新預報（政府可見）與真實減產
政府決策        需要決策的回合才呼叫（見下）
                agents/government.py 提出 → world/social_rules.py 檢查規則 → world/government.py 驗證與結算
平民決策        依價格、狀態與已發布的預報行動；對政府行動有對應的反應規則
結算與 upkeep   現有流程
記錄            事件、狀態、指標
評估與反思      某次天災的評估期結束時：analysis/goals.py 產生報告 → 政府提出新版記憶 → 引擎檢查後保存
                不論價格是否恢復，引擎都把社會調回同一個均衡狀態，政府記憶會保留
```

- **決策頻率**：從預報開始到評估期結束，每個 tick 都決策；平時是否決策待討論（若可以，每 N 個 tick 一次）。
- **結算順序**：政府先於平民結算；平民行動的順序每回合隨機打亂。
- **一天一個決策**：政府和平民一樣一天只能做一個決策（`max_decisions_per_day`），多送的會被拒絕並記錄理由。

## 政府的行動

封閉清單，參數範圍、初始預算與儲備都放在 config（模擬引擎組訂定）。

| 類別 | 行動 |
|---|---|
| 穩定 | `release_reserve`、`buy_reserve`、`import_food`、`price_cap`、`distribute_food`、`cash_transfer` |
| 財政 | `collect_tax`、`issue_currency` |
| 強制 | `seize_food`、`execute_citizen` |
| 資訊 | `publish_forecast`：把預報公開給平民（平民會沿用現有的囤積反應） |

名稱與參數以 `agents/government.py` 的 `DECISION_DOCS` 為準，`publish_forecast` 尚未加入；
實際可用的行動由模擬引擎組的 `GovernmentActionType` 決定。

- 刻意納入可能違反社會邏輯的行動，才觀察得到違規。
- 每個行動至少定義一條平民的反應規則（例如被徵收後下回合工作量下降），壞決策才有代價；
  代價只存在於該次天災內，不會帶到下一次。
  平民不遵守政策時的具體行為待討論。
- 發行貨幣會影響價格：做市商的價格乘上「目前貨幣量 / 初始貨幣量」。

## 社會規則

- 規則是實驗設定的一部分，**一次 run 內固定不變**，每個規則集有版本號。
- 研究者在 run 和 run 之間滾動式調整：B 組（沒有社會規則）出現超出常理的行為 → 更新規則集 → A、C 組用新版本重跑。
- 違規決策由引擎拒絕，拒絕理由放進政府下一次的觀察。

## 記憶

- 政府的記憶是一份 Markdown。每次天災評估期結束都會呼叫 `reflect`；回傳 `None` 表示不更新。
- 引擎只檢查長度上限與格式，不審查內容；每個版本都保存。
- 記憶**不跨 run**：每個 run 從同一份初始記憶開始（版本記錄在 manifest）。
- 反思報告只放實際觀測值：評估期內的價格、是否恢復到均衡價格、這次天災中自己的決策和被拒絕的決策。
  其他欄位（例如挨餓與死亡人數）隨「政府看得到什麼」一起決定。

## 天災時間表

```
[穩定期][預報][天災][評估期] → 調回同一個均衡狀態 → 下一次天災（從穩定期開始）
```

- 時間表與強度由 config 決定，與政府決策無關，所有條件和 seed 都遇到相同的天災；seed 只影響平民等其他隨機部分。
- 每個 run 經歷多次天災，評估期不重疊。
- **穩定期**是社會沒有經歷天災時的正常社會。每次評估期結束，不論價格是否恢復，引擎都把社會調回同一個均衡狀態，
  政府記憶會保留，近期決策與被拒絕的理由會清空；這個狀態從哪裡取得、人口與政府預算儲備是否調回待討論。
- 每次天災的強度、預警時間（預報開始到天災開始的 tick 數）與評估期長度都相同，結果才能互相比較。
- 各段長度放在 config，總 tick 數由此推算。

## 目標判定與實驗設計

**判定（每次天災，`analysis/goals.py`）**

- 天災結束後的評估期長度固定，觀察這段期間內價格能否恢復到市場均衡價格；A、C 組比較的就是這個結果。
- 政府可以使用 `price_cap`，但價格被上限壓住時不算成功。
- 死亡人數不影響成功判定，只記成輔助指標。
- 成功標準待討論：用固定數字，或和穩定期（社會沒有經歷天災時的正常社會）的價格比較。

**比較（`experiments/disaster_runner.py`）**

分組（實驗設計尚未定案，見 README）：

| 組別 | 政府 | 記憶 | 社會規則 | 用途 |
|---|---|---|---|---|
| A 沒有記憶 | AI Agent | 無 | 有（參照 B 組行為） | 當對照組 |
| B 有記憶（沒有社會規則） | AI Agent | 有 | 無 | 觀察無規則限制時政府可能做出哪些不合理舉動，藉此訂定 A、C 組的社會規則；不參與比較 |
| C 有記憶（有社會規則） | AI Agent | 有 | 有（參照 B 組行為） | 看記憶能否提高恢復成功率 |

真正進行比較的只有 A、C 組；兩組使用相同版本的社會規則，差別只有記憶。

- 無記憶組只拿掉跨天災的 Markdown 記憶（不呼叫 `reflect`），天災內的近期歷史與拒絕回饋照常提供，但每次調回均衡狀態時都會清空，不跨天災。
- 除了表中的變因，各組使用相同的初始世界、平民設定、引擎規則、prompt 版本，以及相同的天災時間表與強度。
- 每組用同一批 seed 各跑多次。temperature 用小的固定值，靠重複次數處理變異。
- 主要結果待討論，兩個方案是：看 n 次天災內的成功次數，或看經歷到第幾次會成功。

## 執行模式與 digiRunner

實驗也走 digiRunner；本機模式用於開發。

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

## 模組之間的介面

| 介面 | 模組 | 用途 |
|---|---|---|
| `build_schedule(seed, ticks)` | `world/disasters.py` | 建立天災時間表，與政府決策無關 |
| `begin_tick_events(world, schedule)` | `world/disasters.py` | 回合開始時更新預報、觸發天災 |
| `GovernmentController.decide(obs)` | `agents/government.py` | 根據 `GovernmentObservation` 提出 `GovernmentDecision` |
| `GovernmentController.reflect(report, memory)` | `agents/government.py` | 回傳新版記憶，不修改時回傳 `None` |
| `find_violations(decision, rules)` | `world/social_rules.py` | 回傳決策違反的規則 |
| `validate(world, decision)` | `world/government.py` | 合法時回傳 `None`，否則回傳拒絕原因 |
| `settle(world, decision)` | `world/government.py` | 執行已驗證的決策並回傳事件紀錄 |
| `evaluate_disaster(disaster, history, events)` | `analysis/goals.py` | 產生一次天災的報告 |
| `first_sustained(reports)` | `analysis/goals.py` | 找出從第幾次天災開始，之後每一次都成功（是否保留依實驗方式決定） |
| `ResearchRecorder` | `storage/research_records.py` | 保存 manifest、天災報告、記憶版本與 LLM 呼叫 |
| `run_conditions(configs, repeats, out_root)` | `experiments/disaster_runner.py` | 每組條件跑多個 seed，輸出每次天災的結果 |

## 預計的 HTTP 路徑

都列在 `api/government.py`，目前尚未實作。政府的路徑預留 `run_id`（見上面的執行模式）。

| 路徑 | 內容 |
|---|---|
| `GET /runs/{run_id}/government/observation` | 政府本回合看得到的內容 |
| `POST /runs/{run_id}/government/decisions` | 提交政府決策 |
| `GET /runs/{run_id}/government/reflections` | 等待反思的天災報告與目前的記憶 |
| `POST /runs/{run_id}/government/memory` | 提交新版記憶 |
| `GET /world/disasters` | 天災時間表與報告 |
| `GET /world/memory` | 政府記憶的所有版本 |
| `GET /world/rules` | 社會規則 |

`/runs/*/government/*` 只有政府的身分能呼叫；`/world/*` 的欄位由前端組確認。

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

## 接線

把骨架接進引擎、調整現有程式時會改到共用介面，請先在群組討論分工與順序：

- **移除舊的資訊權限**：`policy/`、`models.py` 的權限行動、`world/engine.py` 與 `world/rules.py` 的權限檢查、
  `agents/rule_based.py` 的申請與授權邏輯、`agents/llm.py`、`analysis/metrics.py` 的權限指標、
  `gateway/`、`api/server.py`，以及相關測試與 `configs/`。前端的 `/world/state` 會少掉權限欄位，需同步通知前端組。
- **預報**：平民改為預設看不到預報，只有政府發布後才看得到。
- **市場**：做市商的價格加入貨幣量倍率。
- **`world/engine.py`**：加入上面的回合流程，並支援 API 模式下等待政府決策。
- **`world/events.py`**：`generate_events` 由 `begin_tick_events` 取代。
- **`models.py`**：政府決策維持獨立的 `GovernmentDecision`，不併入 `ActionType`。
- **`config.py`**：新增天災、政府、社會規則、判定標準、決策頻率、模型的設定。
- **`api/server.py`**：掛上 `api/government.py` 的 router。
- **調回均衡狀態**：引擎要在每次評估期結束時，把社會調回同一個均衡狀態（保留政府記憶，清空近期決策與被拒絕的理由）並記錄事件。
- **研究目標**：`analysis/goals.py` 與 `agents/government.py` 的 prompt 仍寫「沒有飢荒」，要改成新的目標。
