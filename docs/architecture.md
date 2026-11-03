# 新方向骨架

說明新研究方向的架構：AI 政府面對天災時如何決策，包含模組、回合流程與模組之間的介面。

**目前狀態**：下面的模組都還沒有接進引擎。其中 `agents/government.py` 已有實作，其他模組只有介面與 `TODO(組別)`。

## 核心觀念

**政府只能提出決策與新版記憶，世界狀態只由模擬引擎改變。**

引擎對每個決策問兩個問題，分開由兩個模組回答：

| 問題 | 例子 | 模組 |
|---|---|---|
| 應不應該做 | 處決平民是否違反社會規則 | `world/social_rules.py` |
| 做不做得到 | 儲備夠不夠發糧 | `world/government.py` |

社會規則由研究者新增，政府只能讀取、不能修改。

## 模組

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

## 預計的回合流程

| 順序 | 步驟 | 做什麼 | 模組 |
|---|---|---|---|
| 1 | 天災觸發 | 依時間表更新預報、觸發天災 | `world/disasters.py` |
| 2 | 政府提出決策 | LLM 根據看到的資訊提出決策 | `agents/government.py` |
| 3 | 檢查規則 | 判定決策是否違反社會規則 | `world/social_rules.py` |
| 4 | 驗證與結算 | 檢查預算、儲備與參數，通過後更新世界 | `world/government.py` |
| 5 | 平民決策 | 平民依固定規則工作與交易，由引擎驗證與結算 | `agents/rule_based.py`、`world/` |
| 6 | 記錄 | 寫入事件、狀態與指標 | `storage/` |

## 評估與反思

一次天災的評估期結束時，會多做一次評估與反思：

```
analysis/goals.py 產生天災報告
    ↓
政府比較決策與結果，提出新版記憶（也可以不修改）
    ↓
引擎驗證後保存（storage/research_records.py），政府帶著新記憶面對下一次天災
```

每個記憶版本都會保留，才能分析政府的記憶如何變化。

## 模組之間的介面

| 介面 | 模組 | 用途 |
|---|---|---|
| `build_schedule(seed, ticks)` | `world/disasters.py` | 建立天災時間表，只由 seed 決定，不同實驗條件才會遇到相同的天災 |
| `begin_tick_events(world, schedule)` | `world/disasters.py` | 回合開始時更新預報、觸發天災 |
| `GovernmentController.decide(obs)` | `agents/government.py` | 根據 `GovernmentObservation` 提出 `GovernmentDecision` |
| `GovernmentController.reflect(report, memory)` | `agents/government.py` | 回傳新版記憶，不修改時回傳 `None` |
| `find_violations(decision, rules)` | `world/social_rules.py` | 回傳決策違反的規則 |
| `validate(world, decision)` | `world/government.py` | 合法時回傳 `None`，否則回傳拒絕原因 |
| `settle(world, decision)` | `world/government.py` | 執行已驗證的決策並回傳事件紀錄 |
| `evaluate_disaster(disaster, history, events)` | `analysis/goals.py` | 產生一次天災的報告 |
| `first_sustained(reports)` | `analysis/goals.py` | 找出從第幾次天災開始，之後每一次都達標 |
| `ResearchRecorder` | `storage/research_records.py` | 保存天災報告、記憶版本與 LLM 呼叫 |
| `run_conditions(configs, repeats, out_root)` | `experiments/disaster_runner.py` | 每組條件跑多個 seed，輸出每次天災的達標比例 |

## 預計的 HTTP 路徑

都列在 `api/government.py`，目前尚未實作。

| 路徑 | 內容 |
|---|---|
| `GET /government/observation` | 政府本回合看得到的內容 |
| `POST /government/decisions` | 提交政府決策 |
| `GET /government/reflections` | 等待反思的天災報告與目前的記憶 |
| `POST /government/memory` | 提交新版記憶 |
| `GET /world/disasters` | 天災時間表與報告 |
| `GET /world/memory` | 政府記憶的所有版本 |
| `GET /world/rules` | 社會規則 |

`/government/*` 只有政府的身分能呼叫；`/world/*` 的欄位由前端組確認。

## 接線

把骨架接進引擎時會改到共用介面，請先在群組討論：

| 檔案 | 要改什麼 |
|---|---|
| `world/engine.py` | 加入上面的流程 |
| `models.py` | 把政府決策併入 `ActionType`，或維持獨立的 `GovernmentDecision` |
| `config.py` | 新增天災、政府、社會規則、判定標準的設定 |
| `api/server.py` | 掛上 `api/government.py` 的 router；`/world/*` 異動要同步更新前端 |
| `world/events.py` | `generate_events` 由 `begin_tick_events` 取代 |
