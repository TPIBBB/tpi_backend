# 架構

研究「AI 政府面對天災時會如何決策」：觀察政府的決策，以及每次天災後的評估期內，價格能否恢復到市場均衡價格、
經歷多次天災後這個結果如何變化。本文件記錄已經定案的專案邊界；還沒定的內容見 README 的「待討論」。

> 11/20 更新：依 11/09 會議與目前的程式更新（不提供天災預報、政府每天都能決策、均衡區間用校準期計算、
> 政府的 HTTP 路徑已實作）。社會、市場與平民的細節以 [society.md](society.md) 為準，HTTP 格式以 [api.md](api.md) 為準。

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
| 政府 | LLM（`agents/government.py` 的 `LLMGovernment`），供應商可替換（Gemini、Modal／Ollama 等 OpenAI 相容 API），正式實驗前鎖定模型 ID | 見下方「政府看得到什麼」 |
| 平民 | rule-based（`agents/rule_based.py`，規格見 `agents/citizen_skill.md`），不使用 LLM | 昨天的成交價、習慣價格、自己的狀態、目前的價格上限 |

政府和平民的行動分開定義：平民用 `models.ActionType`，政府用 `GovernmentDecision` / `GovernmentActionType`。

**政府看得到什麼**（11/09 會議，欄位見 `world/government.py` 的 `GovernmentObservation`）：

| 看得到 | 看不到 |
|---|---|
| 昨天的成交價、自己的預算與儲備、人口、這次週期的死亡人數、昨天挨餓的人數 | 平民各自的存糧與存款 |
| 平民的 id 與類型、目前的價格上限 | 天災時間表、天災預報 |
| 社會規則（B 組看不到）、記憶（A 組沒有）、這次週期最近 20 筆決策結果與被拒絕的理由 | 均衡價格區間（後台判定用） |
| 這次週期（上次重置以來）每天的成交價 `price_history` | 上一次以前的週期的價格（只能靠記憶） |

**為什麼給價格歷史、不給均衡區間**（11/20 決定）：均衡區間是後台的評分標準，給了等於先看答案。
價格歷史是政府自己親眼看過的資訊，但 LLM 每次呼叫都不記得上一次，不給的話天災那天只看得到一個數字，
不知道它比平常高還是低；C 組卻能在記憶裡寫下「正常糧價約 5」補上這個資訊。
這樣 C 組贏了也分不清是學到策略，還是記憶只被當成價格筆記本。給了價格歷史，A、C 組在同一次天災內資訊對等，
兩組的差距只會來自跨天災累積的經驗，比較容易判斷政府有沒有從經驗中學習。

**副作用：政府推得出「這個週期的第幾天」**（11/20 決定接受）：`price_history` 的長度就是上次重置後過了幾天。
C 組可能在記憶裡寫下「重置後約第 20 天會有天災」並提前準備；穩定期長度隨機（`stable_days ± stable_jitter`）可以降低、但無法消除這個效果。
「記住天災大概何時來」也算從經驗中學習，所以接受；分析時要從記憶內容區分政府學到的是**時機**還是**策略**，並在報告中說明。

平民的設定：

- **特性**：有無買賣、有無產出，共 4 種（農商、自耕農、打工族、依賴者）；有產出的平民產量隨機。
- **persona**：sloth、greed、risk_tolerance、gluttony，以及是否服從政府（固定 30% 不服從）。

## 一個回合

```
天災            world/disasters.py   依時間表觸發減產（沒有預報，政府和平民都只能從收成與價格察覺）
政府決策        每天都呼叫
                agents/government.py 提出 → world/social_rules.py 檢查規則 → world/government.py 驗證與結算
平民決策        依價格與自己的狀態行動；對政府政策的反應見 agents/citizen_skill.md
結算            生產 → 集合競價成交 → 每人吃 1 單位糧食（見 society.md）
記錄            事件、狀態、指標
評估與反思      某次天災的評估期結束時：analysis/goals.py 產生報告 → 政府提出新版記憶 → 引擎檢查後保存
                不論價格是否恢復，引擎都把社會調回同一個均衡狀態，政府記憶會保留
```

- **決策頻率**：穩定期、天災與評估期每天都決策（政府不知道天災何時開始，平時也要能行動）。
  為了省 LLM 呼叫，`government.call_policy: on_change` 會在狀況和上次呼叫時差不多時沿用上次的決策、不呼叫 LLM；
  上次決策被拒絕、記憶剛更新，或已經連續 `max_skip_days` 天沒呼叫時，一定會呼叫。
- **結算順序**：政府先於平民結算；平民行動的順序每回合隨機打亂。
- **一天一個決策**：政府一天只能做一個決策（`max_decisions_per_day`），多送的會被拒絕並記錄理由。
- **平民一天跑一輪**：依身分生產一次（收成／打工）加上一張買賣單，先生產再下單；多送的動作會被拒絕並記錄。

## 政府的行動

封閉清單，參數範圍、初始預算與儲備都放在 config（模擬引擎組訂定）。

| 類別 | 行動 |
|---|---|
| 穩定 | `release_reserve`、`buy_reserve`、`import_food`、`price_cap`、`distribute_food`、`cash_transfer` |
| 財政 | `collect_tax`、`issue_currency` |
| 強制 | `seize_food`、`execute_citizen` |
| 其他 | `idle`：今天不行動 |

給 LLM 看的參數說明在 `agents/government.py` 的 `DECISION_DOCS`；實際可用的行動與參數檢查以模擬引擎組的
`GovernmentActionType` 與 `world/government.py` 為準。引擎新增行動但 `DECISION_DOCS` 還沒補說明時，prompt 只會列出名稱。

- 刻意納入可能違反社會邏輯的行動，才觀察得到違規。
- 平民的反應（11/12 定案）：只有價格上限需要平民選擇，不服從的農商在價格上限期間不賣糧；
  其他政策由引擎直接執行，平民不做反應。壞決策的代價只存在於該次天災內，不會帶到下一次。
- 發行貨幣會影響價格：習慣價格（平民報價的參考）隨貨幣量上升。

## 社會規則

- 規則是實驗設定的一部分，**一次 run 內固定不變**，每個規則集有版本號。
- 研究者在 run 和 run 之間滾動式調整：B 組（沒有社會規則）出現超出常理的行為 → 更新規則集 → A、C 組用新版本重跑。
- 違規決策由引擎拒絕，拒絕理由放進政府下一次的觀察。

## 記憶

- 政府的記憶是一份 Markdown。有記憶的組別在每次天災評估期結束都會呼叫 `reflect`；回傳 `None` 表示不更新。
- 引擎只檢查長度上限（`government.memory_max_chars`，預設 4000 字元）與格式，不審查內容；每個版本都保存。
  超過上限的記憶整份拒絕、沿用舊版。反思的 prompt 會告訴 LLM 這個上限與目前記憶的字數，
  `build_government` 會把 config 的上限傳給 `LLMGovernment`，兩邊要一致。
- 記憶**不跨 run**：每個 run 從同一份初始記憶（`government.initial_memory`）開始。
- 反思報告（`analysis/goals.py` 的 `evaluate_disaster`）交給 LLM 前會拿掉均衡區間（`band`，見 `HIDDEN_REPORT_FIELDS`），
  只放實際觀測值：評估期內每天的價格、
  是否成功、第幾天回到區間、價格被上限壓住的天數、最高價、挨餓人天數、死亡人數，以及這次週期自己的所有決策與被拒絕的理由。
- 記憶格式（gov-v6 起，`agents/government.py`）：試跑時 Qwen2.5-7B 把失敗的天災寫成「災害未發生」、
  第二次反思把舊記憶原封不動抄回來，所以改成程式和 LLM 分工：
  - **天災紀錄**：每次天災的結果（成功與否、挨餓人天、最高價、被上限壓住的天數、各類決策次數）由程式寫一行，LLM 不能改。
    紀錄最多佔記憶的一半，超過就刪最舊的。
  - **教訓**：LLM 回傳 `result`（照抄成功／失敗）、`analysis`、`worked` / `failed` / `try_next` 三個清單，由程式組成 Markdown。
  - 反思報告寫成先講結論的中文摘要，決策依類型統計，不逐筆列出。
  - 回答不合格（`result` 和報告不符、超過字數、格式錯誤、和舊教訓一模一樣、三個清單都空）就帶著問題重問一次
    （`trigger = "reflect-retry"`）。還是不合格時：嚴重問題（讀錯結果、太長、格式錯誤）保留舊教訓，
    輕微問題（照抄、空白）照樣採用；兩種情況這次的天災紀錄都會寫進去。連不上 LLM 時回傳 `None`，引擎記成反思失敗。
- 決策 prompt（gov-v6 起）另外附上程式從觀察算好的趨勢：漲跌幅、連續上漲／下跌天數、價格是否被上限壓住、
  挨餓人數的變化，以及近期決策（連續相同的合併）之後價格與挨餓人數的變化。只做算術，不加入政府看不到的資訊。
  觀察裡只有今天的挨餓人數，`LLMGovernment` 自己記每天的人數，價格歷史變短（重置）時清空。
  可用行動依作用分類（增加糧食／幫平民買得起／壓住價格／增加政府資源），LLM 要先寫 `situation` 判斷現況再決定。

## 天災時間表

```
[穩定期][天災][評估期] → 調回同一個均衡狀態 → 下一次天災（從穩定期開始）
```

- 不提供天災預報（11/09 會議）：有預報又能提前決策的話，政府一定先囤糧，會讓數據失真。政府只能憑記憶判斷。
- 時間表與強度由 config 決定（`schedule_seed` 和平民的 `seed` 分開），與政府決策無關，所有條件都遇到相同的天災。
- 每個 run 經歷多次天災，評估期不重疊。
- **穩定期**是社會沒有經歷天災時的正常社會。長度在 `stable_days ± stable_jitter` 內隨機，政府才學不到天災的固定時間。
- 模擬一開始與每次評估期結束（不論價格是否恢復），社會都在**均衡狀態**：校準期（沒有政府、沒有天災）跑完
  `burn_in_days` 天、價格已收斂後的世界（`equilibrium.start_converged: true`，預設）。人口、平民庫存、政府預算與儲備、
  市場全部重置成這個狀態，近期決策與被拒絕的理由清空，只有政府記憶保留。所以每次穩定期一開始價格就在均衡區間內。
  設成 `false` 時改用初始世界（價格約 5.6，要約 10 天才收斂），11/22 以前的 run 都是這樣跑的。
- 每次天災的強度（`food_multiplier`）、天災天數與評估期長度都相同，結果才能互相比較。

## 目標判定與實驗設計

**判定（每次天災，`analysis/goals.py`）**

- 天災結束後的評估期長度固定，觀察這段期間內價格能否恢復到市場均衡價格；A、C 組比較的就是這個結果。
- 均衡區間：校準期（沒有政府、沒有天災）每天成交價的平均 ± k 個標準差（`equilibrium.k`，見 society.md）。
- 成功（11/09 會議）：評估期內回到區間後，要一直維持在區間內直到評估期結束；中途跑出區間就算失敗。
- 政府可以使用 `price_cap`，但價格被上限壓住的那天不算在區間內。
- 死亡與挨餓人數不影響成功判定，只記成輔助指標。

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
- **world-api 自己跑回合迴圈**，每天暫停等政府 `POST /government/decisions` 送來才繼續；
  政府 client（`gateway/client.py`，用 `python -m civsim govern` 啟動）輪詢 `GET /government/observation`。
  有記憶的組別在評估期結束時會停在 `awaiting_reflection`，等政府送來新版記憶（見 api.md）。
- **基礎設施錯誤**（限流、逾時、驗證失敗）有上限地重試；仍然失敗就把整個 run 標記為無效，
  不會默默變成 IDLE。經過 digiRunner 時，驗證失敗分兩種處理：401（沒有 token 或 token 過期）會換一次 token 再送；
  403（這個 client 沒有權限呼叫這條路徑）**不重試**，直接把 run 標記為無效，因為那是 digiRunner 的權限設定問題，
  重試也不會變（見 [digirunner_setup.md](digirunner_setup.md)）。
- 第一版一次只跑一個 run，但路徑預留 `run_id`（`/runs/{run_id}/government/...`），之後平行執行不必改路由。
- 本機和遠端的政府都實作同一個 `GovernmentController` Protocol。

兩層存取控制的區分：社會規則是**研究模型**的一部分，由引擎檢查；digiRunner 的政策是**現實系統**的 API 安全，
決定誰能呼叫 `/government/*`。兩者不同步。

## 紀錄

- 每個 run 一份 manifest：`run_id`、條件名稱、seed、config 雜湊值、規則集版本、初始記憶版本、
  模型 ID 與 temperature、git commit。
- 天災報告、記憶版本、LLM 呼叫（prompt、回應、模型版本）都帶 `run_id`。
- digiRunner 的存取紀錄（每次呼叫的時間、client、網址、狀態碼）靠政府路徑網址裡的 `run_id` 對應到 run，
  跑完用 `python -m civsim export-access-log` 匯出成該 run 的 `digirunner_access.jsonl`。
  政府 client 另外在 header 帶 `X-Run-Id`，但 digiRunner 的紀錄不存 header。
- 先寫 JSONL（`JsonlRecorder`），資料庫組另寫匯入 `db/schema.sql` 的流程；實驗執行不依賴資料庫服務。
- 目前每個 run 的 `meta.json` 有：完整的 config、git commit 與有沒有未 commit 的修改（`git.dirty`），
  用 LLM 政府時再加上 `llm`：供應商、模型、temperature、seed、prompt 版本，以及還沒鎖定的設定（`unlocked`）。
  不含 API key。
- **重播的決策**：`call_policy: on_change` 跳過 LLM 的日子會重送上次的決策，結算方式完全相同，但決策紀錄
  （`recent_decisions`、天災報告的 `decisions`、`gov:*` 與 `rule:violation` 事件）會標 `replayed: true`。
  分析政府做了什麼、B 組人工判斷「亂搞」時，只看 LLM 親自做的決策，重播的另外計算。

### 正式實驗前的檢查清單

1. **鎖定 LLM 設定**：`.env` 明確寫出 `LLM_MODEL`（固定版本，不要用 `latest` 這類會自動更新的別名）、
   `LLM_TEMPERATURE=0`、`LLM_SEED`（整數）。`run`、`experiment`、`govern` 用 LLM 政府時會提醒還沒鎖定的設定；
   正式實驗加上 `--strict`，沒鎖定就不執行。
2. **改 prompt 就升版本**：改了 `agents/government.py` 的任何 prompt，就把 `GOV_PROMPT_VERSION` 加 1。
   `tests/test_prompt_version.py` 會檢查 prompt 內容的指紋，忘記升版本時測試會失敗，並印出要登記的新指紋。
3. **先 commit 再跑**：`meta.json` 的 `git.dirty` 是 `true` 表示有未 commit 的修改，那次的結果無法重現。
4. **跑完看統計**：`python -m civsim llm-stats runs/<組別>/seed<n> [...] [--csv 輸出.csv]` 會列出 LLM 呼叫與失敗次數、
   token 用量、每種決策的次數（LLM 親自做的／重播的、穩定期／天災／評估期）、被拒絕的理由、違反的社會規則、
   每次天災的結果與 LLM 用了哪些決策。B 組的結果直接交給社會規則負責人訂規則。

## 模組之間的介面

| 介面 | 模組 | 用途 |
|---|---|---|
| `build_schedule(config)` | `world/disasters.py` | 建立天災時間表，與政府決策無關 |
| `begin_tick_events(world, schedule)` | `world/disasters.py` | 回合開始時觸發天災 |
| `GovernmentController.decide(obs)` | `agents/government.py` | 根據 `GovernmentObservation` 提出 `GovernmentDecision` |
| `GovernmentController.reflect(report, memory)` | `agents/government.py` | 回傳新版記憶，不修改時回傳 `None` |
| `find_violations(decision, rules)` | `world/social_rules.py` | 回傳決策違反的規則 |
| `validate(world, decision, config)` | `world/government.py` | 合法時回傳 `None`，否則回傳拒絕原因 |
| `settle(world, decision, config)` | `world/government.py` | 執行已驗證的決策並回傳事件紀錄 |
| `evaluate_disaster(disaster, history, band, decisions)` | `analysis/goals.py` | 產生一次天災的報告 |
| `first_sustained(reports)` | `analysis/goals.py` | 找出從第幾次天災開始，之後每一次都成功（是否保留依實驗方式決定） |
| `ResearchRecorder` | `storage/research_records.py` | 保存 manifest、天災報告、記憶版本與 LLM 呼叫 |
| `run_conditions(configs, repeats, out_root)` | `experiments/disaster_runner.py` | 每組條件跑多個 seed，輸出每次天災的結果（尚未實作，目前用 `experiments/runner.py` 的 `run_batch`） |

## HTTP 路徑

政府的路徑在 `api/government.py`，`/world/*` 在 `api/server.py`。格式以 [api.md](api.md) 為準。

| 路徑 | 內容 | 狀態 |
|---|---|---|
| `GET /runs/{run_id}/government/observation` | 政府本回合看得到的內容 | ✅ |
| `POST /runs/{run_id}/government/decisions` | 提交政府決策 | ✅ |
| `GET /runs/{run_id}/government/reflections` | 等待反思的天災報告與目前的記憶 | ✅ |
| `POST /runs/{run_id}/government/memory` | 提交新版記憶 | ✅ |
| `GET /world/disasters` | 天災時間表與報告 | ✅ |
| `GET /world/memory` | 政府記憶的所有版本 | 之後需要再做 |
| `GET /world/rules` | 社會規則 | 之後需要再做 |

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

## 尚未完成

原本「接線」清單裡的項目（移除舊的資訊權限、回合流程、調回均衡狀態、掛上政府 router、更新研究目標）都已完成；
預報因為 11/09 會議決定不提供而取消。目前還沒做的：

- **`experiments/disaster_runner.py`** 的 `run_conditions`（分析組）。
- **manifest**：`meta.json` 已經有 config、git commit、模型與 prompt 版本；還缺 `run_id`、config 雜湊值、規則集版本。
- **`/world/memory`、`/world/rules`**：前端需要時再做。
