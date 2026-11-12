"""文明模擬引擎。

一天（一回合）的流程：
1. 天災          world/disasters.py   設定今天的階段與收成倍率
2. 政府決策      agents/government.py 提出 → world/social_rules.py 檢查規則 → world/government.py 驗證與結算
3. 平民決策      每位平民跑一輪：依類型生產一次（收成／打工）、下一張買單或賣單，先生產再下單
4. 市場          world/market.py      集合競價，所有成交都用同一個價格
5. 吃飯          每人吃掉 food_per_day，不夠吃就算挨餓
6. 記錄          事件、指標
7. 評估期最後一天：analysis/goals.py 產生報告 → 政府反思、更新記憶 → 社會調回均衡狀態（初始世界）

政府先於平民結算，所以平民當天就看得到政府的價格上限；政府的買賣單和平民的單在同一場競價撮合。

API 模式（world-api 等政府經 digiRunner 送決策）：
    engine.begin_tick(); obs = engine.government_observation(); ...; engine.step(decisions)
"""

from __future__ import annotations

import copy
import random
from dataclasses import asdict
from typing import Any

from civsim.agents.base import AgentController
from civsim.analysis.goals import evaluate_disaster
from civsim.analysis.metrics import snapshot_metrics
from civsim.config import SimConfig
from civsim.models import FOOD, GOV_ID, Action, ActionType, Event, Observation, WorldState
from civsim.storage.recorder import NullRecorder, Recorder
from civsim.world import rules
from civsim.world.disasters import Disaster, begin_tick_events, build_schedule, disaster_at
from civsim.world.equilibrium import EquilibriumBand, calibrate
from civsim.world.government import GovernmentDecision, GovernmentObservation, settle, validate
from civsim.world.market import settle_market
from civsim.world.setup import create_world
from civsim.world.social_rules import MODES, find_violations, load_rules

_FROM_CONFIG: Any = object()  # 參數沒給時，依 config 建立


class SimulationEngine:
    def __init__(self, config: SimConfig, government=_FROM_CONFIG, recorder: Recorder | None = None,
                 band: EquilibriumBand | None = _FROM_CONFIG):
        """government：GovernmentController；None = 沒有政府；不給就依 config.government.controller 建立。
        band：均衡區間；None = 不計算（校準期本身）；不給就跑一次校準期。
        """
        if config.social_rules.mode not in MODES:
            raise ValueError(f"未知的 social_rules.mode: {config.social_rules.mode}，可用：{MODES}")
        self.config = config
        self.schedule: list[Disaster] = build_schedule(config.disasters)
        self.rules = load_rules(config.social_rules.path)
        self.recorder = recorder or NullRecorder()

        if government is _FROM_CONFIG:
            from civsim.agents import build_government  # 延後匯入，避免 agents <-> world 循環

            government = build_government(config)
        self.government = government

        self.calibration_prices: list[float] = []
        if band is _FROM_CONFIG:
            band, self.calibration_prices = calibrate(config)
        self.band: EquilibriumBand | None = band

        # 均衡狀態 = 初始世界；每次評估期結束都調回這個狀態
        self.initial_world: WorldState = create_world(config, random.Random(config.seed))
        self.world: WorldState = copy.deepcopy(self.initial_world)
        self.cycle = 0
        self._start_cycle(0)

        self.memory: str = config.government.initial_memory
        self.memory_versions: list[str] = [self.memory]
        self._llm_calls_recorded = 0  # 政府的 LLM 呼叫紀錄（LLMGovernment.calls）已經寫出幾筆
        self.reports: list[dict] = []
        self.history: list[dict] = []
        self._tick_open = False
        self._pending_events: list[Event] = []

        # 遠端反思（API 模式）：評估期最後一天跑完後先不重置世界，停在這裡等 submit_memory()。
        # 本機模式（False）直接呼叫 self.government.reflect()。見 docs/api.md 的 D6。
        self.remote_reflection = False
        self.pending_reflection: dict | None = None  # 等待反思的天災報告
        self._deferred: tuple | None = None  # (天災, 當天的世界, 當天的事件, 當天的指標)，反思完才寫入紀錄

    # ---- 天災週期 ----
    def _start_cycle(self, cycle: int) -> None:
        from civsim.agents import build_citizens

        self.cycle = cycle
        self.rng = random.Random(f"{self.config.seed}:engine:{cycle}")
        self.citizens: dict[str, AgentController] = build_citizens(self.world, self.config, cycle)
        self.cycle_history: list[dict] = []
        self.cycle_decisions: list[dict] = []  # 這次週期政府的所有決策結果（反思報告用）
        self.gov_actions_yesterday: list[dict] = []

    def _cycle_start_tick(self) -> int:
        d = disaster_at(self.schedule, self.world.tick)
        return d.cycle_start if d else 0

    def _reset_to_equilibrium(self, d: Disaster) -> Event:
        """除了政府記憶以外，全部回到初始世界的狀態（人口、平民庫存、政府預算與儲備、市場）。"""
        tick = self.world.tick
        self.world = copy.deepcopy(self.initial_world)
        self.world.tick = tick
        self._start_cycle(self.cycle + 1)
        return Event(tick, "world:reset", None, True, {"after_disaster": d.id})

    # ---- 觀察 ----
    def observe(self, citizen_id: str) -> Observation:
        m = self.world.market
        return Observation(
            tick=self.world.tick,
            self_state=self.world.citizens[citizen_id],
            price=m.price,
            customary_price=m.customary_price,
            price_cap=self._active_cap(),
            government_actions=list(self.gov_actions_yesterday),
        )

    def government_observation(self) -> GovernmentObservation:
        w = self.world
        cap = self._active_cap()
        show_rules = self.config.social_rules.mode == "enforce"
        return GovernmentObservation(
            tick=w.tick,
            prices={FOOD: w.market.price},
            memory=self.memory if self.config.government.memory else None,
            rules=self.rules.texts() if show_rules else [],
            budget=round(w.government.budget, 4),
            food_reserve=round(w.government.food_reserve, 4),
            population=len(w.living()),
            deaths=w.deaths,
            hungry=sum(1 for c in w.living() if c.hungry_days > 0),
            price_cap={"price": cap, "until": w.market.price_cap_until} if cap is not None else None,
            citizens=[{"id": c.id, "type": c.type.value} for c in w.living()],
            recent_decisions=self.cycle_decisions[-self.config.government.recent_decisions:],
        )

    def _active_cap(self) -> float | None:
        m = self.world.market
        if m.price_cap_until is not None and self.world.tick <= m.price_cap_until:
            return m.price_cap
        return None

    # ---- 一個回合 ----
    def begin_tick(self) -> list[Event]:
        """回合開始：設定天災階段。API 模式下，之後才能取得政府本回合的觀察。"""
        if not self._tick_open:
            m = self.world.market
            if m.price_cap_until is not None and self.world.tick > m.price_cap_until:
                m.price_cap = m.price_cap_until = None
            self._pending_events = begin_tick_events(self.world, self.schedule)
            self._tick_open = True
        return self._pending_events

    def step(self, decisions: list[GovernmentDecision] | None = None) -> list[Event]:
        """執行一個回合。decisions=None 時由本機的政府決策；API 模式下由外部送入。"""
        if self.pending_reflection is not None:
            raise RuntimeError("正在等待政府反思，請先呼叫 submit_memory()")
        world = self.world
        events = list(self.begin_tick())
        self._tick_open = False

        # 2. 政府
        if decisions is None and self.government is not None:
            decisions = self.government.decide(self.government_observation())
            self._record_llm_calls()
        events.extend(self._apply_government(decisions or []))

        # 3. 平民：每人跑一輪（生產一次 + 一張買賣單），先全部生產，再全部下單
        production: list[Action] = []
        trades: list[Action] = []
        for c in world.living():
            proposed = list(self.citizens[c.id].decide(self.observe(c.id)) or [])
            made, trade, extra = rules.plan_day(c.id, proposed)
            if made is None and trade is None:
                events.append(rules.settle(world, Action(c.id, ActionType.IDLE, {}, _idle_reason(proposed)),
                                           self.config.citizens, self.rng))
            production += [made] if made else []
            trades += [trade] if trade else []
            if extra:
                events.append(Event(world.tick, "action:extra", c.id, False,
                                    {"dropped": [a.type.value for a in extra]},
                                    "一天最多生產一次、下一張買賣單"))
        for batch in (production, trades):
            self.rng.shuffle(batch)
            for action in batch:
                error = rules.validate(world, action)
                if error:
                    events.append(Event(world.tick, f"action:{action.type.value}", action.agent_id, False,
                                        {"params": action.params}, error))
                else:
                    events.append(rules.settle(world, action, self.config.citizens, self.rng))

        # 4. 市場
        clearing, trade_events = settle_market(world, self.rng)
        events.extend(trade_events)

        # 5. 吃飯
        events.extend(rules.end_of_tick_upkeep(world, self.config.citizens))

        # 6. 記錄
        metrics = snapshot_metrics(world, clearing, events, day=world.tick - self._cycle_start_tick())
        if self.band is not None:
            metrics["in_band"] = self.band.contains(clearing.price) and not clearing.capped
        self.history.append(metrics)
        self.cycle_history.append(metrics)

        # 7. 評估期最後一天
        d = disaster_at(self.schedule, world.tick)
        if d is not None and world.tick == d.window_end:
            events.extend(self._close_cycle(d))
            if self.pending_reflection is not None:  # 遠端反思：這一天要等記憶送來才算結束
                self._deferred = (d, world, events, metrics)
                return events

        self.recorder.record_tick(world, events, metrics)
        self.world.tick += 1
        return events

    def _apply_government(self, decisions: list[GovernmentDecision]) -> list[Event]:
        world, cfg = self.world, self.config.government
        mode = self.config.social_rules.mode
        events: list[Event] = []
        accepted: list[dict] = []
        for i, d in enumerate(decisions):
            record = {"tick": world.tick, "type": d.type.value, "params": d.params, "reason": d.reason}
            error = None
            if i >= cfg.max_decisions_per_day:
                error = f"超過每天的決策上限 {cfg.max_decisions_per_day}"
            violations = find_violations(d, self.rules.rules) if mode != "off" and error is None else []
            if violations:
                ids = [r.id for r in violations]
                events.append(Event(world.tick, "rule:violation", GOV_ID, mode == "record",
                                    {**record, "rules": ids, "mode": mode}))
                if mode == "enforce":
                    error = "違反社會規則：" + "；".join(r.text for r in violations)
            if error is None:
                error = validate(world, d, cfg)
            if error is None:
                event = settle(world, d, cfg)
                events.append(event)
                record.update(accepted=True, result={k: v for k, v in event.payload.items() if k != "params"})
                accepted.append({"type": d.type.value, "params": d.params})
            else:
                events.append(Event(world.tick, "gov:rejected", GOV_ID, False, record, error))
                record.update(accepted=False, rejected_reason=error)
            self.cycle_decisions.append(record)
        self.gov_actions_yesterday = accepted
        return events

    def _close_cycle(self, d: Disaster) -> list[Event]:
        events: list[Event] = []
        if self.band is not None:
            report = evaluate_disaster(d, self.cycle_history, self.band, self.cycle_decisions)
            report["memory_version"] = len(self.memory_versions) - 1
            self.reports.append(report)
            self.recorder.record_disaster(report)
            events.append(Event(self.world.tick, "world:disaster_report", None, True,
                                {k: v for k, v in report.items() if k != "decisions"}))
            if self.remote_reflection and self.config.government.memory:
                self.pending_reflection = report  # 先不重置，等 submit_memory()
                return events
            events.extend(self._reflect(report))
        events.append(self._reset_to_equilibrium(d))
        return events

    def submit_memory(self, new: str | None) -> list[Event]:
        """遠端反思：送入政府的新版記憶（None = 不更新），接著把世界調回均衡狀態，結束評估期最後一天。"""
        if self.pending_reflection is None:
            raise RuntimeError("目前沒有等待反思的天災")
        d, world, events, metrics = self._deferred
        closing = self._apply_memory(new)
        closing.append(self._reset_to_equilibrium(d))
        self.pending_reflection = self._deferred = None
        events.extend(closing)
        self.recorder.record_tick(world, events, metrics)
        self.world.tick += 1
        return closing

    def _reflect(self, report: dict) -> list[Event]:
        cfg = self.config.government
        if self.government is None or not cfg.memory:
            return []
        new = self.government.reflect(report, self.memory)
        self._record_llm_calls()
        error = getattr(self.government, "last_reflect_error", None)
        if new is None and error:  # 反思失敗和「LLM 決定不改」要分開記錄
            return [Event(self.world.tick, "gov:memory_failed", GOV_ID, False, {"error": error},
                          "反思失敗，維持舊版記憶")]
        return self._apply_memory(new)

    def _record_llm_calls(self) -> None:
        """把政府新的 LLM 呼叫紀錄寫進 recorder（llm_calls.jsonl）。沒有呼叫紀錄的政府（例如 NoGovernment）就跳過。"""
        calls = getattr(self.government, "calls", None)
        record = getattr(self.recorder, "record_llm_call", None)  # 舊的 recorder 沒有這個方法就不寫
        if not calls or record is None:
            return
        for call in calls[self._llm_calls_recorded:]:
            record(asdict(call))
        self._llm_calls_recorded = len(calls)

    def _apply_memory(self, new) -> list[Event]:
        """引擎只檢查記憶的長度與格式，不審查內容；每個版本都保存。"""
        cfg = self.config.government
        tick = self.world.tick
        if new is None:
            return [Event(tick, "gov:memory_unchanged", GOV_ID, True)]
        if not isinstance(new, str) or len(new) > cfg.memory_max_chars:
            return [Event(tick, "gov:memory_rejected", GOV_ID, False, {"chars": len(str(new))},
                          f"記憶超過 {cfg.memory_max_chars} 字或格式錯誤，維持舊版")]
        self.memory = new
        self.memory_versions.append(new)
        self.recorder.record_memory(len(self.memory_versions) - 1, new)
        return [Event(tick, "gov:memory_updated", GOV_ID, True, {"version": len(self.memory_versions) - 1})]

    def run(self, ticks: int | None = None) -> list[dict]:
        for _ in range(ticks or self.config.total_ticks):
            self.step()
        self.recorder.close()
        return self.history

    def summary(self) -> dict:
        return {
            "band": self.band.to_dict() if self.band else None,
            "rules_version": self.rules.version,
            "reports": [{k: v for k, v in r.items() if k != "decisions"} for r in self.reports],
            "memory_versions": len(self.memory_versions),
            "schedule": [asdict(d) for d in self.schedule],
        }


def _idle_reason(proposed: list[Action]) -> str:
    idle = next((a for a in proposed if a.type == ActionType.IDLE), None)
    return idle.reason if idle else "沒有提出行動"
