"""政府 client 的測試：重試、逾時後確認已送達、run 作廢。不需要真的開 world-api 或 digiRunner。"""

import pytest

pytest.importorskip("fastapi")
import httpx
from fastapi.testclient import TestClient

from civsim.agents import NoGovernment
from civsim.api.server import create_app
from civsim.gateway.client import HttpWorldClient, RunInvalid, run_government
from civsim.world import SimulationEngine
from civsim.world.government import GovernmentActionType, GovernmentDecision

RUN = "test-run"


@pytest.fixture
def engine(small_config):
    return SimulationEngine(small_config, government=None)


@pytest.fixture
def server(engine):
    """world-api 本體（在記憶體裡，不開 port）。"""
    return TestClient(create_app(engine, run_id=RUN))


def flaky(server, fail):
    """模擬不穩定的網路：每個請求先問 fail(request, 第幾次)，回傳要怎麼出錯。

    fail 回傳 None → 正常轉給 world-api
    回傳 int       → 不轉給 world-api，直接回這個 HTTP 狀態碼（例如 digiRunner 回 503）
    回傳 "lost"    → 轉給 world-api 處理完，但回應在路上逾時
    回傳 "down"    → 連不上
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        what = fail(request, len(calls))
        if what == "down":
            raise httpx.ConnectError("連不上", request=request)
        if isinstance(what, int):
            return httpx.Response(what)
        r = server.request(request.method, request.url.raw_path.decode(), content=request.content,
                           headers={"content-type": request.headers.get("content-type", "")})
        if what == "lost":
            raise httpx.ReadTimeout("逾時", request=request)
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://digirunner")
    return http, calls


def client(http, **kw):
    return HttpWorldClient(http=http, backoff=0, **kw)


def is_post(request):
    return request.method == "POST"


class ImportEveryDay:
    def __init__(self):
        self.seen_memories = []

    def decide(self, obs):
        return [GovernmentDecision(GovernmentActionType.IMPORT_FOOD, {"qty": 1}, "測試")]

    def reflect(self, report, memory):
        self.seen_memories.append(memory)
        return f"# 天災 {report['disaster_id']}：{'成功' if report['success'] else '失敗'}"


def test_runs_whole_run(server, engine):
    summary = run_government(client(server), NoGovernment())
    assert summary == {"run_id": RUN, "days": engine.config.total_ticks,
                       "reflections": len(engine.schedule), "recovered": 0}
    assert engine.world.tick == engine.config.total_ticks
    assert engine.memory_versions == [""]  # NoGovernment 從不更新記憶


def test_reflection_updates_memory(server, engine):
    gov, reflected = ImportEveryDay(), []
    run_government(client(server), gov, on_reflect=lambda report, r: reflected.append(r["memory_result"]))
    assert reflected == ["updated", "updated"]
    assert gov.seen_memories == ["", engine.memory_versions[1]]  # 第二次反思時讀得到第一次寫的記憶
    assert len(engine.memory_versions) == 3


def test_decisions_reach_engine(server, engine):
    days = []
    run_government(client(server), ImportEveryDay(), on_day=days.append)
    assert all(d["decisions"][0]["type"] == "import_food" and d["decisions"][0]["accepted"] for d in days)


def test_finds_the_only_run_and_sends_run_id_header(engine):
    seen = []
    http, _ = flaky(TestClient(create_app(engine, run_id=RUN)), lambda r, n: seen.append(r.headers.get("x-run-id")))
    c = client(http)
    c.observe()
    assert c.run_id == RUN and seen[-1] == RUN


def test_retries_503_then_succeeds(server, engine):
    http, calls = flaky(server, lambda r, n: 503 if is_post(r) and n <= 2 else None)
    c = client(http, run_id=RUN)
    result = c.submit(0, [])
    assert result["next_tick"] == 1 and engine.world.tick == 1
    assert sum(is_post(r) for r in calls) == 3  # 503、503、成功


def test_retries_connection_error(server, engine):
    http, _ = flaky(server, lambda r, n: "down" if n == 1 else None)
    assert client(http, run_id=RUN).observe()["observation"]["tick"] == 0


def test_gives_up_after_max_retries(server, engine):
    http, calls = flaky(server, lambda r, n: 503 if is_post(r) else None)
    with pytest.raises(RunInvalid, match="重試 2 次仍然失敗"):
        client(http, run_id=RUN, max_retries=2).submit(0, [])
    assert sum(is_post(r) for r in calls) == 3  # 第一次 + 重試 2 次
    assert engine.world.tick == 0


def test_backoff_doubles(server):
    waits = []
    http, _ = flaky(server, lambda r, n: 503)
    with pytest.raises(RunInvalid):
        HttpWorldClient(http=http, run_id=RUN, max_retries=3, backoff=1, sleep=waits.append).observe()
    assert waits == [1, 2, 4]


def test_lost_response_is_not_sent_twice(server, engine):
    """world-api 處理完了，回應卻逾時 → 重送收到 409 → 確認世界只前進一天，不算錯誤。"""
    lost = {"done": False}

    def fail(request, n):
        if is_post(request) and not lost["done"]:
            lost["done"] = True
            return "lost"
        return None

    http, _ = flaky(server, fail)
    c = client(http, run_id=RUN)
    result = c.submit(0, [{"type": "import_food", "params": {"qty": 5}}])
    assert result["recovered"] is True and result["decisions"] is None and result["next_tick"] == 1
    assert engine.world.tick == 1  # 只跑了一天
    assert c.recovered == 1
    recent = c.observe()["observation"]["recent_decisions"]
    assert recent[-1]["type"] == "import_food"  # 隔天仍看得到結果


def lose_first(path_part):
    """路徑包含 path_part 的第一個 POST：world-api 處理完，回應卻逾時。"""
    lost = {"done": False}

    def fail(request, n):
        if is_post(request) and path_part in request.url.path and not lost["done"]:
            lost["done"] = True
            return "lost"
        return None

    return fail


def test_lost_decision_on_last_day_of_window(server, engine):
    """評估期最後一天的決策回應遺失：世界停在同一天等反思，也要判斷成已送達。"""
    window_end = engine.schedule[0].window_end
    c = client(server, run_id=RUN)
    for tick in range(window_end):
        c.submit(tick, [])
    http, _ = flaky(server, lose_first("decisions"))
    result = client(http, run_id=RUN).submit(window_end, [])
    assert result["recovered"] is True and result["status"] == "awaiting_reflection"
    assert engine.world.tick == window_end and engine.pending_reflection is not None


def test_lost_memory_response_is_not_invalid(server, engine):
    window_end = engine.schedule[0].window_end
    c = client(server, run_id=RUN)
    for tick in range(window_end + 1):
        c.submit(tick, [])
    http, _ = flaky(server, lose_first("memory"))
    result = client(http, run_id=RUN).submit_memory("# 記憶", window_end)
    assert result["recovered"] is True and result["memory_result"] is None
    assert result["status"] == "awaiting_decision" and result["next_tick"] == window_end + 1
    assert engine.memory == "# 記憶" and len(engine.memory_versions) == 2  # 只送到一次


def test_tick_mismatch_without_retry_is_invalid(server):
    """沒有重送卻收到 409，代表有別人推進了世界（例如 /admin/step），不能繼續。"""
    c = client(server, run_id=RUN)
    server.post("/admin/step")
    with pytest.raises(RunInvalid, match="409"):
        c.submit(0, [])


def test_unknown_run_is_invalid(server):
    with pytest.raises(RunInvalid, match="找不到"):
        client(server, run_id="nope").run_status()
    with pytest.raises(RunInvalid, match="404"):
        client(server, run_id="nope").observe()


def test_invalid_run_stops_instead_of_idling(server, engine):
    """跑到一半 world-api 掛掉 → 整個 run 作廢，不會默默不行動繼續跑。"""
    http, _ = flaky(server, lambda r, n: "down" if n > 10 else None)
    with pytest.raises(RunInvalid):
        run_government(client(http, run_id=RUN, max_retries=1), NoGovernment())
    assert 0 < engine.world.tick < engine.config.total_ticks
