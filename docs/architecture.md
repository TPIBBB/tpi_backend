# 架構

## 一個回合

```
begin_tick()   世界事件（例如「明天糧食可能減產」）→ 真相寫入 modifiers，預報寫入 forecasts
observe()      每個 Agent 只拿到有權限的資訊（read:prices、read:forecast、別人分享的消息）
decide()       Agent 提出行動（work / trade / share_info / request_permission / grant_permission）
validate()     引擎檢查資源、規則與權限，不合法就拒絕並記錄原因
settle()       執行合法行動，更新庫存、價格、權限
upkeep         每人吃 1 單位食物，沒食物就扣健康
record         事件、Agent 狀態、指標寫入 Recorder
```

行動的執行順序每回合隨機打亂，避免固定先後造成優勢。

## 兩種執行模式

**本機模式**（`civsim run` / `civsim experiment`）：引擎直接呼叫 Agent，速度快，適合大量重複實驗。

**API 模式**（`civsim serve` + `civsim remote`）：

```
Agent 決策 (gateway/client.py)
    │  HTTP + 身分憑證
    ▼
digiRunner API Gateway  ── 路由、身分驗證、存取政策、流量限制、存取紀錄
    │
    ▼
world-api (api/server.py) ── 模擬引擎
```

## 兩層權限的區分

| | 模擬世界的權限 | digiRunner 的存取控制 |
|---|---|---|
| 是什麼 | 研究模型的一部分 | 現實系統的 API 安全 |
| 例子 | `read:prices`、`grant:read:forecast` | Agent a03 能不能呼叫 `/agents/a03/observation` |
| 誰決定 | `policy/`，可在模擬中被授予、改變 | digiRunner 的政策設定 |
| 實作位置 | `policy/permissions.py` | digiRunner 後台 / 設定 |

Agent 不能靠宣稱取得權限：模擬內的權限只能透過 `grant_permission` 行動、經引擎驗證後改變。
若之後要讓制度變更同步到 digiRunner（例如投票後開放某個 API），需要另外設計「政策轉換」流程：
制度決策 → 明確的政策物件 → 套用到 PolicyStore，並透過 digiRunner 的管理 API 更新存取規則。

## 目前的簡化（之後可擴充）

- 市場是單一做市商，依淨需求調價；尚無 Agent 之間的雙邊交易
- 世界事件只有「糧食減產」
- 權限只有 `read:prices`、`read:forecast` 兩種

## 新方向骨架

研究方向改為「AI 政府面對天災時如何決策」。下面的模組目前只有介面與 `TODO(組別)`，還沒有接進引擎，
所以現有程式的行為不變。本文件前面的內容描述的仍是現有程式。

| 模組 | 組別 | 內容 |
|---|---|---|
| `world/disasters.py` | 模擬引擎組 | 天災時間表與觸發 |
| `world/government.py` | 模擬引擎組 | 政府的狀態、決策與結算 |
| `world/social_rules.py` | 模擬引擎組 | 社會規則與違規判定 |
| `agents/government.py` | Agent 決策組 | 政府的決策與反思（`GovernmentController`） |
| `analysis/goals.py` | 分析組 | 每次天災的目標判定 |
| `storage/research_records.py` | 資料庫組 | 天災報告、記憶版本、LLM 呼叫的紀錄 |
| `experiments/disaster_runner.py` | 分析組 | 比較不同實驗條件 |
| `api/government.py` | digiRunner 整合組、前端組 | 政府與研究資料的 HTTP 路徑 |

### 預計的回合流程

```
天災觸發        world/disasters.py
政府決策        agents/government.py 提出 → world/social_rules.py 檢查規則 → world/government.py 驗證與結算
平民決策        現有流程
記錄            現有流程
評估與反思      某次天災的評估期結束時：analysis/goals.py 產生報告
                → 政府提出新版記憶 → 引擎驗證後保存（storage/research_records.py）
```

### 接線

把骨架接進引擎時會改到共用介面，請先在群組討論：

- `world/engine.py`：加入上面的流程
- `models.py`：把政府決策併入 `ActionType`，或維持獨立的 `GovernmentDecision`
- `config.py`：新增天災、政府、社會規則、判定標準的設定
- `api/server.py`：掛上 `api/government.py` 的 router；`/world/*` 異動要同步更新前端
