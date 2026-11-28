"""匯出 digiRunner 存取紀錄的測試：用假的 docker，不需要真的開 digiRunner。"""

import json
import subprocess

import pytest

from civsim.cli import main
from civsim.gateway import access_log
from civsim.gateway.access_log import AccessLogError, export, find_container, parse, query, write

HEADER = '"ID","RTIME","CID","MODULE_NAME","URL","HTTP_STATUS","EXE_STATUS","ELAPSE","ERR_MSG"\n'
OK = ('"a1","2026-11-29 01:41:02","civsim-gov","/runs/{p}/government/observation",'
      '"/dgrc/runs/r1/government/observation","200","Y","13"," "\n')
BLOCKED = ('"b2","2026-11-29 01:41:01"," ","/runs/{p}/government/observation",'
           '"/dgrc/runs/r1/government/observation","403","N","3",'
           '"{""status"":403,""message"":""Token Violates Scope Authorization Access Settings""}"\n')


class FakeDocker:
    """記下每次呼叫的 docker 指令，依子指令（ps / exec）回傳事先準備好的結果。"""

    def __init__(self, ps="dgr-1\n", exec_out=HEADER + OK, exec_code=0, exec_err=""):
        self.calls = []
        self.results = {"ps": (0, ps, ""), "exec": (exec_code, exec_out, exec_err)}

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        code, out, err = self.results[cmd[1]]
        return subprocess.CompletedProcess(cmd, code, out.encode(), err.encode())


def test_parse_cleans_fields_and_sorts_by_time():
    rows = parse(HEADER + OK + BLOCKED)
    assert [r["log_id"] for r in rows] == ["b2", "a1"]
    blocked, ok = rows
    assert ok == {"time": "2026-11-29 01:41:02", "client_id": "civsim-gov", "api": "/runs/{p}/government/observation",
                  "url": "/dgrc/runs/r1/government/observation", "http_status": 200, "success": True,
                  "elapsed_ms": 13, "error": None, "log_id": "a1"}
    assert blocked["client_id"] is None and blocked["success"] is False
    assert blocked["error"] == "Token Violates Scope Authorization Access Settings"


def test_parse_keeps_one_row_per_id():
    """同一筆同時在暫存表（還沒有回應結果）和歷史表時，只留有結果的那一筆。"""
    pending = OK.replace('"200","Y","13"', '"","",""')
    rows = parse(HEADER + pending + OK)
    assert len(rows) == 1 and rows[0]["http_status"] == 200


@pytest.mark.parametrize("bad", ["", "r1' OR '1'='1", "r_1", "r1/government", "x" * 65])
def test_query_rejects_unsafe_run_id(bad):
    with pytest.raises(AccessLogError, match="run_id 格式不對"):
        query(bad)


def test_query_reads_both_tables():
    sql = query("20261129-a572")
    assert "TSMP_REQ_LOG" in sql and "TSMP_REQ_RES_LOG_HISTORY" in sql
    assert sql.count("'%/runs/20261129-a572/%'") == 2


def test_export_writes_jsonl(tmp_path):
    docker = FakeDocker(exec_out=HEADER + OK + BLOCKED)
    path, rows = export("r1", tmp_path / "run", runner=docker)
    assert path == tmp_path / "run" / "digirunner_access.jsonl"
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == rows
    ps, exec_ = docker.calls
    assert ps[:2] == ["docker", "ps"]
    assert exec_[:5] == ["docker", "exec", "dgr-1", "sh", "-c"]
    sql = exec_[-2]
    assert sql.startswith("CALL CSVWRITE('/tmp/civsim-access-") and "''%/runs/r1/%''" in sql


def test_given_container_skips_docker_ps(tmp_path):
    docker = FakeDocker()
    export("r1", tmp_path, container="my-dgr", runner=docker)
    assert [c[1] for c in docker.calls] == ["exec"] and docker.calls[0][2] == "my-dgr"


def test_no_rows_is_an_error_and_writes_nothing(tmp_path):
    with pytest.raises(AccessLogError, match="沒有 run r1 的紀錄"):
        export("r1", tmp_path, runner=FakeDocker(exec_out=HEADER))
    assert not (tmp_path / "digirunner_access.jsonl").exists()


def test_does_not_overwrite_a_bigger_file(tmp_path):
    write(parse(HEADER + OK + BLOCKED), tmp_path)
    with pytest.raises(AccessLogError, match="已經有 2 筆，這次只查到 1 筆"):
        write(parse(HEADER + OK), tmp_path)
    assert len((tmp_path / "digirunner_access.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_database_error_is_shown(tmp_path):
    docker = FakeDocker(exec_code=1, exec_err="Connection is broken: \"java.net.ConnectException\"")
    with pytest.raises(AccessLogError, match="(?s)讀不到 digiRunner 的資料庫（容器 dgr-1）.*ConnectException"):
        export("r1", tmp_path, runner=docker)


@pytest.mark.parametrize("ps, message", [("", "找不到正在跑的 digiRunner"),
                                         ("a\nb\n", "有好幾個 digiRunner 在跑（a、b）")])
def test_find_container(ps, message):
    with pytest.raises(AccessLogError, match=message):
        find_container(FakeDocker(ps=ps))


def test_docker_not_installed():
    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    with pytest.raises(AccessLogError, match="找不到 docker 指令"):
        find_container(missing)


def test_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(access_log.subprocess, "run", FakeDocker(exec_out=HEADER + OK + BLOCKED))
    main(["export-access-log", "r1", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "run r1：2 次經過 digiRunner 的呼叫（2026-11-29 01:41:01 ~ 2026-11-29 01:41:02）" in out
    assert "civsim-gov" in out and "Token Violates Scope Authorization Access Settings" in out
    assert (tmp_path / "digirunner_access.jsonl").exists()


def test_cli_failure_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(access_log.subprocess, "run", FakeDocker(ps=""))
    with pytest.raises(SystemExit) as e:
        main(["export-access-log", "r1", "--out", str(tmp_path)])
    assert e.value.code == 1 and "匯出失敗：找不到正在跑的 digiRunner" in capsys.readouterr().out
