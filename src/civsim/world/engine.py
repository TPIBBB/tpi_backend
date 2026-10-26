"""文明模擬引擎：觀察 → 決策 → 驗證 → 結算 → 記錄。"""

from __future__ import annotations

import random

from civsim.agents.base import AgentController
from civsim.analysis.metrics import snapshot_metrics
from civsim.config import SimConfig
from civsim.models import Action, Event, Observation, WorldState
from civsim.policy import PolicyStore, apply_institution
from civsim.policy.permissions import READ_FORECAST, READ_PRICES
from civsim.storage.recorder import NullRecorder, Recorder
from civsim.world import rules
from civsim.world.events import generate_events
from civsim.world.market import update_prices
from civsim.world.setup import create_world


class SimulationEngine:
    def __init__(
        self,
        config: SimConfig,
        controllers: dict[str, AgentController] | None = None,
        recorder: Recorder | None = None,
    ):
        self.config = config
        self.rng = random.Random(config.seed)
        self.world: WorldState = create_world(config, self.rng)
        self.policy: PolicyStore = apply_institution(self.world, config.institution, self.rng)
        if controllers is None:
            from civsim.agents import build_controllers  # 延後匯入，避免 agents <-> world 循環

            controllers = build_controllers(self.world, config)
        self.controllers = controllers
        self.recorder = recorder or NullRecorder()
        self.history: list[dict] = []
        self._pending_events: list[Event] | None = None

    # ---- 1. 觀察：只給 Agent 它有權看到的資訊 ----
    def observe(self, agent_id: str) -> Observation:
        world = self.world
        agent = world.agents[agent_id]
        perms = self.policy.permissions_of(agent_id)

        # 有正式權限 → 直接讀到預報，並記入自己的資訊
        if READ_FORECAST in perms:
            agent.known_info.update(world.forecasts)
        # 透過正式或非正式管道得知、且尚未過期的預報
        forecast = {
            k: v for k, v in agent.known_info.items()
            if k.startswith("forecast:") and v.get("tick", -1) >= world.tick
        }

        return Observation(
            tick=world.tick,
            self_state=agent,
            others=[{"id": a.id, "role": a.role} for a in world.living_agents() if a.id != agent_id],
            prices=dict(world.market.prices) if READ_PRICES in perms else None,
            forecast=forecast or None,
            permissions=perms,
            pending_requests=[r for r in world.pending_requests if r.target == agent_id],
            allow_info_sharing=self.config.allow_info_sharing,
        )

    # ---- 一個回合 ----
    def begin_tick(self) -> list[Event]:
        """回合開始：產生世界事件。之後 Agent 才能觀察到本回合的預報。"""
        self._pending_events = generate_events(self.world, self.config.events, self.rng)
        return self._pending_events

    def step(self, submitted: dict[str, list[Action]] | None = None) -> list[Event]:
        """執行一個回合。

        submitted=None：由本機的 controllers 決策（一般實驗）。
        submitted={agent_id: [Action]}：行動由外部（經 digiRunner 的 HTTP API）送進來，
        此時呼叫端必須先呼叫 begin_tick()。
        """
        world = self.world
        if submitted is None:
            events = self.begin_tick()
        else:
            events = self._pending_events
            if events is None:
                raise RuntimeError("外部送入行動前必須先呼叫 begin_tick()")
        self._pending_events = None

        # 2. 決策
        actions: list[Action] = []
        for agent in world.living_agents():
            if submitted is None:
                proposed = self.controllers[agent.id].decide(self.observe(agent.id))
            else:
                proposed = submitted.get(agent.id, [])
            for action in proposed:
                action.agent_id = agent.id  # Agent 不能替別人行動
                actions.append(action)

        # 3~4. 驗證與結算（打亂順序，避免固定先後造成優勢）
        self.rng.shuffle(actions)
        ctx = rules.TickContext(demand={}, allow_info_sharing=self.config.allow_info_sharing)
        for action in actions:
            error = rules.validate(world, self.policy, ctx, action)
            if error:
                events.append(
                    Event(world.tick, f"action:{action.type.value}", action.agent_id, False,
                          {"params": action.params}, error)
                )
                continue
            events.append(rules.settle(world, self.policy, ctx, action))

        update_prices(world.market, ctx.demand, self.config.market)
        events.extend(rules.end_of_tick_upkeep(world, self.config.action_points))

        # 5. 記錄
        metrics = snapshot_metrics(world, self.policy, events)
        self.history.append(metrics)
        self.recorder.record_tick(world, events, metrics)

        world.tick += 1
        return events

    def run(self, ticks: int | None = None) -> list[dict]:
        for _ in range(ticks or self.config.ticks):
            if not self.world.living_agents():
                break
            self.step()
        self.recorder.close()
        return self.history
