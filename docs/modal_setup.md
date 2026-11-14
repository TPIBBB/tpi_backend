# 用自己的 Modal 帳號跑 civsim 實驗

LLM 政府用 Modal 架的 Qwen 模型（`Qwen/Qwen2.5-7B-Instruct`）。每個人用自己的 Modal 帳號部署一台，用的是自己的免費額度。

整個流程第一次大約要 30 分鐘，其中大部分時間在等部署和下載模型。

## 1. 安裝 uv（只要做一次）

uv 是 Python 的套件和環境管理工具，負責建立專案的 `.venv`、安裝套件、執行指令。

先檢查是不是已經裝過：

```powershell
uv --version
```

有出現版本號就跳到步驟 2。出現「找不到指令」的話，在 PowerShell 執行（整行一起複製，不要換行）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

裝完把 PowerShell（或 VS Code）關掉再重開，再執行一次 `uv --version`，有出現版本號就是成功了。

## 2. 更新專案、安裝套件

```powershell
cd <你的路徑>\tpi_backend
git switch main
git pull
uv sync --all-extras
```

- `git switch main`、`git pull`：切到 main 並更新到最新版。Modal 相關的檔案（`deploy/modal_llm.py`、`src/civsim/agents/llm_client.py`、`configs/group_a.yaml`、`configs/group_c.yaml`）都在 main 上

- `uv sync --all-extras`：照 `uv.lock` 建立 `.venv` 並安裝所有套件，包含 LLM、API、測試用的選用套件，不用自己建虛擬環境。

⚠️ 之後所有指令都要在 `tpi_backend` 資料夾裡執行

## 3. 註冊 Modal 帳號

1. 到 https://modal.com 註冊，可以用 GitHub 或 Google 帳號登入。
2. 免費方案每月有 $30 的額度。我們用的 L4 GPU 大約 $0.8／小時，而且只有在呼叫模型時才會開機計費。

## 4. 讓這台電腦登入你的 Modal

```powershell
uvx modal setup
```
它會打開瀏覽器，按確認授權就好。`uvx` 會自動下載 modal 指令，不用另外安裝。

## 5. 設定模型伺服器的密碼

先產生一組隨機密碼：

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```
複製印出來的那串，再存進 Modal（把 `<你的密碼>` 換成剛才那串，不用加角括號）：

```powershell
uvx modal secret create civsim-llm-key VLLM_API_KEY=<你的密碼>
```
⚠️ 名稱一定要是 `civsim-llm-key`，部署程式是用這個名字找密碼的。這組密碼等一下還要用，先記下來。

## 6. 部署模型

```powershell
$env:PYTHONIOENCODING="utf-8"
uvx modal deploy deploy/modal_llm.py
```
第一次大約要 5～10 分鐘（安裝 vllm、torch 等套件）。成功時最後會出現：

```
✓ Created Function serve
└── https://<你的帳號>--civsim-llm-serve.<地區>.modal.run
✓ App deployed in ...s! 🎉
```

把這個網址複製下來。

（第一行設定編碼，是為了避免 Windows 印出 ✓ 這類符號時報錯。）

## 7. 填寫 .env

```powershell
Copy-Item .env.example .env
```

打開 `.env`，填上網址和密碼：

```
LLM_PROVIDER=modal
LLM_BASE_URL=https://<步驟 6 的網址>/v1
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
LLM_API_KEY=<步驟 5 的密碼>
```
⚠️ 網址後面一定要加 `/v1`。

## 8. 測試連線

```powershell
uv run civsim llm-check
```

第一次要等比較久，大約 5～15 分鐘：要排隊等 GPU、下載約 15 GB 的模型、再載入到 GPU。畫面停住是正常的，不要關掉。

最後出現「--- LLM 回應 ---」和「--- 解析出的決策 ---」就是成功了。之後模型會存在 Modal 上，不用重新下載。GPU 開著的期間，每次呼叫只要幾秒。

## 9. 跑實驗

```powershell
# A 組：LLM 政府、沒有記憶
uv run civsim run --config configs/group_a.yaml

# C 組：LLM 政府、有記憶
uv run civsim run --config configs/group_c.yaml
```

結果會存在 `runs/<組別>/seed42/`：

- `summary.json`：每次天災有沒有恢復
- `llm_calls.jsonl`：政府每次的 prompt 和回應
- `memory.jsonl`：C 組政府的記憶

## 10. 用完記得關掉

GPU 閒置 5 分鐘會自動關機，關機後不計費。如果想完全停掉：

```powershell
uvx modal app stop civsim-llm
```

停掉之後要再用，重新執行步驟 6 的 deploy 就好。這次會用快取，很快就部署完。

## 常見問題

| 狀況 | 原因與解法 |
|---|---|
| `civsim` 找不到 / `Failed to spawn: civsim` | 不在 `tpi_backend` 資料夾裡，或是前面忘了加 `uv run` |
| `HTTP 404: modal-http: invalid function call` | 模型沒有部署，或已經被停掉了，重新執行步驟 6 |
| `HTTP 401` | `.env` 的 `LLM_API_KEY` 跟步驟 5 存的密碼不一樣 |
| 等了很久都沒反應 | 正在排隊等 GPU，或第一次下載模型。用 `uvx modal app logs civsim-llm` 看進度 |
| 部署時出現 `UnicodeEncodeError` | 先執行 `$env:PYTHONIOENCODING="utf-8"` 再部署 |
| 想看額度用了多少 | Modal 網站右上角的 Usage / Billing |
