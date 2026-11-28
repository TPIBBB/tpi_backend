"""匯出 digiRunner 的存取紀錄：某個 run 經過 digiRunner 的每一次呼叫（時間、client、路徑、狀態碼）。

前提：digiRunner 的 系統設定 → Setting 已把 TSMP_APILOG_FORCE_WRITE_RDB 改成 true，改了之後的呼叫才會存進
它的資料庫。紀錄先寫在 TSMP_REQ_LOG / TSMP_RES_LOG，digiRunner 的排程再複製到 TSMP_REQ_RES_LOG_HISTORY
（原始碼裡保留一年），所以兩邊都查，用 ID 去掉重複。

讀法：digiRunner 容器裡有它自己的 H2 資料庫服務（port 9090，只有容器內部連得到），用 docker exec 在容器裡
執行 H2 附的查詢工具。查詢只有 SELECT，不會改到 digiRunner 的資料；結果先寫成容器裡的暫存 CSV，讀完就刪掉。

只收網址裡有 /runs/<run_id>/ 的呼叫，也就是政府的路徑。GET /runs（列出 run）和換 token 的網址裡沒有 run_id，
分不出是哪個 run 的，不收。被 digiRunner 擋下的呼叫（401、403）也會收，但 digiRunner 不記它們的 client。
"""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

IMAGE = "tpisoftwareopensource/digirunner-open-source"
FILENAME = "digirunner_access.jsonl"
_DB_URL = "jdbc:h2:tcp://localhost:9090//opt/digirunner/db/dgrdb;NON_KEYWORDS=VALUE;MODE=MySQL"
_RUN_ID = re.compile(r"[A-Za-z0-9-]{1,64}")

# 在容器裡執行：用 H2 的查詢工具把結果寫成 CSV、印出來、再刪掉暫存檔。
# 網址、SQL、暫存檔路徑用 $1 $2 $3 傳進去，不用處理引號。查詢工具自己的輸出丟到 stderr，失敗時才拿來顯示。
_SCRIPT = (
    'jar=$(ls /opt/digirunner/party-3rd-jar/h2-*.jar 2>/dev/null | head -n 1); '
    '[ -n "$jar" ] || { echo "容器裡找不到 H2 的 jar（digiRunner 的版本和預期不同？）" >&2; exit 3; }; '
    'java -cp "$jar" org.h2.tools.Shell -url "$1" -user sa -password "" -sql "$2" 1>&2 && cat "$3"; '
    'code=$?; rm -f "$3"; exit $code'
)

Runner = Callable[..., subprocess.CompletedProcess]


class AccessLogError(Exception):
    """匯出失敗。訊息可以直接給使用者看。"""


def query(run_id: str) -> str:
    """查某個 run 的 SQL。run_id 只能有英數字和 -，所以直接放進 SQL 也不會被當成指令。"""
    if not _RUN_ID.fullmatch(run_id):
        raise AccessLogError(f"run_id 格式不對：{run_id!r}（只能有英文、數字和 -，例如 20261129-a572）")
    where = f"URL LIKE '%/runs/{run_id}/%'"
    return (
        "SELECT q.ID, q.RTIME, q.CID, q.MODULE_NAME, q.URL, r.HTTP_STATUS, r.EXE_STATUS, r.ELAPSE, r.ERR_MSG "
        f"FROM TSMP_REQ_LOG q LEFT JOIN TSMP_RES_LOG r ON r.ID = q.ID WHERE q.{where} "
        "UNION ALL "
        "SELECT ID, RTIME, CID, MODULE_NAME, URL, HTTP_STATUS, EXE_STATUS, ELAPSE, ERR_MSG "
        f"FROM TSMP_REQ_RES_LOG_HISTORY WHERE {where}"
    )


def find_container(runner: Runner | None = None) -> str:
    """找正在跑的 digiRunner 容器（不管 docker compose 的專案叫什麼名字）。"""
    r = _docker(runner, "ps", "--filter", f"ancestor={IMAGE}", "--format", "{{.Names}}")
    if r.returncode != 0:
        raise AccessLogError("docker ps 失敗，Docker Desktop 有開嗎？\n" + _tail(r.stderr))
    names = _text(r.stdout).split()
    if not names:
        raise AccessLogError("找不到正在跑的 digiRunner：先開 Docker Desktop，再執行 docker compose up -d dgr")
    if len(names) > 1:
        raise AccessLogError(f"有好幾個 digiRunner 在跑（{'、'.join(names)}），用 --container 指定要哪一個")
    return names[0]


def fetch(run_id: str, container: str, runner: Runner | None = None) -> list[dict]:
    """從 digiRunner 的資料庫讀出這個 run 的存取紀錄，依時間排好。"""
    sql = query(run_id)
    tmp = f"/tmp/civsim-access-{uuid.uuid4().hex}.csv"
    call = "CALL CSVWRITE('{}', '{}', 'charset=UTF-8')".format(tmp, sql.replace("'", "''"))
    r = _docker(runner, "exec", container, "sh", "-c", _SCRIPT, "sh", _DB_URL, call, tmp)
    if r.returncode != 0:
        raise AccessLogError(f"讀不到 digiRunner 的資料庫（容器 {container}）：\n" + _tail(r.stderr))
    return parse(_text(r.stdout))


def parse(text: str) -> list[dict]:
    """CSV → 一筆一個 dict。同一個 ID 同時在暫存表和歷史表時只留一筆（優先留有回應結果的）。"""
    rows: dict[str, dict] = {}
    for raw in csv.DictReader(io.StringIO(text)):
        row = {
            "time": _blank(raw["RTIME"]),  # digiRunner 容器的時間（docker-compose.yml 設 TZ=Asia/Taipei），只到秒
            "client_id": _blank(raw["CID"]),  # 被擋下的呼叫是 None
            "api": _blank(raw["MODULE_NAME"]),  # 註冊在 digiRunner 的路徑，例如 /runs/{p}/government/observation
            "url": _blank(raw["URL"]),
            "http_status": _int(raw["HTTP_STATUS"]),
            "success": {"Y": True, "N": False}.get(_blank(raw["EXE_STATUS"]) or ""),
            "elapsed_ms": _int(raw["ELAPSE"]),
            "error": _error(raw["ERR_MSG"]),  # 被擋下的原因
            "log_id": raw["ID"].strip(),  # digiRunner 裡這筆紀錄的 ID
        }
        old = rows.get(row["log_id"])
        if old is None or (old["http_status"] is None and row["http_status"] is not None):
            rows[row["log_id"]] = row
    return sorted(rows.values(), key=lambda r: (r["time"] or "", r["log_id"]))


def write(rows: list[dict], out_dir: Path) -> Path:
    """寫成 out_dir/digirunner_access.jsonl。舊檔的筆數比這次多時不覆蓋（代表 digiRunner 的紀錄可能被刪過）。"""
    path = out_dir / FILENAME
    if path.exists():
        with path.open(encoding="utf-8") as f:
            old = sum(1 for line in f if line.strip())
        if old > len(rows):
            raise AccessLogError(f"{path} 已經有 {old} 筆，這次只查到 {len(rows)} 筆"
                                 f"（digiRunner 的紀錄可能被刪過），所以沒有覆蓋")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)
    return path


def export(run_id: str, out_dir: Path, container: str | None = None,
           runner: Runner | None = None) -> tuple[Path, list[dict]]:
    query(run_id)  # 先檢查 run_id，格式錯就不用去找 docker
    rows = fetch(run_id, container or find_container(runner), runner)
    if not rows:
        raise AccessLogError(
            f"digiRunner 裡沒有 run {run_id} 的紀錄。可能是：run_id 打錯；這個 run 沒有經過 digiRunner"
            "（civsim govern 沒加 --base-url http://localhost:31080）；或跑的時候 TSMP_APILOG_FORCE_WRITE_RDB 還不是 true")
    return write(rows, out_dir), rows


def _docker(runner: Runner | None, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    try:
        return (runner or subprocess.run)(["docker", *args], capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise AccessLogError("找不到 docker 指令：有裝 Docker Desktop 嗎？") from None
    except subprocess.TimeoutExpired:
        raise AccessLogError(f"docker {args[0]} 超過 {timeout:g} 秒沒有回應") from None


def _text(data: bytes | str | None) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def _tail(data: bytes | str | None, lines: int = 15) -> str:
    return "\n".join(_text(data).strip().splitlines()[-lines:])


def _blank(value: str | None) -> str | None:
    value = (value or "").strip()  # digiRunner 的空欄位常是一個空白
    return value or None


def _int(value: str | None) -> int | None:
    value = _blank(value)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _error(value: str | None) -> str | None:
    """digiRunner 的錯誤訊息常是整段 JSON，取出裡面的 message。"""
    value = _blank(value)
    if value is None:
        return None
    try:
        return json.loads(value).get("message") or value
    except (ValueError, AttributeError):
        return value
