"""政府與研究資料的 HTTP 路徑。（骨架，尚未接進 api/server.py）

負責人：digiRunner 整合組 / 前端組（/world/*）。接線方式見 docs/architecture.md 的「新方向骨架」。

TODO(digiRunner 整合組)：實作下列路徑，並設定只有政府的身分能呼叫 /government/*
- GET  /government/observation  政府本回合看得到的內容
- POST /government/decisions    提交政府決策
- GET  /government/reflections  等待反思的天災報告與目前的記憶
- POST /government/memory       提交新版記憶

TODO(前端組)：確認需要的欄位後實作下列路徑
- GET  /world/disasters         天災時間表與報告
- GET  /world/memory            政府記憶的所有版本
- GET  /world/rules             社會規則
"""

from __future__ import annotations

from fastapi import APIRouter


def create_government_router(engine) -> APIRouter:
    raise NotImplementedError
