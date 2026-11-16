"""引擎的遠端反思模式（API 用）必須和本機模式跑出完全一樣的結果。"""

import json

import pytest

from civsim.agents import LLMGovernment
from civsim.agents.llm import ScriptedClient
from civsim.world import SimulationEngine
from civsim.world.government import GovernmentActionType, GovernmentDecision


class ListRecorder:
    def __init__(self):
        self.rows = []

    def record_tick(self, world, events, metrics):
        self.rows.append(("tick", world.tick, [(e.tick, e.kind) for e in events], metrics))

    def record_disaster(self, report):
        self.rows.append(("disaster", report))

    def record_memory(self, version, text):
        self.rows.append(("memory", version, text))

    def close(self):
        pass


def memory_for(report):
    return f"# 天災 {report['disaster_id']} 的經驗"


def local_engine(config):
    def respond(system, user):
        if "current_memory" in user:
            return json.dumps({"memory": memory_for(json.loads(user)["report"])})
        return json.dumps({"actions": [{"type": "import_food", "params": {"qty": 2}}]})

    return SimulationEngine(config, government=LLMGovernment(ScriptedClient(respond)), recorder=ListRecorder())


def remote_engine(config):
    engine = SimulationEngine(config, government=None, recorder=ListRecorder())
    engine.remote_reflection = True
    while engine.world.tick < config.total_ticks:
        if engine.pending_reflection is not None:
            engine.submit_memory(memory_for(engine.pending_reflection))
        else:
            engine.step([GovernmentDecision(GovernmentActionType.IMPORT_FOOD, {"qty": 2})])
    return engine


def test_remote_reflection_matches_local(small_config):
    local = local_engine(small_config)
    local.run()
    remote = remote_engine(small_config)

    assert remote.history == local.history
    assert remote.reports == local.reports
    assert remote.memory_versions == local.memory_versions == ["", "# 天災 1 的經驗", "# 天災 2 的經驗"]
    assert remote.recorder.rows == local.recorder.rows  # 紀錄檔的內容與順序都一樣


def test_step_refused_while_waiting(small_config):
    engine = SimulationEngine(small_config, government=None)
    engine.remote_reflection = True
    while engine.pending_reflection is None:
        engine.step([])
    tick = engine.world.tick
    with pytest.raises(RuntimeError, match="submit_memory"):
        engine.step([])
    assert engine.world.tick == tick == engine.schedule[0].window_end
    engine.submit_memory(None)
    assert engine.world.tick == tick + 1
    with pytest.raises(RuntimeError, match="沒有等待反思"):
        engine.submit_memory(None)
