"""模型 <-> JSON，給 HTTP API 與 gateway client 共用。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from civsim.models import (
    Action, ActionType, AgentState, Observation, PermissionRequest, Persona,
)


def observation_to_dict(obs: Observation) -> dict[str, Any]:
    data = asdict(obs)
    data["permissions"] = sorted(obs.permissions)
    return data


def observation_from_dict(data: dict[str, Any]) -> Observation:
    s = dict(data["self_state"])
    s["persona"] = Persona(**s["persona"])
    return Observation(
        tick=data["tick"],
        self_state=AgentState(**s),
        others=data["others"],
        prices=data["prices"],
        forecast=data["forecast"],
        permissions=set(data["permissions"]),
        pending_requests=[PermissionRequest(**r) for r in data["pending_requests"]],
        allow_info_sharing=data["allow_info_sharing"],
    )


def action_to_dict(action: Action) -> dict[str, Any]:
    return {"type": action.type.value, "params": action.params, "reason": action.reason}


def action_from_dict(agent_id: str, data: dict[str, Any]) -> Action:
    return Action(agent_id, ActionType(data["type"]), data.get("params", {}), data.get("reason", ""))
