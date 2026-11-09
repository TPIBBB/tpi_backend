
# Multi-Agent 文明模擬器（後端）

研究「AI Agent(政府) 面對天災時會如何決策」。 AI 政府治理一群規則式平民，社會經歷 N 次天災；觀察政府的決策，以及每次天災後的固定天數內，價格能否恢復到市場均衡價格。

此 repo 是僅負責後端(模擬引擎、Agent、world-api等) 。前端介面在：
[tpi_frontend](https://github.com/TPIBBB/tpi_frontend)。

# 研究問題(目標)

每次天災結束後，在固定的天數（評估期）內，價格能否恢復到市場均衡價格？經歷多次天災後，這個結果會如何變化？

每次天災的評估期長度都相同，結果才能互相比較。

# 模擬設計

# 角色

| 角色 | 控制方式 | 說明 |
|---|---|---|
| 政府 | AI Agent（LLM） | 從預報開始到評估期結束，每個 tick 都決策；平時是否決策待討論 (主要觀察對象) |
| 平民 | Rule-based Agent | 依固定規則工作、交易，對政府決策與市場變化做出反應 (職業、階級等待定) |

# 實驗流程

```
社會正常運作 → 天災預報 → 天災發生 → 評估期 → 記錄價格是否恢復均衡與決策內容
      ▲                                           │
      └──── 更新政府記憶、視情況新增社會規則 ◄────┘
```

政府在各階段提出的決策，都由引擎驗證並結算。每次評估期結束，不論價格是否恢復，引擎都會把社會調回同一個均衡狀態，再進入下一次天災；政府記憶會保留。

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

政府的記憶存成 Markdown 檔。每次天災的評估期結束時，政府可修改這份記憶，也可選擇不更新，並帶著它面對下一次天災。藉此觀察政府是否真的會從過去的天災中學習。

# 社會規則

社會規則有明確的 do and don't，例如：

- 不能亂殺平民
- 不能隨意發行貨幣

規則不會一開始就全部訂好。先觀察前幾次天災中，政府是否做出違反社會邏輯的決策，再把需要的規則加上去。

# 實驗設計(還沒討論)

僅觀察 AI 政府，無法確定價格能否恢復是因為記憶，還是 LLM 隨機性或運氣，需要分組別進行比較。真正進行比較的只有 A、C 組。

| 組別 | 政府 | 記憶 | 社會規則 | 用途 |
|---|---|---|---|---|
| A 沒記憶 | AI Agent | 無 | 有(參照B行為) | 對照組 |
| B 有記憶(沒有社會規則) | AI Agent |有 | 無 | 觀察無規則限制時政府可能做出哪些不合理舉動，藉此訂定 A、C 組的社會規則；不參與比較 |
| C 有記憶(有社會規則) | AI Agent | 有 | 有(參照B行為) | 看記憶能否提高恢復成功率 |

**固定不變的條件**：除了表中的變因，各組使用相同的初始世界、平民設定、引擎規則、prompt 版本，以及相同的天災時間表與強度。每次天災的強度與預警時間（預報開始到天災開始的 tick 數）都相同，第一版的預報不設誤差。

**重複次數**：每組用同一批 seed 各跑多次，比較平均與差異。LLM 每次的回答可能不同，只跑一次的結果可能只是運氣。

# 公民細節

- 特性：有無買賣、有無產出 (4種)
(有產出的人產量隨機)
- persona：會不會遵守政府政策、sloth、greed、risk tolerance、gluttony (七宗罪)

# 下周開會內容

- 決定社會規則要有哪些do and don't

# 待討論

- **實驗方式**：
  1、比較n次看n次內成功次數 
     問題：實驗A成功率為隨機，可能會不準確
  2、觀察經歷到第幾次會成功
     問題：實驗C在經歷一次.成功後寫進記憶markdown後可能會都成功，之後實驗會沒意義(？)

- **成功標準**：
  1、固定的數字
     優：所有天災的標準都相同
     缺：價格水準若有變動，可能造成永遠達標或永遠達不到
  2、或依據和穩定期時的價格比較（穩定期：社會沒有經歷天災時的正常社會）
     優：標準來自模擬本身的正常價格，不必另外猜數字
     缺：要先確認沒有天災時，價格會穩定在某個範圍內

  11/9：設定均衡價格區間 用數值來自穩定期多次均衡價格的平均值 天災發生後政府將價格穩定在區間直到周期結束就算成功。

- **怎樣算恢復**：
  1、評估期內只要碰到均衡價格就算
  2、維持均衡價格到評估期結束
  
 11/9：維持均衡價格到評估期結束
  
- **均衡狀態標準**：
  每次調回的同一個狀態要從哪裡來？初始世界，或第一次穩定期結束時的快照？
  人口要不要補回？若不補回，後面幾次天災的價格變化，可能分不清是政府決策成功，還是人口變少、需求下降
  政府預算與儲備要不要調回？若調回，政府無法把資源累積到下一次天災，跨天災能留下的只有記憶

- **B 組的「亂搞」怎麼記錄**：
  B 組沒有社會規則，決策不會因違反社會規則被拒絕（資源不足等做不到的決策仍會被拒絕），所以引擎本身不會留下「違規」的紀錄
  什麼樣的決策算「亂搞」？是看行動種類（例如處決、徵糧），還是看行動的程度（例如發行多少貨幣才算過頭）？

- **B組社會規則何時定案**
  規則更新後，A、C 組都要用新版本重跑。感覺要先跑 B 組把規則定好，再跑 A、C 組，用同一版規則的結果比較。
  
- **政府平時可不可以決策**：
  1、可以
     問題：穩定期的價格和狀態會受政府影響，A、C 組的基準可能不同；政府可能提前囤積資源，LLM 費用也較高
  2、不可以，只從預報開始決策
     問題：政府無法在預報前準備，平時的政策（例如收稅）也不會運作

- **政府看得到什麼**：
  政府的觀察要包含哪些？例如價格、自己的預算與儲備、死亡人數、挨餓人數、平民的庫存。給多少資訊是否影響實驗結果
  
- **「遵守政府政策」的具體行為**：
  需定義對每一項政府行動，若平民不遵守時分別會做什麼？
    - `price_cap`：用超過上限的價格私下交易？乾脆不賣？
    - `collect_tax`：逃稅？少報收入？
    - `seize_food`：藏糧？反抗？
    - `publish_forecast`：不相信預報？還是照樣囤糧？
   政府能不能知道誰沒有遵守？不遵守有沒有懲罰？

# Git 協作流程

開工前先 pull，做完依序 add → commit → pull → push。push 之前再 pull 一次，有衝突就會出現在自己電腦上，比較好處理。

第一次使用前先設定一次，讓 `git pull` 遇到雙方都有新 commit 時用合併處理：

```bash
git config --global pull.rebase false
```

## 每次的流程

```bash
# 1. 開工前：取得最新版本
git pull origin main

# 2. 做完後：查看改了哪些檔案
git status

# 3. 加入要提交的檔案（只加自己改的，避免用 git add . 把不相關的檔案一起送出）
git add 檔案路徑

# 4. 提交，訊息寫這次做了什麼
git commit -m "說明"

# 5. push 前再取得一次最新版本
git pull origin main

# 6. 推上 GitHub
git push origin main
```

## 發生衝突時

第 5 步出現 `CONFLICT` 時：

1. 執行 `git status`，標示 `both modified` 的就是衝突的檔案。
2. 打開檔案，找到 `<<<<<<<`、`=======`、`>>>>>>>` 標記，保留正確的內容並刪掉標記。
3. 執行 `git add 檔案路徑`，標記這個檔案已處理。
4. 執行 `git commit`，使用預設的合併訊息。若進入 vim 編輯器，輸入 `:wq` 再按 Enter 離開。
5. 執行 `git push origin main`。

不確定怎麼處理時，執行 `git merge --abort` 回到 pull 之前的狀態，再到群組問。

## 常用指令

| 指令 | 用途 |
|---|---|
| `git status` | 查看目前改了哪些檔案 |
| `git diff` | 查看還沒 add 的修改內容 |
| `git restore --staged 檔案路徑` | 把檔案從 add 中移除，修改內容還在 |
| `git restore 檔案路徑` | 放棄這個檔案還沒 add 的修改，**無法復原** |

## 注意事項

- **不要用 `git push --force`**：會把別人推上去的 commit 蓋掉。
- **push 前先跑測試**：執行 `python -m pytest`，推上去後 CI 也會再檢查一次。

# CI（自動測試）

CI 會在 GitHub 上自動安裝專案並跑測試，確認推上去的程式能正常運作，不會只在自己電腦上能跑。設定檔在 [.github/workflows/ci.yml](.github/workflows/ci.yml)。

## 什麼時候會執行

- 推到 `main` 時
- 開 PR 或更新 PR 時
- 在 GitHub 的 **Actions** 分頁手動執行時

同一個 branch 短時間內推了好幾次時，只會保留最新一次，舊的會自動取消。

## 執行步驟

| 步驟 | 做什麼 | 什麼時候會失敗 |
|---|---|---|
| 1. 下載程式碼 | 取出這次 push 的版本 | 幾乎不會 |
| 2. 安裝 uv | 準備 Python 環境，並快取依賴，讓之後跑得比較快 | GitHub 服務異常時 |
| 3. 安裝依賴 | 依 `uv.lock` 安裝套件，Python 版本依 `.python-version`（3.12） | 改了 `pyproject.toml` 的依賴，卻沒更新 `uv.lock` |
| 4. 跑測試 | 執行 `pytest` | 任何一個測試失敗 |

通常 1～2 分鐘內會跑完，超過 10 分鐘會自動停止並算失敗。

## 怎麼看結果

- **commit 旁的圖示**：黃點代表執行中、綠勾代表通過、紅叉代表失敗。
- **Actions 分頁**：點最新一筆「CI」，再點失敗的步驟，就能看到完整的錯誤訊息。

## 失敗時怎麼處理

1. 到 Actions 分頁找出是哪一步失敗。
2. 依失敗的步驟處理：
   - **安裝依賴失敗**：在自己電腦執行 `uv lock`，把更新後的 `uv.lock` 一起 commit。
   - **測試失敗**：在自己電腦執行 `python -m pytest`，修到通過再 push。如果是因為重寫模組，舊測試已經不適用，就一起刪掉或改寫對應的測試。
3. 修好後再 push 一次，CI 會自動重跑。

如果懷疑只是 GitHub 暫時出錯，可以在失敗的那次執行頁面按 **Re-run jobs** 重跑。

想在自己電腦上用和 CI 完全相同的方式檢查，執行：

```bash
uv sync --locked --all-extras
uv run --locked pytest
```

## CI 不會檢查什麼

- **不會呼叫真實的 LLM**：測試不應該依賴 API key，也不應該花費 LLM 費用。
- **不會連 digiRunner 或 PostgreSQL**：這些要在自己電腦上用 `docker compose up` 測試。
- **不會跑實驗**：實驗結果要由負責實驗與分析的人另外執行和確認。

CI 失敗時請先修好，不要放著繼續推新的修改，否則之後很難判斷是哪次修改造成的問題。

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

# 專案結構

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
