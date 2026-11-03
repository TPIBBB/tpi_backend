# Multi-Agent 文明模擬器（後端）

研究「AI 政府面對天災時會如何決策」。一個 AI 政府治理一群規則式平民，社會反覆經歷天災；
我們觀察政府的決策，並研究它在什麼時候能同時穩住市場價格、避免飢荒。

本 repo 是模擬引擎、Agent、world-api 與分析。視覺化介面在另一個 repo：
[tpi_frontend](https://github.com/TPIBBB/tpi_frontend)。

> 專案剛調整研究方向，程式還沒完全跟上，已完成與待完成的部分見[目前進度](#目前進度)。

## 研究問題

經歷多次天災後，政府何時可以達到這兩個目標？

1. **市場穩定**：市場價格維持平衡，不會大幅變動
2. **沒有飢荒**：就算天災來臨，也不會導致飢荒

## 模擬設計

### 角色

| 角色 | 控制方式 | 說明 |
|---|---|---|
| 政府 | AI Agent（LLM） | 天災發生時做出決策，是主要的觀察對象 |
| 平民 | Rule-based Agent | 依固定規則工作、交易、吃飯，對政府決策與市場變化做出反應 |

### 實驗流程

```
社會正常運作 → 天災發生 → 政府決策 → 引擎驗證並結算 → 記錄價格、飢荒與決策內容
      ▲                                                     │
      └──────── 更新政府記憶、視情況新增社會規則 ◄──────────┘
```

### 記憶

政府的記憶存成 Markdown 檔。經歷幾次天災後，如果政府有新的發現，可以自己修改這份記憶，
並帶著它面對下一次天災。藉此觀察政府是否真的會從過去的天災中學習。

### 社會規則

社會規則是明確的 do and don't，例如：

- 不能亂殺平民
- 不能隨意發行貨幣

規則不會一開始就全部訂好。我們會先觀察前幾次天災中，政府是否做出違反社會邏輯的決策，再把需要的規則加上去。

## 目前進度

| 項目 | 狀態 | 說明 |
|---|---|---|
| 模擬引擎、市場 | 已有 | 回合制，所有行動由引擎驗證與結算 |
| 平民（rule-based） | 已有 | 農夫、樵夫、工匠、商人四種職業 |
| 天災 | 部分完成 | 目前只有「糧食減產」一種 |
| 價格與飢荒指標 | 部分完成 | 已記錄價格、挨餓與死亡人數，尚未判定目標是否達成 |
| 政府（AI Agent） | 待實作 | `agents/llm.py` 已有 LLM 呼叫與解析流程，但 prompt 仍以居民為對象，供應商也還沒選定 |
| 政府的決策行動 | 待實作 | 目前的行動都是平民層級（工作、交易等） |
| 記憶 Markdown | 待實作 | |
| 社會規則與違規紀錄 | 待實作 | |

### 設計決定

完整內容見 [docs/architecture.md](docs/architecture.md)。

- **目標的判定標準**：沒有飢荒 = 評估期內死亡人數為 0；價格穩定 = 價格最大偏離比 IDLE 基準政府低 Z%
- **政府可以做哪些決策**：封閉清單，包含穩定、財政、強制、發布預報四類，刻意納入可能違規的行動
- **違規決策的處理**：引擎拒絕，並把拒絕理由回饋給政府
- **記憶更新的時機**：每次天災評估期結束都可以更新，政府可選擇不更新；記憶不跨 run
- **實驗的比較方式**：主要比較有記憶 vs 無記憶；規則集在 run 內固定、有版本號；每個 run 有 manifest 記錄所有版本
- **範圍**：平民維持 rule-based；移除舊方向的資訊權限機制；實驗中政府經由 digiRunner 呼叫 world-api

### 待討論

- **數值**：平時的決策間隔 N、價格穩定的門檻 Z%、天災各段的長度、每個條件的 seed 數（暫定 5）
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
python -m civsim serve --config configs/baseline.yaml      # 啟動 world-api，文件在 http://localhost:8000/docs
python -m civsim remote --base-url http://localhost:8000   # Agent 端透過 HTTP 呼叫
```

接上 digiRunner 後，`--base-url` 改成 Gateway 位址（或設定 `.env` 的 `DIGIRUNNER_BASE_URL`），
Agent 的每次呼叫就會經過 Gateway。PostgreSQL 與 digiRunner 用 `docker compose up` 啟動（digiRunner 設定待補）。

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

## 分工

見 [CONTRIBUTING.md](CONTRIBUTING.md)。各模組待辦事項以 `TODO(組別)` 標註在程式碼中：

```bash
git grep -n "TODO("
```
