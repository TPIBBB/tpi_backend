# 分工與協作方式

## 模組負責分工

| 組別 | 負責目錄 | 主要待辦 |
|---|---|---|
| 模擬引擎組 | `world/`、`policy/`、`models.py` | 調整經濟平衡、雙邊交易、更多世界事件、實驗 E 的投票改制度 |
| Agent 決策組 | `agents/` | 選定 LLM 並實作 `LLMAgent.call_llm`、prompt 設計、記憶摘要、降低呼叫成本 |
| digiRunner 整合組 | `api/`、`gateway/`、`docker-compose.yml` | 部署 digiRunner、把 world-api 註冊為後端、每個 Agent 的身分與存取政策 |
| 資料庫與分析組 | `storage/`、`analysis/`、`experiments/`、`db/` | `PostgresRecorder`、補齊指標（合作效率、制度存續…）、分析報告與圖表 |
| 前端組 | 另一個 repo：`TBIBBB/tpi_frontend` | 視覺化；需要新 API 時在本 repo 的 `api/server.py` 的 `/world/*` 新增 |

組別名稱與人員請自行填入。程式中的 `TODO(組別)` 是各組的起點。

## 模組之間的介面（改動前請先在群組討論）

- `models.py`：`Action`、`Observation`、`Event` 是所有組共用的資料格式
- `AgentController.decide(obs) -> list[Action]`：引擎與 Agent 之間唯一的介面
- `Recorder.record_tick(world, events, metrics)`：引擎與儲存之間的介面
- world-api 的 HTTP 路徑：`/agents/*`、`/admin/*`、`/world/*`
  （`/world/*` 的回傳格式是前後端的約定，改動時要同步更新前端 repo 的 `src/api/types.ts`）

## Git 流程

1. 不要直接 push 到 `main`
2. 開分支：`git checkout -b <組別>/<功能>`，例如 `agents/llm-provider`
3. push 前先跑 `python -m pytest`
4. 開 Pull Request，至少一位其他組員 review 後再 merge

## 設計原則

1. **Agent 說的話不算數**：Agent 只能提出 `Action`，世界狀態只由 `world/rules.py` 改變
2. **只看得到有權限的資訊**：Agent 只能拿到 `engine.observe()` 給的內容
3. **可重現**：所有隨機都來自 config 的 `seed`；LLM 版本與 prompt 版本要記錄下來
4. **一次只改一個條件**：新實驗請複製現有 config，只改要研究的那一項
