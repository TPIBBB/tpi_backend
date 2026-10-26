# Multi-Agent 文明模擬器（後端）

研究「資訊、權限與權力如何影響 AI 社會」。多個 Agent 在一個有明確規則的小鎮裡工作、交易、分享消息、申請權限；
所有行動都由模擬引擎驗證與結算，再以可量化的指標比較不同制度。

本 repo 是模擬引擎、Agent、world-api 與分析。視覺化介面在另一個 repo：
[multi-agent-civilization-sim-frontend](https://github.com/greentea17dog/multi-agent-civilization-sim-frontend)。

## 快速開始

需要 Python 3.11+。

```bash
pip install -e ".[api,dev]"

# 單次模擬（紀錄寫到 runs/）
python -m civsim run --config configs/baseline.yaml

# 批次實驗：多組條件 × 5 個 seed，輸出 summary.csv
python -m civsim experiment configs/baseline.yaml configs/hierarchical.yaml --repeats 5

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
  world/             模擬引擎：回合流程、行動驗證與結算、市場、世界事件
  policy/            模擬世界的權限與制度（equal / hierarchical）
  agents/            Agent 決策：rule_based（基準線）、llm（待實作）
  api/               world-api（FastAPI），註冊在 digiRunner 後面
  gateway/           Agent 端經 Gateway 呼叫 world-api 的 client
  storage/           事件紀錄（JSONL；PostgreSQL 待實作）
  analysis/          指標：吉尼係數、權力集中度、穩定性…
  experiments/       重複實驗與摘要
configs/             實驗條件設定檔
db/schema.sql        PostgreSQL schema
docs/architecture.md 架構與設計原則
tests/
```

## 分工

見 [CONTRIBUTING.md](CONTRIBUTING.md)。各模組待辦事項以 `TODO(組別)` 標註在程式碼中：

```bash
git grep -n "TODO("
```
