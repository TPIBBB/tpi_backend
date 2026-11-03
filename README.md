# Multi-Agent 文明模擬器（後端）

研究「AI Agent(政府) 面對天災時會如何決策」。 AI 政府治理一群規則式平民，社會經歷 N 天災；觀察政府的決策，研究在經歷幾次天災後，能成功避免市場價格波動/飢荒發生(？)

此 repo 是僅負責後端(模擬引擎、Agent、world-api等) 。前端介面在：
[tpi_frontend](https://github.com/TPIBBB/tpi_frontend)。

# 研究問題(目標)

經歷多次天災後，政府何時可以達到這兩個目標？(擇一)

1. **市場穩定**：市場價格維持平衡，不會因天災造成大幅度變動
2. **避免飢荒**：就算天災來臨，也不會導致飢荒

# 模擬設計

# 角色

| 角色 | 控制方式 | 說明 |
|---|---|---|
| 政府 | AI Agent（LLM） | 天災發生時做出決策 (主要觀察對象) |
| 平民 | Rule-based Agent | 依固定規則工作、交易，對政府決策與市場變化做出反應 (職業、階級等待定) |

# 實驗流程

```
社會正常運作 → 天災發生 → 政府決策 → 引擎驗證並結算 → 記錄價格、飢荒與決策內容
      ▲                                                     │
      └──────── 更新政府記憶、視情況新增社會規則 ◄──────────┘
```

# 系統架構

```
前端 ─────┐
          ├→ digiRunner（API Gateway）→ world-api（FastAPI）→   模擬引擎
Agent 端 ─┘
```

- **模擬引擎**：推進回合、觸發天災，驗證決策並更新世界狀態。(AI 政府提出決策後，結果由引擎依固定規則計算，避免 LLM 憑空創造資源，不同實驗用同一套規則進行比較)
- **world-api**：模擬引擎對外的 HTTP 介面，前端與 Agent 透過它查詢世界狀態、送出行動。
- **digiRunner**：管理前端與 Agent 對 world-api 的呼叫。

詳細設計見 [docs/architecture.md](docs/architecture.md)。

# 記憶

政府的記憶存成 Markdown 檔。經歷幾次天災後，如果政府有新的發現，可修改這份記憶，並帶著它面對下一次天災。藉此觀察政府是否真的會從過去的天災中學習。

# 社會規則

社會規則有明確的 do and don't，例如：

- 不能亂殺平民
- 不能隨意發行貨幣

規則不會一開始就全部訂好。先觀察前幾次天災中，政府是否做出違反社會邏輯的決策，再把需要的規則加上去。

# 實驗設計(還沒討論)

僅觀察 AI 政府，無法確定目標達成是因為政府決策，還是天災較輕、市場自行恢復或運氣好，需要分組別進行比較。

| 組別 | 政府 | 記憶 | 社會規則 | 用途 |
|---|---|---|---|---|
| A 不介入(對照組) | 無 | 無 | 無 | 衡量天災本身造成的影響 |
| B 沒有記憶 | AI Agent | 無 | 無 | 和 A 比較，看 AI 政府的決策有沒有幫助 |
| C 有記憶(主要實驗組) | AI Agent | 有 | 無 | 和 B 比較，看記憶有沒有幫助 |

**固定不變的條件**：除了表中的變因，各組使用相同的初始世界、平民設定、引擎規則、prompt 版本，以及相同的天災時間表與強度。

**重複次數**：每組用同一批 seed 各跑多次，比較平均與差異。LLM 每次的回答可能不同，只跑一次的結果可能只是運氣。

**進行順序**：

1. 先跑 C，觀察政府的決策
2. 加上 A，確認政府是否比完全不介入更好
3. 加上 B，確認政府是否真的從記憶中學習

**暫定**：一次模擬經歷 10 次天災，每組 5 個 seed；回合數由天災各段長度推算（需先估算 LLM 費用）。

# 公民細節

# 下周開會內容

- 決定社會規則要有哪些do and don't

# 設計決定

完整內容見 [docs/architecture.md](docs/architecture.md)。

- **目標的判定標準**：沒有飢荒 = 評估期內死亡人數為 0；價格穩定 = 價格最大偏離比 A 組（不介入）低 Z%
- **政府可以做哪些決策**：封閉清單，包含穩定、財政、強制、發布預報四類，刻意納入可能違規的行動
- **違規決策的處理**：引擎拒絕，並把拒絕理由回饋給政府
- **記憶更新的時機**：每次天災評估期結束都可以更新，政府可選擇不更新；記憶不跨 run
- **實驗的比較方式**：規則集在 run 內固定、有版本號；每個 run 有 manifest 記錄所有版本
- **範圍**：平民維持 rule-based；移除舊方向的資訊權限機制；實驗中政府經由 digiRunner 呼叫 world-api

# 要討論的

- **目標是擇一還是兩個都要**：研究問題寫「擇一」，但上面的判定標準與政府的 prompt 都假設兩個目標同時達成
- **數值**：平時的決策間隔 N、價格穩定的門檻 Z%、天災各段的長度、每組的 seed 數（暫定 5）
- **LLM**：供應商與模型 ID（正式實驗前鎖定）、temperature
- **政府行動的細節**：各行動的參數範圍、初始預算與儲備、每個行動對應的平民反應規則

## 快速開始

需要 Python 3.11+。以下指令目前執行的是尚未加入政府的版本。

```bash
pip install -e ".[api,dev]"

# 單次模擬（紀錄寫到 runs/）
python -m civsim run --config configs/baseline.yaml

# 批次實驗：重複 5 個 seed，輸出 summary.csv
python -m civsim experiment configs/baseline.yaml --repeats 5

# 測試
python -m pytest
```

### 經由 API（digiRunner）執行

```bash
python -m civsim serve --config configs/baseline.yaml     
# 啟動 world-api，文件在 http://localhost:8000/docs
python -m civsim remote --base-url http://localhost:8000   
# Agent 端透過 HTTP 呼叫
```

接上 digiRunner 後，`--base-url` 改成 Gateway 位址（或設定 `.env` 的 `DIGIRUNNER_BASE_URL`），Agent 的每次呼叫就會經過 Gateway。PostgreSQL 與 digiRunner 用 `docker compose up` 啟動（digiRunner 設定待補）。

### 給前端使用的 API

| 路徑 | 內容 |
|---|---|
| `GET /world/state` | 目前回合、市場、每個 Agent 的狀態與權限 |
| `GET /world/metrics` | 每回合指標 |
| `GET /world/events?since_tick=N` | 第 N 回合之後的事件 |

前端開發伺服器的來源預設允許 `http://localhost:5173`，其他來源用環境變數 `CIVSIM_CORS_ORIGINS` 設定（逗號分隔）。

## 專案結構

```
src/civsim/
  models.py          核心資料結構（AgentState、Action、Observation、WorldState…）
  config.py          實驗設定（YAML）
  cli.py             命令列入口
  world/             模擬引擎：回合流程、行動驗證與結算、市場、世界事件（天災）
  policy/            模擬世界的權限與制度（舊方向，預定移除）
  agents/            Agent 決策：rule_based（平民）、llm（政府，待實作）
  api/               world-api（FastAPI），註冊在 digiRunner 後面
  gateway/           Agent 端經 Gateway 呼叫 world-api 的 client
  storage/           事件紀錄（JSONL；PostgreSQL 待實作）
  analysis/          指標：價格、挨餓與死亡人數、吉尼係數…
  experiments/       重複實驗與摘要
configs/             實驗條件設定檔（hierarchical、no_sharing 為舊方向的條件）
db/schema.sql        PostgreSQL schema
docs/architecture.md 架構與專案邊界
tests/
```
