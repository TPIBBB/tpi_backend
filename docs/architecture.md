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
